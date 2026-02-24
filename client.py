"""
client.py — Cliente CLI Interactivo de Clisend

Se conecta al servidor, se identifica con un nombre, y permite
ejecutar operaciones sobre la carpeta compartida del Host.

Uso:
    python3 client.py <nombre> [--host HOST] [--port PORT]

Comandos disponibles:
    ls [ruta]        - Listar archivos de la carpeta compartida
    cp <archivo>     - Descargar un archivo del host
    put <archivo>    - Subir un archivo local al host
    rm <archivo>     - Eliminar un archivo del host
    cut <archivo>    - Cortar (descargar + eliminar atómicamente del host)
    help             - Mostrar ayuda
    exit             - Desconectarse
"""

import argparse
import os
import socket
import sys

from protocol import send_message, recv_message, send_file_data, recv_file_data, recv_exact


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 65432
DOWNLOAD_FOLDER = "./downloads"


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"


def print_entries(entries: list):
    # Muestra una lista de archivos/carpetas formateada con emojis y columnas
    if not entries:
        print("  (carpeta vacía)")
        return

    print(f"  {'Nombre':<35} {'Tipo':<10} {'Tamaño':<15}")
    print(f"  {'─'*35} {'─'*10} {'─'*15}")
    for entry in entries:
        name = entry["name"]
        is_dir = entry.get("is_dir", False)
        size = entry.get("size", 0)

        tipo = "📁 DIR" if is_dir else "📄 FILE"
        size_str = "" if is_dir else format_size(size)
        display_name = f"{name}/" if is_dir else name
        print(f"  {display_name:<35} {tipo:<10} {size_str:<15}")


def print_help():
    """Muestra los comandos disponibles."""
    print("""
╔═══════════════════════════════════════════════════════╗
║                CLISEND — Comandos                     ║
╠═══════════════════════════════════════════════════════╣
║  ls [ruta]         Listar archivos del host           ║
║  cp <archivo>      Descargar archivo del host         ║
║  put <archivo>     Subir archivo local al host        ║
║  rm <archivo>      Eliminar archivo del host          ║
║  cut <archivo>     Cortar archivo del host a tu PC    ║
║  help              Mostrar esta ayuda                 ║
║  exit              Desconectarse                      ║
╚═══════════════════════════════════════════════════════╝
""")


def print_progress(received: int, total: int):
    pct = (received / total) * 100
    bar_len = 30
    filled = int(bar_len * received / total)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {pct:.1f}% ({format_size(received)}/{format_size(total)})",
          end="", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Clisend — Cliente de transferencia de archivos",
    )
    parser.add_argument("name", type=str, help="Tu nombre/alias para el servidor")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST,
                        help=f"IP del servidor (default: {DEFAULT_HOST})")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT,
                        help=f"Puerto del servidor (default: {DEFAULT_PORT})")
    parser.add_argument("-d", "--download-dir", type=str, default=DOWNLOAD_FOLDER,
                        help=f"Carpeta para descargas (default: {DOWNLOAD_FOLDER})")

    args = parser.parse_args()

    client_name = args.name
    download_dir = os.path.abspath(args.download_dir)
    os.makedirs(download_dir, exist_ok=True)

    print(f"\n[*] Conectando a {args.host}:{args.port} como '{client_name}'...")

    try:
        sock = socket.create_connection((args.host, args.port))
    except ConnectionRefusedError:
        print("[!] No se pudo conectar al servidor. ¿Está corriendo?")
        sys.exit(1)

    # Enviar identificación como JSON
    send_message(sock, {"name": client_name})

    # Recibir bienvenida
    welcome = recv_message(sock)
    if welcome and welcome.get("status") == "ok":
        print(f"[+] {welcome['message']}")
    else:
        print("[!] Error al identificarse con el servidor.")
        sock.close()
        sys.exit(1)

    print_help()

    try:
        while True:
            try:
                raw = input(f"clisend ({client_name})> ").strip()
            except EOFError:
                break

            if not raw:
                continue

            parts = raw.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            # ── LIST ──
            if cmd in ("list", "ls"):
                path = arg if arg else "/"
                send_message(sock, {"action": "LIST", "path": path})
                resp = recv_message(sock)
                if resp and resp["status"] == "ok":
                    print(f"\n  Contenido de '{path}':")
                    print_entries(resp.get("entries", []))
                    print()
                else:
                    print(f"  [!] {resp.get('message', 'Error desconocido')}")

            # ── DOWNLOAD ──
            elif cmd in ("download", "dl", "copy", "cp", "get"):
                if not arg:
                    print("  [!] Uso: cp <archivo>")
                    continue
                send_message(sock, {"action": "DOWNLOAD", "path": arg})
                resp = recv_message(sock)
                if resp and resp["status"] == "ok":
                    file_size = resp["size"]
                    filename = os.path.basename(resp["path"])
                    dest = os.path.join(download_dir, filename)
                    print(f"  Descargando '{filename}' ({format_size(file_size)})...")
                    recv_file_data(sock, file_size, dest,
                                   progress_callback=print_progress)
                    print(f"\n  [+] Guardado en: {dest}")
                else:
                    print(f"  [!] {resp.get('message', 'Error desconocido')}")

            # ── UPLOAD ──
            elif cmd in ("upload", "up", "put"):
                if not arg:
                    print("  [!] Uso: put <archivo_local>")
                    continue
                if not os.path.isfile(arg):
                    print(f"  [!] Archivo no encontrado: {arg}")
                    continue
                file_size = os.path.getsize(arg)
                remote_name = os.path.basename(arg)
                send_message(sock, {"action": "UPLOAD", "path": remote_name, "size": file_size})
                # Esperar confirmación READY
                ready = recv_message(sock)
                if ready and ready.get("status") == "ready":
                    print(f"  Subiendo '{remote_name}' ({format_size(file_size)})...")
                    send_file_data(sock, arg)
                    # Esperar confirmación final
                    resp = recv_message(sock)
                    if resp and resp["status"] == "ok":
                        print(f"  [+] {resp['message']}")
                    else:
                        print(f"  [!] {resp.get('message', 'Error')}")
                else:
                    print("  [!] Servidor no está listo para recibir")

            # ── DELETE ──
            elif cmd in ("delete", "rm"):
                if not arg:
                    print("  [!] Uso: rm <archivo>")
                    continue
                send_message(sock, {"action": "DELETE", "path": arg})
                resp = recv_message(sock)
                if resp and resp["status"] == "ok":
                    print(f"  [+] {resp['message']}")
                else:
                    print(f"  [!] {resp.get('message', 'Error')}")

            # ── CUT ──
            elif cmd == "cut":
                if not arg:
                    print("  [!] Uso: cut <archivo>")
                    continue
                send_message(sock, {"action": "CUT", "path": arg})
                resp = recv_message(sock)
                if resp and resp["status"] == "ok":
                    file_size = resp["size"]
                    filename = os.path.basename(resp["path"])
                    dest = os.path.join(download_dir, filename)
                    print(f"  Cortando '{filename}' ({format_size(file_size)})...")
                    recv_file_data(sock, file_size, dest,
                                   progress_callback=print_progress)
                    print(f"\n  [+] Movido a: {dest}")
                else:
                    print(f"  [!] {resp.get('message', 'Error')}")

            # ── HELP ──
            elif cmd == "help":
                print_help()

            # ── EXIT ──
            elif cmd in ("exit", "quit"):
                print("  [*] Desconectando...")
                break

            else:
                print(f"  [!] Comando no reconocido: '{cmd}'. Escribí 'help'.")

    except KeyboardInterrupt:
        print("\n  [*] Ctrl+C - Desconectando...")
    except (ConnectionResetError, BrokenPipeError):
        print("\n  [!] Se perdió la conexión con el servidor.")
    finally:
        sock.close()
        print("  [*] Conexión cerrada.")


if __name__ == "__main__":
    main()
