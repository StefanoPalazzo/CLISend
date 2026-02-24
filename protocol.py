"""
protocol.py — Protocolo de comunicación Cliente <-> Servidor

Formato de mensajes sobre TCP:
  [4 bytes: longitud del JSON en big-endian][JSON payload]

Para transferencia de archivos:
  1. Se envía un mensaje JSON con la metadata (action, path, size...)
  2. Seguido de los bytes crudos del archivo (si aplica)

Esto evita problemas de delimitación de mensajes en TCP (stream-based).
Un simple \\n no sirve como delimitador porque los datos binarios de un archivo
pueden contener \\n. El length-prefix es la solución profesional.
"""

import json
import struct
import asyncio

HEADER_SIZE = 4  # 4 bytes para longitud del mensaje (hasta ~4 GB)


# ─────────────────────────────────────────────
#  Funciones SYNC (usadas por el cliente)
# ─────────────────────────────────────────────

def send_message(sock, msg: dict):
    payload = json.dumps(msg).encode("utf-8")
    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)


def recv_message(sock) -> dict:
    raw_header = recv_exact(sock, HEADER_SIZE)
    if not raw_header:
        return None
    msg_len = struct.unpack("!I", raw_header)[0]
    raw_payload = recv_exact(sock, msg_len)
    if not raw_payload:
        return None
    return json.loads(raw_payload.decode("utf-8"))


def send_file_data(sock, filepath: str, chunk_size: int = 8192):
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sock.sendall(chunk)


def recv_file_data(sock, size: int, filepath: str, chunk_size: int = 8192,
                   progress_callback=None):
    received = 0
    with open(filepath, "wb") as f:
        while received < size:
            to_read = min(chunk_size, size - received)
            chunk = recv_exact(sock, to_read)
            if not chunk:
                raise ConnectionError("Conexión cerrada durante transferencia")
            f.write(chunk)
            received += len(chunk)
            if progress_callback:
                progress_callback(received, size)


def recv_exact(sock, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


#  Funciones ASYNC (usadas por el servidor)


async def async_send_message(writer: asyncio.StreamWriter, msg: dict):
    payload = json.dumps(msg).encode("utf-8")
    header = struct.pack("!I", len(payload))
    writer.write(header + payload)
    await writer.drain()


async def async_recv_message(reader: asyncio.StreamReader) -> dict:
    raw_header = await async_recv_exact(reader, HEADER_SIZE)
    if not raw_header:
        return None
    msg_len = struct.unpack("!I", raw_header)[0]
    raw_payload = await async_recv_exact(reader, msg_len)
    if not raw_payload:
        return None
    return json.loads(raw_payload.decode("utf-8"))


async def async_recv_file_data(reader: asyncio.StreamReader, size: int,
                               filepath: str, chunk_size: int = 8192):
    received = 0
    with open(filepath, "wb") as f:
        while received < size:
            to_read = min(chunk_size, size - received)
            chunk = await reader.readexactly(to_read)
            f.write(chunk)
            received += len(chunk)


async def async_send_file_data(writer: asyncio.StreamWriter, filepath: str,
                               chunk_size: int = 8192):
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()


async def async_recv_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    try:
        return await reader.readexactly(n)
    except asyncio.IncompleteReadError:
        return None
