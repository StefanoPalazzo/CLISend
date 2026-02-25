"""
server.py — Servidor AsyncIO Principal de Clisend
"""

import asyncio
import argparse
import multiprocessing
import os
import signal
import sys
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from protocol import async_send_message, async_recv_message
from workers.reader import reader_worker
from workers.writer import writer_worker
from workers.logger import logger_worker

# ─────────────────────────────────────────────
#  Configuración
# ─────────────────────────────────────────────

DEFAULT_PORT = 65432
DEFAULT_FOLDER = "."
DEFAULT_DB = "logs.db"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

# Colas IPC
read_request_q = multiprocessing.Queue()
read_response_q = multiprocessing.Queue()
write_request_q = multiprocessing.Queue()
write_response_q = multiprocessing.Queue()
log_q = multiprocessing.Queue()

# Referencias a workers hijos
workers_procs = []

# Estado asíncrono
pending_requests: dict[str, asyncio.Future] = {}
clients: dict[str, dict] = {}
executor = ThreadPoolExecutor(max_workers=2)

# Configuración del host (seteada en main)
shared_folder_path = ""
db_path_file = ""


#  Manejo de Workers

def start_workers():
    global workers_procs
    
    r_proc = multiprocessing.Process(
        target=reader_worker,
        args=(read_request_q, read_response_q, shared_folder_path),
        daemon=True,
        name="Worker-Reader"
    )
    w_proc = multiprocessing.Process(
        target=writer_worker,
        args=(write_request_q, write_response_q, shared_folder_path),
        daemon=True,
        name="Worker-Writer"
    )
    l_proc = multiprocessing.Process(
        target=logger_worker,
        args=(log_q, db_path_file),
        daemon=True,
        name="Worker-Logger"
    )

    r_proc.start()
    w_proc.start()
    l_proc.start()

    workers_procs.extend([r_proc, w_proc, l_proc])

    logging.info("Workers iniciados:")
    logging.info(f"  Reader PID: {r_proc.pid}")
    logging.info(f"  Writer PID: {w_proc.pid}")
    logging.info(f"  Logger PID: {l_proc.pid}")


def stop_workers():
    logging.info("Deteniendo Workers...")
    try:
        read_request_q.put(None)
        write_request_q.put(None)
        log_q.put(None)
    except Exception:
        pass

    for proc in workers_procs:
        if proc and proc.is_alive():
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()

    executor.shutdown(wait=False)
    logging.info("Todos los Workers detenidos.")


#  Comunicación con Workers

async def send_to_worker(queue_req, queue_resp, request: dict) -> dict:
    req_id = str(uuid.uuid4())
    request["id"] = req_id

    loop = asyncio.get_event_loop()
    future = loop.create_future()
    pending_requests[req_id] = (future, queue_resp)

    await loop.run_in_executor(executor, queue_req.put, request)

    result = await future
    del pending_requests[req_id]
    return result


def _try_get(q):
    try:
        return q.get_nowait()
    except Exception:
        return None


async def poll_response_queues():
    loop = asyncio.get_event_loop()
    while True:
        for resp_q in (read_response_q, write_response_q):
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(executor, _try_get, resp_q),
                    timeout=0.05
                )
                if result is not None:
                    req_id = result.get("id")
                    if req_id in pending_requests:
                        future, _ = pending_requests[req_id]
                        if not future.done():
                            future.set_result(result)
            except (asyncio.TimeoutError, Exception):
                pass
        
        await asyncio.sleep(0.01)


def log_event(client_name: str, client_ip: str, client_port: int,
              action: str, path: str = "", status: str = "ok", detail: str = ""):
    """Encola evento para el Worker de Logger."""
    log_q.put({
        "timestamp": datetime.now().isoformat(),
        "client_name": client_name,
        "client_ip": client_ip,
        "client_port": client_port,
        "action": action,
        "path": path,
        "status": status,
        "detail": detail,
    })


#  Manejo de Cliente Individual (Protocolo)

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    client_ip, client_port = addr[0], addr[1]
    client_id = f"{client_ip}:{client_port}"

    # Handshake
    msg = await async_recv_message(reader)
    if not msg or "name" not in msg:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return

    client_name = msg["name"]
    clients[client_id] = {"name": client_name, "ip": client_ip, "port": client_port}

    logging.info(f"[+] Cliente conectado: {client_name} ({client_id})")
    log_event(client_name, client_ip, client_port, "CONNECT",
              detail=f"Cliente {client_name} conectado")

    await async_send_message(writer, {
        "status": "ok",
        "message": f"Bienvenido {client_name}! Conectado al servidor Clisend.",
    })

    # Loop principal de Comandos
    try:
        while True:
            msg = await async_recv_message(reader)
            if msg is None:
                break

            action = msg.get("action", "").upper()
            path = msg.get("path", "/")
            logging.info(f"[{client_name}] -> {action} {path}")

            if action == "LIST":
                result = await send_to_worker(
                    read_request_q, read_response_q,
                    {"action": "LIST", "path": path}
                )
                await async_send_message(writer, {
                    "status": result["status"],
                    "action": "LIST",
                    "entries": result.get("entries", []),
                    "message": result.get("message", ""),
                })
                log_event(client_name, client_ip, client_port, "LIST", path, result["status"])

            elif action == "DOWNLOAD":
                result = await send_to_worker(
                    read_request_q, read_response_q,
                    {"action": "DOWNLOAD", "path": path}
                )
                if result["status"] == "ok":
                    await async_send_message(writer, {
                        "status": "ok",
                        "action": "DOWNLOAD",
                        "path": result["path"],
                        "size": result["size"],
                    })
                    writer.write(result["data"])
                    await writer.drain()
                else:
                    await async_send_message(writer, {
                        "status": "error", "action": "DOWNLOAD",
                        "message": result.get("message", "Error desc"),
                    })
                log_event(client_name, client_ip, client_port, "DOWNLOAD", path, result["status"])

            elif action == "UPLOAD":
                file_size = msg.get("size", 0)
                await async_send_message(writer, {"status": "ready", "action": "UPLOAD"})
                
                # Leemos bytes crudos
                file_data = await reader.readexactly(file_size)
                
                result = await send_to_worker(
                    write_request_q, write_response_q,
                    {"action": "UPLOAD", "path": path, "data": file_data}
                )
                await async_send_message(writer, {
                    "status": result["status"],
                    "action": "UPLOAD",
                    "message": result.get("message", ""),
                })
                log_event(client_name, client_ip, client_port, "UPLOAD", path, result["status"], f"{file_size}b")

            elif action == "DELETE":
                result = await send_to_worker(
                    write_request_q, write_response_q,
                    {"action": "DELETE", "path": path}
                )
                await async_send_message(writer, {
                    "status": result["status"],
                    "action": "DELETE",
                    "message": result.get("message", ""),
                })
                log_event(client_name, client_ip, client_port, "DELETE", path, result["status"])

            elif action == "CUT":
                result = await send_to_worker(
                    write_request_q, write_response_q,
                    {"action": "CUT", "path": path}
                )
                if result["status"] == "ok":
                    await async_send_message(writer, {
                        "status": "ok",
                        "action": "CUT",
                        "path": result["path"],
                        "size": result["size"],
                    })
                    writer.write(result["data"])
                    await writer.drain()
                else:
                    await async_send_message(writer, {
                        "status": "error", "action": "CUT",
                        "message": result.get("message", "Error desc"),
                    })
                log_event(client_name, client_ip, client_port, "CUT", path, result["status"])

            else:
                await async_send_message(writer, {"status": "error", "message": f"Desconocido: {action}"})

    except asyncio.IncompleteReadError:
        pass
    except ConnectionResetError:
        logging.warning(f"[-] Cliente '{client_name}' desconectado abruptamente.")
    except Exception as e:
        logging.error(f"[!] Error con {client_name}: {e}")
    finally:
        if client_id in clients:
            del clients[client_id]
        log_event(client_name, client_ip, client_port, "DISCONNECT")
        logging.info(f"[-] Cliente desconectado: {client_name}")
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

async def async_main(host: str, port: int):
    os.makedirs(shared_folder_path, exist_ok=True)
    
    start_workers()
    poll_task = asyncio.create_task(poll_response_queues())
    
    server = await asyncio.start_server(handle_client, host, port)
    
    addr = server.sockets[0].getsockname()
    logging.info(f"{'='*55}")
    logging.info(f"  CLISEND SERVER")
    logging.info(f"  Escuchando en {addr[0]}:{addr[1]}")
    logging.info(f"  Carpeta compartida: {shared_folder_path}")
    logging.info(f"  Base de datos: {db_path_file}")
    logging.info(f"{'='*55}")
    
    try:
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        poll_task.cancel()
        stop_workers()



def main():
    global shared_folder_path, db_path_file
    
    parser = argparse.ArgumentParser(description="Clisend Server Funcional")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("-f", "--folder", type=str, default=DEFAULT_FOLDER)
    parser.add_argument("--host", type=str, default=None)
    parser.add_argument("--db", type=str, default=DEFAULT_DB)
    args = parser.parse_args()

    shared_folder_path = os.path.abspath(args.folder)
    db_path_file = os.path.abspath(args.db)

    multiprocessing.set_start_method('fork', force=True)

    # El SO limpia los hijos zombies
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    # Manejo de apagado
    def shutdown_handler(sig, frame):
        logging.info("\nSeñal de apagado recibida. Cerrando servidor...")
        stop_workers()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        asyncio.run(async_main(args.host, args.port))
    except KeyboardInterrupt:
        logging.info("Servidor apagado.")


if __name__ == "__main__":
    main()
