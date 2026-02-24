"""
workers/writer.py — Worker de Escritura (Proceso independiente)

Maneja operaciones que modifican la carpeta compartida:
  - UPLOAD: guardar un archivo recibido del cliente
  - DELETE: eliminar un archivo
  - CUT: operación atómica que lee, elimina y devuelve el contenido

Corre como proceso separado para:
1. No bloquear el Event Loop del servidor
2. Serializar escrituras (una a la vez) para evitar corrupción de datos

Las escrituras son PELIGROSAS en concurrencia. Este Worker las procesa
secuencialmente desde la Queue, garantizando consistencia.
"""

import os
import shutil
import signal
import logging
from multiprocessing import Queue


def _save_file(shared_folder: str, rel_path: str, data: bytes) -> dict:
    """Guarda bytes en un archivo dentro de la carpeta compartida."""
    rel_path = rel_path.lstrip("/")
    target = os.path.normpath(os.path.join(shared_folder, rel_path))

    if not os.path.realpath(target).startswith(os.path.realpath(shared_folder)):
        return {"status": "error", "message": "Ruta no permitida"}

    # Crear directorios intermedios si no existen
    target_dir = os.path.dirname(target)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    try:
        with open(target, "wb") as f:
            f.write(data)
        return {
            "status": "ok",
            "message": f"Archivo guardado: {rel_path} ({len(data)} bytes)",
        }
    except PermissionError:
        return {"status": "error", "message": f"Permiso denegado: {rel_path}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _delete_file(shared_folder: str, rel_path: str) -> dict:
    """Elimina un archivo de la carpeta compartida."""
    rel_path = rel_path.lstrip("/")
    target = os.path.normpath(os.path.join(shared_folder, rel_path))

    if not os.path.realpath(target).startswith(os.path.realpath(shared_folder)):
        return {"status": "error", "message": "Ruta no permitida"}

    if not os.path.exists(target):
        return {"status": "error", "message": f"Archivo no encontrado: {rel_path}"}

    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
            return {"status": "ok", "message": f"Directorio eliminado: {rel_path}"}
        else:
            os.remove(target)
            return {"status": "ok", "message": f"Archivo eliminado: {rel_path}"}
    except PermissionError:
        return {"status": "error", "message": f"Permiso denegado: {rel_path}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _cut_file(shared_folder: str, rel_path: str) -> dict:
    """
    'Cortar' un archivo: lo lee, lo elimina, y devuelve su contenido.
    Operación ATÓMICA: lee + borra en un solo paso del Worker,
    evitando que otro cliente vea el archivo a medio borrar.
    """
    rel_path = rel_path.lstrip("/")
    target = os.path.normpath(os.path.join(shared_folder, rel_path))

    if not os.path.realpath(target).startswith(os.path.realpath(shared_folder)):
        return {"status": "error", "message": "Ruta no permitida"}

    if not os.path.isfile(target):
        return {"status": "error", "message": f"Archivo no encontrado: {rel_path}"}

    try:
        with open(target, "rb") as f:
            data = f.read()
        size = len(data)
        os.remove(target)
        return {
            "status": "ok",
            "message": f"Archivo cortado: {rel_path} ({size} bytes)",
            "data": data,
            "size": size,
            "path": rel_path,
        }
    except PermissionError:
        return {"status": "error", "message": f"Permiso denegado: {rel_path}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def writer_worker(request_queue: Queue, response_queue: Queue, shared_folder: str):
    """
    Proceso principal del Worker de Escritura.
    Procesa peticiones de forma SECUENCIAL (una a la vez) para evitar
    problemas de concurrencia en escritura.
    Se detiene al recibir None.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    shared_folder = os.path.abspath(shared_folder)
    logging.info(f"[WRITER] Iniciado. Carpeta: {shared_folder}")

    try:
        while True:
            request = request_queue.get()

            if request is None:
                break

            req_id = request.get("id")
            action = request.get("action", "").upper()
            path = request.get("path", "")

            try:
                if action == "UPLOAD":
                    data = request.get("data", b"")
                    result = _save_file(shared_folder, path, data)
                elif action == "DELETE":
                    result = _delete_file(shared_folder, path)
                elif action == "CUT":
                    result = _cut_file(shared_folder, path)
                else:
                    result = {"status": "error", "message": f"Acción desconocida: {action}"}
            except Exception as e:
                result = {"status": "error", "message": f"Error interno: {e}"}

            result["id"] = req_id
            result["action"] = action
            response_queue.put(result)

    finally:
        logging.info("[WRITER] Detenido.")
