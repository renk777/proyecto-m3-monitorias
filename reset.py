import os
import sqlite3
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "local-development-secret-change-me-32")
from app import DB_PATH

if Path(DB_PATH).exists():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
print("Base de datos eliminada.")
