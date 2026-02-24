# Clisend

Clisend es un sistema cliente-servidor rápido y asíncrono diseñado para la transferencia de archivos de manera local o remota. Está construido en Python utilizando **AsyncIO** para gestionar múltiples conexiones concurrentes sin bloqueo y **Multiprocessing** (mediante Workers) para delegar las operaciones pesadas de disco y base de datos.

![Arquitectura](architecture.jpg)

## Características
- **Concurrencia:** Emplea de manera nativa la librería `asyncio`.
- **Workers Dedicados:** Subprocesos separados para lectura (`reader.py`), escritura (`writer.py`) y registro (`logger.py`).
- **Protocolo Personalizado:** Transferencias seguras sobre TCP usando un tamaño predefinido (Length-Prefix) y cuerpos JSON.
- **Log de Transferencias:** Registra automáticamente los eventos a través de SQLite (`logs.db`).

## Cómo ejecutarlo

### 1. Iniciar el Servidor
Por defecto, el servidor se levanta en el puerto `65432` y comparte la carpeta actual (`.`).
```bash
python3 server.py
```

*Opciones extras del servidor:*
- `-p` o `--port`: Modifica el puerto (ej. `python3 server.py -p 8080`).
- `-f` o `--folder`: Ruta de la carpeta a compartir con los clientes.
- `--db`: Archivo SQLite para el registro de logs (por defecto `logs.db`).

### 2. Iniciar el Cliente
Para conectarte basta con invocar el script seguido de tu nombre o alias.
```bash
python3 client.py "Usuario"
```

*Opciones extras del cliente:*
- `--host`: La IP del servidor si no corre localmente (ej. `--host 192.168.1.100`).
- `-p` o `--port`: Modifica el puerto para igualar al servidor.
- `-d` o `--download-dir`: Carpeta donde irán a parar tus descargas (por defecto `downloads/`).

---

## Comandos del Cliente

Tras conectar y ser autenticado, podrás tipear los siguientes comandos en la terminal:

- `ls [ruta]`: Lista el contenido de la carpeta compartida en el servidor.
- `cp <archivo>`: Descarga un archivo a tu carpeta de descargas.
- `put <archivo_local>`: Sube uno de tus archivos locales al servidor.
- `rm <archivo>`: Elimina un archivo permanentemente del servidor.
- `cut <archivo>`: Corta el archivo (lo descarga y luego lo elimina del servidor).
- `help`: Imprime la lista completa de comandos disponibles.
- `exit`: Para desconectarte.
