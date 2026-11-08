"""Controlador del administrador: usuarios, asignaturas, periodos y catálogos (CRUD)."""

import sqlite3

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

from ..auth import require_auth
from ..config import ROLES
from ..models import conn, row_dict
from ..services.sessions import generate_upcoming_sessions
from ..utils import default_password, payload, to_int


bp = Blueprint("admin", __name__)


@bp.get("/api/admin/users")
@require_auth("admin")
def admin_users():
    with conn() as connection:
        rows = connection.execute("SELECT id,name,email,role,active FROM users ORDER BY name").fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.post("/api/admin/users")
@require_auth("admin")
def create_user():
    data = payload()
    name, email = str(data.get("name", "")).strip(), str(data.get("email", "")).strip().lower()
    if not name:
        return jsonify(error="El nombre es obligatorio."), 400
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify(error="El correo no es válido."), 400
    if data.get("role") not in ROLES:
        return jsonify(error="El rol no es válido."), 400
    password = str(data.get("password") or "") or default_password() or ""
    if len(password) < 8:
        return jsonify(error="La contraseña debe tener al menos 8 caracteres."), 400
    with conn() as connection:
        try:
            result = connection.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                (name, email, generate_password_hash(password), data["role"]))
        except sqlite3.IntegrityError:
            return jsonify(error="Ya existe un usuario con ese correo."), 409
    return jsonify(id=result.lastrowid), 201


@bp.patch("/api/admin/users/<int:user_id>")
@require_auth("admin")
def update_user(user_id):
    data = payload()
    updates, values = [], []
    own = user_id == request.user["id"]
    if "active" in data:
        active = 1 if str(data["active"]).lower() in ("1", "true") else 0
        if own and not active:
            return jsonify(error="No puedes desactivar tu propia cuenta."), 400
        updates.append("active=?")
        values.append(active)
    if data.get("role"):
        if data["role"] not in ROLES:
            return jsonify(error="El rol no es válido."), 400
        if own and data["role"] != request.user["role"]:
            return jsonify(error="No puedes cambiar tu propio rol."), 400
        updates.append("role=?")
        values.append(data["role"])
    if data.get("name"):
        updates.append("name=?")
        values.append(str(data["name"]).strip())
    if data.get("email"):
        email = str(data["email"]).strip().lower()
        if "@" not in email:
            return jsonify(error="El correo no es válido."), 400
        updates.append("email=?")
        values.append(email)
    if data.get("password"):
        if len(str(data["password"])) < 8:
            return jsonify(error="La contraseña debe tener al menos 8 caracteres."), 400
        updates.append("password_hash=?")
        values.append(generate_password_hash(str(data["password"])))
    if not updates:
        return jsonify(error="No hay cambios."), 400
    values.append(user_id)
    with conn() as connection:
        try:
            changed = connection.execute(f"UPDATE users SET {','.join(updates)} WHERE id=?", values)
        except sqlite3.IntegrityError:
            return jsonify(error="Ya existe un usuario con ese correo."), 409
    if changed.rowcount != 1:
        return jsonify(error="Usuario no encontrado."), 404
    return jsonify(ok=True)


@bp.delete("/api/admin/users/<int:user_id>")
@require_auth("admin")
def delete_user(user_id):
    if user_id == request.user["id"]:
        return jsonify(error="No puedes desactivar tu propia cuenta."), 400
    with conn() as connection:
        connection.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
    return jsonify(ok=True)


@bp.post("/api/admin/users/<int:user_id>/reset-password")
@require_auth("admin")
def reset_password(user_id):
    password = str(payload().get("password") or "") or default_password() or ""
    if len(password) < 8:
        return jsonify(error="La contraseña debe tener al menos 8 caracteres."), 400
    with conn() as connection:
        changed = connection.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(password), user_id))
    if changed.rowcount != 1:
        return jsonify(error="Usuario no encontrado."), 404
    return jsonify(ok=True)


@bp.get("/api/admin/subjects")
@require_auth("admin")
def admin_subjects():
    with conn() as connection:
        rows = connection.execute("SELECT s.*,u.name teacher FROM subjects s LEFT JOIN users u ON u.id=s.teacher_id ORDER BY s.code").fetchall()
    return jsonify([row_dict(r) for r in rows])


def clean_teacher(connection, value):
    teacher_id = to_int(value)
    if teacher_id is None:
        return None, None
    if not connection.execute("SELECT 1 FROM users WHERE id=? AND role='teacher' AND active=1", (teacher_id,)).fetchone():
        return None, "El profesor indicado no existe o no tiene rol de profesor."
    return teacher_id, None


@bp.post("/api/admin/subjects")
@require_auth("admin")
def create_subject():
    data = payload()
    code, name = str(data.get("code", "")).strip(), str(data.get("name", "")).strip()
    if not code or not name:
        return jsonify(error="El código y el nombre son obligatorios."), 400
    with conn() as connection:
        teacher_id, problem = clean_teacher(connection, data.get("teacherId"))
        if problem:
            return jsonify(error=problem), 400
        try:
            result = connection.execute("INSERT INTO subjects(code,name,teacher_id) VALUES(?,?,?)", (code, name, teacher_id))
        except sqlite3.IntegrityError:
            return jsonify(error="Ya existe una asignatura con ese código."), 409
    return jsonify(id=result.lastrowid), 201


@bp.patch("/api/admin/subjects/<int:subject_id>")
@require_auth("admin")
def update_subject(subject_id):
    data = payload()
    code, name = str(data.get("code", "")).strip(), str(data.get("name", "")).strip()
    if not code or not name:
        return jsonify(error="El código y el nombre son obligatorios."), 400
    with conn() as connection:
        teacher_id, problem = clean_teacher(connection, data.get("teacherId"))
        if problem:
            return jsonify(error=problem), 400
        try:
            changed = connection.execute("UPDATE subjects SET code=?,name=?,teacher_id=? WHERE id=?", (code, name, teacher_id, subject_id))
        except sqlite3.IntegrityError:
            return jsonify(error="Ya existe una asignatura con ese código."), 409
    if changed.rowcount != 1:
        return jsonify(error="Asignatura no encontrada."), 404
    return jsonify(ok=True)


@bp.delete("/api/admin/subjects/<int:subject_id>")
@require_auth("admin")
def delete_subject(subject_id):
    try:
        with conn() as connection:
            connection.execute("DELETE FROM subjects WHERE id=?", (subject_id,))
    except sqlite3.IntegrityError:
        return jsonify(error="No puedes eliminar una asignatura con historial. Desactiva sus asignaciones."), 409
    return jsonify(ok=True)


@bp.get("/api/admin/periods")
@require_auth("admin")
def admin_periods():
    with conn() as connection:
        return jsonify([row_dict(x) for x in connection.execute("SELECT * FROM periods ORDER BY id DESC")])


@bp.post("/api/admin/periods")
@require_auth("admin")
def create_period():
    name = str(payload().get("name", "")).strip()
    if not name:
        return jsonify(error="El nombre del periodo es obligatorio."), 400
    with conn() as connection:
        if connection.execute("SELECT 1 FROM periods WHERE name=?", (name,)).fetchone():
            return jsonify(error="Ya existe un periodo con ese nombre."), 409
        connection.execute("UPDATE periods SET active=0")
        result = connection.execute("INSERT INTO periods(name,active) VALUES(?,1)", (name,))
    return jsonify(id=result.lastrowid), 201


@bp.post("/api/admin/periods/<int:period_id>/activate")
@require_auth("admin")
def activate_period(period_id):
    with conn() as connection:
        if not connection.execute("SELECT 1 FROM periods WHERE id=?", (period_id,)).fetchone():
            return jsonify(error="Periodo no encontrado."), 404
        connection.execute("UPDATE periods SET active=0")
        connection.execute("UPDATE periods SET active=1 WHERE id=?", (period_id,))
        generate_upcoming_sessions(connection)
    return jsonify(ok=True)


@bp.delete("/api/admin/periods/<int:period_id>")
@require_auth("admin")
def delete_period(period_id):
    try:
        with conn() as connection:
            period = connection.execute("SELECT active FROM periods WHERE id=?", (period_id,)).fetchone()
            if not period or period["active"]:
                return jsonify(error="No puedes eliminar el periodo activo."), 400
            connection.execute("DELETE FROM periods WHERE id=?", (period_id,))
    except sqlite3.IntegrityError:
        return jsonify(error="No puedes eliminar un periodo con historial."), 409
    return jsonify(ok=True)


@bp.post("/api/admin/catalogs")
@require_auth("admin")
def create_catalog():
    data = payload()
    value = str(data.get("value", "")).strip()
    if data.get("catalog") not in {"alert_type", "action", "survey_reason"} or not value:
        return jsonify(error="El catálogo no es válido."), 400
    with conn() as connection:
        existing = connection.execute("SELECT id,active FROM catalog_options WHERE catalog=? AND value=?", (data["catalog"], value)).fetchone()
        if existing:
            if existing["active"]:
                return jsonify(error="Esa opción ya existe."), 409
            connection.execute("UPDATE catalog_options SET active=1 WHERE id=?", (existing["id"],))
            return jsonify(id=existing["id"]), 200
        result = connection.execute("INSERT INTO catalog_options(catalog,value) VALUES(?,?)", (data["catalog"], value))
    return jsonify(id=result.lastrowid), 201


@bp.patch("/api/admin/catalogs/<int:catalog_id>")
@require_auth("admin")
def update_catalog(catalog_id):
    with conn() as connection:
        connection.execute("UPDATE catalog_options SET active=? WHERE id=?", (1 if payload().get("active") else 0, catalog_id))
    return jsonify(ok=True)
