# Clisend

**English** | [Español](README.es.md)

Clisend is an educational client-server file-transfer system written in Python.
It combines `asyncio` for concurrent TCP connections with dedicated worker
processes for filesystem operations and SQLite event logging.

![Architecture](./docs/Architecture.jpg)

## Architecture

The TCP server accepts multiple clients and exchanges length-prefixed JSON
control messages followed by raw file bytes when required. Read requests are
delegated to a worker with a thread pool, write operations are serialized by a
dedicated worker, and a logger worker persists transfer events in SQLite.

The length prefix provides reliable message framing over TCP. It does **not**
provide encryption, authentication, authorization, or message integrity.

## Features

- Concurrent client handling with `asyncio`.
- Separate reader, writer, and logger worker processes.
- Length-prefixed JSON protocol for commands and metadata.
- Upload, download, listing, preview, delete, and cut operations.
- Filesystem containment within a configured shared directory.
- Transfer-event logging in SQLite (`logs.db`).

## Run the server

By default, the server listens on port `65432` and shares the current directory.

```bash
python3 server.py
```

Server options:

- `-p`, `--port`: change the listening port.
- `-f`, `--folder`: choose the shared directory.
- `--host`: choose the listening interface.
- `--db`: choose the SQLite log database path.

## Run a client

The positional argument is a display name used in logs; it is not an
authenticated identity.

```bash
python3 client.py "User"
```

Client options:

- `--host`: server IP address or hostname.
- `-p`, `--port`: server port.
- `-d`, `--download-dir`: local destination for downloaded files.

## Client commands

- `ls [path]`: list files and directories.
- `cp <file>`: download a file.
- `put <local_file>`: upload a file.
- `rm <file>`: permanently delete a remote file.
- `cut <file>`: download and then delete a remote file.
- `help`: show available commands.
- `exit`: disconnect.

## Security model

Clisend is intended for learning and for use on a local machine or trusted
network. It assumes that clients and the network are trusted. The server keeps
requested filesystem paths inside the configured shared directory, but it does
not authenticate clients or grant per-user permissions.

Do not expose the server directly to the public Internet or use it to transfer
sensitive files without adding a secure transport and an authentication and
authorization layer.

## Current limitations

- TCP traffic is not encrypted with TLS.
- Client display names are not authenticated identities.
- All connected clients have the same file permissions.
- Some transfers are buffered entirely in memory.
- Message and upload size limits are not yet enforced.
- The multiprocessing setup uses `fork` and therefore targets Unix-like systems.
