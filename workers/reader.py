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


def reader_worker(request_queue: Queue, response_queue: Queue, shared_folder: str):
    """
    Proceso principal del Worker de Lectura.
    Lee peticiones de request_queue, las procesa, y pone resultados en response_queue.
    Se detiene al recibir None.
    """
    # Ignorar SIGINT para que solo el padre maneje Ctrl+C (evita zombies)
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    shared_folder = os.path.abspath(shared_folder)
    logging.info(f"[READER] Iniciado. Carpeta: {shared_folder}")

    try:
        while True:
            request = request_queue.get()

            if request is None:
                break

            req_id = request.get("id")
            action = request.get("action", "").upper()
            path = request.get("path", "/")

            try:
                if action == "LIST":
                    result = _list_files(shared_folder, path)
                elif action == "DOWNLOAD":
                    result = _read_file(shared_folder, path)
                else:
                    result = {"status": "error", "message": f"Acción desconocida: {action}"}
            except Exception as e:
                result = {"status": "error", "message": f"Error interno: {e}"}

            result["id"] = req_id
            result["action"] = action
            response_queue.put(result)

    finally:
        logging.info("[READER] Detenido.")
