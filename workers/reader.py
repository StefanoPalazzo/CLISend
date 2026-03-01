"""
workers/reader.py — Worker de Lectura (Proceso independiente)

Maneja operaciones de solo lectura sobre la carpeta compartida:
  - LIST: listar archivos y directorios
  - DOWNLOAD: leer un archivo y devolver su contenido

Corre como proceso separado para no bloquear el Event Loop del servidor.
Las lecturas son seguras para concurrencia (múltiples lecturas simultáneas no causan problemas).
"""

import os
import signal
import logging
from multiprocessing import Queue
from concurrent.futures import ThreadPoolExecutor

MAX_CAT_SIZE = 4096  # Max bytes to return for a CAT command



def _list_files(shared_folder: str, rel_path: str) -> dict:
    """Lista archivos y carpetas en una ruta relativa dentro de la carpeta compartida."""
    if rel_path in ("/", "", "."):
        rel_path = ""
    rel_path = rel_path.lstrip("/")
    target = os.path.normpath(os.path.join(shared_folder, rel_path))

    # Protección contra path traversal (../../etc/passwd)
    if not os.path.realpath(target).startswith(os.path.realpath(shared_folder)):
        return {"status": "error", "message": "Ruta no permitida"}

    if not os.path.isdir(target):
        return {"status": "error", "message": f"Directorio no encontrado: {rel_path or '/'}"}

    entries = []
    for name in sorted(os.listdir(target)):
        full = os.path.join(target, name)
        entry = {
            "name": name,
            "is_dir": os.path.isdir(full),
            "size": os.path.getsize(full) if os.path.isfile(full) else 0,
        }
        entries.append(entry)

    return {"status": "ok", "entries": entries}


def _read_file(shared_folder: str, rel_path: str) -> dict:
    """Lee un archivo y devuelve su contenido como bytes."""
    rel_path = rel_path.lstrip("/")
    target = os.path.normpath(os.path.join(shared_folder, rel_path))

    # Protección contra path traversal
    if not os.path.realpath(target).startswith(os.path.realpath(shared_folder)):
        return {"status": "error", "message": "Ruta no permitida"}

    if not os.path.isfile(target):
        return {"status": "error", "message": f"Archivo no encontrado: {rel_path}"}

    try:
        size = os.path.getsize(target)
        with open(target, "rb") as f:
            data = f.read()
        return {
            "status": "ok",
            "size": size,
            "data": data,
            "path": rel_path,
        }
    except PermissionError:
        return {"status": "error", "message": f"Permiso denegado: {rel_path}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _cat_file(shared_folder: str, rel_path: str) -> dict:
    """Lee un extracto de un archivo de texto para previsualización."""
    rel_path = rel_path.lstrip("/")
    target = os.path.normpath(os.path.join(shared_folder, rel_path))

    # Protección contra path traversal
    if not os.path.realpath(target).startswith(os.path.realpath(shared_folder)):
        return {"status": "error", "message": "Ruta no permitida"}

    if not os.path.isfile(target):
        return {"status": "error", "message": f"Archivo no encontrado: {rel_path}"}

    try:
        size = os.path.getsize(target)
        read_size = min(size, MAX_CAT_SIZE)
        
        with open(target, "rb") as f:
            data = f.read(read_size)
            
        # Intentar decodificar para asegurar que es texto y no binario
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            return {"status": "error", "message": "El archivo parece ser binario y no se puede imprimir."}
            
        if size > MAX_CAT_SIZE:
            text += f"\n\n[... Archivo muy grande, mostrando primeros {MAX_CAT_SIZE} bytes ...]"
            
        return {
            "status": "ok",
            "text": text,
            "path": rel_path,
        }
    except PermissionError:
        return {"status": "error", "message": f"Permiso denegado: {rel_path}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def _process_request(request: dict, response_queue: Queue, shared_folder: str):
    """Procesa una única petición y envía la respuesta a la cola."""
    req_id = request.get("id")
    action = request.get("action", "").upper()
    path = request.get("path", "/")

    try:
        if action == "LIST":
            result = _list_files(shared_folder, path)
        elif action == "DOWNLOAD":
            result = _read_file(shared_folder, path)
        elif action == "CAT":
            result = _cat_file(shared_folder, path)
        else:
            result = {"status": "error", "message": f"Acción desconocida: {action}"}
    except Exception as e:
        result = {"status": "error", "message": f"Error interno: {e}"}

    result["id"] = req_id
    result["action"] = action
    response_queue.put(result)


def reader_worker(request_queue: Queue, response_queue: Queue, shared_folder: str):
    """
    Proceso principal del Worker de Lectura.
    Usa un ThreadPoolExecutor internamente para procesar múltiples lecturas en paralelo,
    evitando que un archivo grande bloquee a otros clientes que solicitan un LIST o archivos pequeños.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    shared_folder = os.path.abspath(shared_folder)
    logging.info(f"[READER] Iniciado. Carpeta: {shared_folder}")

    # Pool de hilos para concurrencia de lectura
    executor = ThreadPoolExecutor(max_workers=10)

    try:
        while True:
            request = request_queue.get()

            if request is None:
                break
                
            # Despacha el trabajo al pool de hilos en lugar de procesarlo sincrónicamente
            executor.submit(_process_request, request, response_queue, shared_folder)

    finally:
        executor.shutdown(wait=False)
        logging.info("[READER] Detenido.")
