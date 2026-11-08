"""Sistema de Monitorías Académicas UCC.

Arquitectura MVC sobre Flask:
  * Modelo      -> `models.py` (esquema SQLite y acceso a datos) y `services/`.
  * Controlador -> `controllers/` y `auth.py` (blueprints con las rutas de la API).
  * Vista       -> carpeta `public/` (HTML5, CSS3 y JavaScript que consume la API).
"""
import sqlite3

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import auth
from .config import load_settings
from .controllers import admin, general, monitor, risk, student, teacher
from .models import conn, init_db
from .services.sessions import generate_upcoming_sessions

HTTP_MESSAGES = {
    400: "La solicitud no es válida.",
    401: "Tu sesión no es válida o expiró. Ingresa de nuevo.",
    403: "No tienes permiso para esta operación.",
    404: "No se encontró el recurso solicitado.",
    405: "Método no permitido para esta ruta.",
    413: "El archivo supera el límite permitido (5 MB).",
    415: "Tipo de contenido no soportado.",
}


def register_error_handlers(app):
    """Respuestas de error amigables en JSON: la interfaz nunca muestra un Traceback."""

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity_error(error):
        return jsonify(error="La operación coincide con datos ya existentes o relacionados con otros registros."), 409

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=HTTP_MESSAGES.get(error.code, "No se pudo completar la solicitud.")), error.code
        if error.code == 404:
            return send_from_directory(app.config["PUBLIC_DIR"], "index.html")
        return error

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception("Error no controlado: %s", error)
        if request.path.startswith("/api/"):
            return jsonify(error="Ocurrió un error inesperado. Revisa los datos e intenta de nuevo."), 500
        return "<h1>Ocurrió un error inesperado</h1><p>Vuelve a la <a href='/'>página principal</a>.</p>", 500


def create_app(overrides=None):
    """Fábrica de la aplicación: configura rutas, errores y base de datos."""
    settings = load_settings(overrides)
    app = Flask(__name__, static_folder=str(settings["PUBLIC_DIR"]), static_url_path="")
    app.config.update(settings)
    settings["DATA_DIR"].mkdir(parents=True, exist_ok=True)
    settings["UPLOADS_DIR"].mkdir(parents=True, exist_ok=True)

    for module in (auth, general, student, monitor, teacher, risk, admin):
        app.register_blueprint(module.bp)
    register_error_handlers(app)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def frontend(path):
        """Sirve la interfaz (SPA); cualquier ruta desconocida vuelve a index.html."""
        public = app.config["PUBLIC_DIR"]
        if path and (public / path).is_file():
            return send_from_directory(public, path)
        return send_from_directory(public, "index.html")

    with app.app_context():
        init_db()
        with conn() as connection:
            generate_upcoming_sessions(connection)
    return app
