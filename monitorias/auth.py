"""Autenticación: sesión por cookie httpOnly con JWT, control de roles y rutas de acceso."""
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from .models import conn, row_dict
from .utils import demo_mode, payload

bp = Blueprint("auth", __name__)


def token_response(user):
    """Genera el JWT (8 horas) y lo entrega en una cookie httpOnly."""
    token = jwt.encode({"id": user["id"], "role": user["role"], "exp": datetime.now(timezone.utc) + timedelta(hours=8)},
                       current_app.config["JWT_SECRET"], algorithm="HS256")
    response = jsonify({"user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}})
    response.set_cookie("session", token, httponly=True, samesite="Lax", secure=current_app.config["COOKIE_SECURE"], max_age=28800)
    return response


def require_auth(*roles):
    """Decorador: exige sesión válida y, si se indican, alguno de los roles permitidos."""
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            token = request.cookies.get("session")
            claims = None
            if token:
                try:
                    claims = jwt.decode(token, current_app.config["JWT_SECRET"], algorithms=["HS256"])
                except jwt.InvalidTokenError:
                    claims = None
            if not claims or "id" not in claims:
                return jsonify(error="Tu sesión no es válida o expiró. Ingresa de nuevo."), 401
            with conn() as connection:
                user = connection.execute("SELECT id,name,email,role,active FROM users WHERE id=?", (claims["id"],)).fetchone()
            if not user or not user["active"] or user["role"] != claims.get("role"):
                return jsonify(error="Tu sesión no es válida o expiró. Ingresa de nuevo."), 401
            if roles and user["role"] not in roles:
                return jsonify(error="No tienes permiso para esta operación."), 403
            request.user = row_dict(user)
            return function(*args, **kwargs)
        return wrapped
    return decorator


@bp.get("/api/config")
def config():
    return jsonify(demoMode=demo_mode())


@bp.post("/api/auth/login")
def login():
    data = payload()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if not email or not password:
        return jsonify(error="Ingresa tu correo y tu contraseña."), 400
    with conn() as connection:
        user = connection.execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify(error="Correo o contraseña incorrectos."), 401
    return token_response(user)


@bp.post("/api/auth/logout")
def logout():
    response = jsonify(ok=True)
    response.delete_cookie("session")
    return response


@bp.get("/api/auth/me")
@require_auth()
def me():
    return jsonify(user={k: request.user[k] for k in ("id", "name", "email", "role")})


@bp.patch("/api/auth/password")
@require_auth()
def change_password():
    data = payload()
    current = str(data.get("current", ""))
    password = str(data.get("password", ""))
    if len(password) < 8:
        return jsonify(error="La contraseña nueva debe tener al menos 8 caracteres."), 400
    with conn() as connection:
        row = connection.execute("SELECT password_hash FROM users WHERE id=?", (request.user["id"],)).fetchone()
        if not check_password_hash(row["password_hash"], current):
            return jsonify(error="La contraseña actual no es correcta."), 400
        if current == password:
            return jsonify(error="La contraseña nueva debe ser distinta de la actual."), 400
        connection.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(password), request.user["id"]))
    return jsonify(ok=True)
