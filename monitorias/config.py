"""Configuración central: rutas, variables de entorno y constantes del sistema."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
BOGOTA = ZoneInfo("America/Bogota")
ROLES = ("student", "monitor", "teacher", "coordinator", "admin")
DEMO_PASSWORD = "Demo1234!"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def env_flag(name):
    """Lee una variable de entorno booleana (`true` activa la bandera)."""
    return os.getenv(name, "").strip().lower() == "true"


def load_settings(overrides=None):
    """Construye la configuración leyendo `.env` y las variables de entorno.

    Se evalúa cada vez que se crea la aplicación, así las pruebas pueden usar
    bases de datos temporales sin tocar el código.
    """
    load_dotenv(ROOT / ".env")
    data_dir = Path(os.getenv("DATA_DIR", ROOT / "data"))
    settings = {
        "ROOT": ROOT,
        "DATA_DIR": data_dir,
        "UPLOADS_DIR": Path(os.getenv("UPLOADS_DIR", ROOT / "uploads")),
        "PUBLIC_DIR": ROOT / "public",
        "DB_PATH": Path(os.getenv("DB_PATH", data_dir / "monitorias.sqlite")),
        "JWT_SECRET": os.getenv("JWT_SECRET", ""),
        # Modo de pruebas: datos demo visibles y reglas de fecha desactivadas.
        "DEMO_MODE": env_flag("DEMO_MODE"),
        "COOKIE_SECURE": env_flag("COOKIE_SECURE"),
        "MAX_CONTENT_LENGTH": MAX_UPLOAD_BYTES,
        "JSON_AS_ASCII": False,
    }
    settings.update(overrides or {})
    secret = settings["JWT_SECRET"]
    if len(secret) < 32 or "pon-aqui" in secret or secret == "change-this-local-secret":
        raise RuntimeError("JWT_SECRET debe existir en el archivo .env y tener al menos 32 caracteres.")
    return settings
