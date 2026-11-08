"""Elimina la base de datos local (deten el servidor antes). Luego ejecuta `python seed.py`."""
import os
import sqlite3
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "local-development-secret-change-me-32")
from monitorias.config import load_settings

DB_PATH = load_settings()["DB_PATH"]
if Path(DB_PATH).exists():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
print("Base de datos eliminada.")
