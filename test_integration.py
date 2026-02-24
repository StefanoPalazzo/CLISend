"""Test de integración automatizado para Clisend."""
import socket
import sys
sys.path.insert(0, ".")
from protocol import send_message, recv_message


def main():
    print("=== Test de Integración Clisend ===\n")

    s = socket.create_connection(("localhost", 65432))
    print("1. ✅ Conectado al servidor")

    # Identificarse
    send_message(s, {"name": "TestBot"})
    resp = recv_message(s)
    assert resp["status"] == "ok", f"Error en handshake: {resp}"
    print(f"2. ✅ Handshake: {resp['message']}")

    # LIST
    send_message(s, {"action": "LIST", "path": "/"})
    resp = recv_message(s)
    assert resp["status"] == "ok", f"Error en LIST: {resp}"
    names = [e["name"] for e in resp.get("entries", [])]
    print(f"3. ✅ LIST: {names}")

    # UPLOAD
    content = b"Archivo creado desde el test automatico de Clisend"
    send_message(s, {"action": "UPLOAD", "path": "test_auto.txt", "size": len(content)})
    resp = recv_message(s)
    assert resp.get("status") == "ready", f"Error en UPLOAD ready: {resp}"
    s.sendall(content)
    resp = recv_message(s)
    assert resp["status"] == "ok", f"Error en UPLOAD: {resp}"
    print(f"4. ✅ UPLOAD: {resp['message']}")

    # LIST de nuevo (debería incluir test_auto.txt)
    send_message(s, {"action": "LIST", "path": "/"})
    resp = recv_message(s)
    names = [e["name"] for e in resp.get("entries", [])]
    assert "test_auto.txt" in names, f"test_auto.txt no aparece en: {names}"
    print(f"5. ✅ LIST post-upload: {names}")

    # DOWNLOAD
    send_message(s, {"action": "DOWNLOAD", "path": "test_auto.txt"})
    resp = recv_message(s)
    assert resp["status"] == "ok", f"Error en DOWNLOAD: {resp}"
    file_size = resp["size"]
    data = b""
    while len(data) < file_size:
        data += s.recv(file_size - len(data))
    assert data == content, f"Contenido descargado no coincide"
    print(f"6. ✅ DOWNLOAD: {len(data)} bytes, contenido verificado")

    # DELETE
    send_message(s, {"action": "DELETE", "path": "test_auto.txt"})
    resp = recv_message(s)
    assert resp["status"] == "ok", f"Error en DELETE: {resp}"
    print(f"7. ✅ DELETE: {resp['message']}")

    # LIST final (no debería tener test_auto.txt)
    send_message(s, {"action": "LIST", "path": "/"})
    resp = recv_message(s)
    names = [e["name"] for e in resp.get("entries", [])]
    assert "test_auto.txt" not in names, f"test_auto.txt sigue presente: {names}"
    print(f"8. ✅ LIST post-delete: {names}")

    s.close()
    print("\n=== ✅ Todos los tests pasaron! ===")


if __name__ == "__main__":
    main()
