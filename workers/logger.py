"""
Recibe eventos por una multiprocessing.Queue y los registra en SQLite.
"""

import sqlite3
import os
import signal
import logging
from datetime import datetime
from multiprocessing import Queue


def _init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            client_name TEXT NOT NULL,
            client_ip TEXT NOT NULL,
            client_port INTEGER NOT NULL,
            action TEXT NOT NULL,
            path TEXT DEFAULT '',
            status TEXT NOT NULL,
            detail TEXT DEFAULT ''
        )
    """)
    conn.commit()
    return conn


def _insert_log(conn: sqlite3.Connection, event: dict):
    """Inserta un registro de log en la base de datos."""
    conn.execute("""
        INSERT INTO logs (timestamp, client_name, client_ip, client_port,
                          action, path, status, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event.get("timestamp", datetime.now().isoformat()),
        event.get("client_name", "unknown"),
        event.get("client_ip", "0.0.0.0"),
        event.get("client_port", 0),
        event.get("action", "UNKNOWN"),
        event.get("path", ""),
        event.get("status", "ok"),
        event.get("detail", ""),
    ))
    conn.commit()


def logger_worker(log_queue: Queue, db_path: str = "logs.db"):
    """
    Proceso principal del Worker de Logging.
    Lee de log_queue indefinidamente y guarda en SQLite.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    conn = _init_db(db_path)
    logging.info(f"[LOGGER] Iniciado. Base de datos: {os.path.abspath(db_path)}")

    try:
        while True:
            event = log_queue.get()  # Bloqueante: espera un evento sin gastar CPU

            if event is None:
                break

            try:
                _insert_log(conn, event)
                action = event.get("action", "?")
                name = event.get("client_name", "?")
                logging.info(f"[DB] {name} -> {action}")
            except Exception as e:
                logging.error(f"[LOGGER] Error al guardar log: {e}")

    finally:
        conn.close()
        logging.info("[LOGGER] Detenido.")
