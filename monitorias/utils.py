"""Funciones de apoyo compartidas por los controladores."""
from datetime import datetime

from flask import current_app, request

from .config import BOGOTA, DEMO_PASSWORD


def payload():
    """Cuerpo de la petición como diccionario (JSON o formulario)."""
    return request.get_json(silent=True) or request.form.to_dict()


def to_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_time(value):
    """Convierte 'HH:MM' en datetime; devuelve None si el formato no es válido."""
    try:
        return datetime.strptime(str(value).strip(), "%H:%M")
    except ValueError:
        return None


def bogota_today():
    return datetime.now(BOGOTA).date()


def bogota_now_time():
    return datetime.now(BOGOTA).strftime("%H:%M")


def demo_mode():
    return bool(current_app.config.get("DEMO_MODE"))


def dates_enforced():
    """En modo demo se desactivan las reglas que dependen de la fecha actual."""
    return not demo_mode()


def default_password():
    return DEMO_PASSWORD if demo_mode() else None
