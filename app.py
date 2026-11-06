import csv
import io
import json
import os
import secrets
import sqlite3
import zipfile
import uuid
from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

import jwt
from flask import Flask, jsonify, request, send_from_directory, make_response, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
UPLOADS_DIR = ROOT / "uploads"
PUBLIC_DIR = ROOT / "public"
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "monitorias.sqlite"))
BOGOTA = ZoneInfo("America/Bogota")
SECRET = os.getenv("JWT_SECRET", "")
if len(SECRET) < 32 or SECRET == "change-this-local-secret" or "pon-aqui" in SECRET:
    raise RuntimeError("JWT_SECRET debe existir y tener al menos 32 caracteres.")

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS periods(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL,active INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS subjects(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE NOT NULL,name TEXT NOT NULL,teacher_id INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS monitor_assignments(id INTEGER PRIMARY KEY AUTOINCREMENT,subject_id INTEGER REFERENCES subjects(id),monitor_id INTEGER REFERENCES users(id),period_id INTEGER REFERENCES periods(id),active INTEGER DEFAULT 1,UNIQUE(subject_id,monitor_id,period_id));
CREATE TABLE IF NOT EXISTS availability(id INTEGER PRIMARY KEY AUTOINCREMENT,assignment_id INTEGER REFERENCES monitor_assignments(id),weekday INTEGER NOT NULL,start_time TEXT NOT NULL,end_time TEXT NOT NULL,place TEXT NOT NULL,capacity INTEGER DEFAULT 10,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,availability_id INTEGER REFERENCES availability(id),session_date TEXT NOT NULL,capacity INTEGER DEFAULT 10,status TEXT DEFAULT 'open',UNIQUE(availability_id,session_date));
CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY AUTOINCREMENT,session_id INTEGER REFERENCES sessions(id),student_id INTEGER REFERENCES users(id),status TEXT DEFAULT 'confirmed',created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(session_id,student_id));
CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY AUTOINCREMENT,booking_id INTEGER UNIQUE REFERENCES bookings(id),attended INTEGER NOT NULL,marked_by INTEGER REFERENCES users(id),marked_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ratings(id INTEGER PRIMARY KEY AUTOINCREMENT,booking_id INTEGER UNIQUE REFERENCES bookings(id),score INTEGER NOT NULL,comment TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS hour_reports(id INTEGER PRIMARY KEY AUTOINCREMENT,assignment_id INTEGER REFERENCES monitor_assignments(id),month TEXT NOT NULL,hours REAL DEFAULT 0,status TEXT DEFAULT 'pending',observations TEXT DEFAULT '',reviewed_by INTEGER,UNIQUE(assignment_id,month));
CREATE TABLE IF NOT EXISTS risk_students(id INTEGER PRIMARY KEY AUTOINCREMENT,period_id INTEGER REFERENCES periods(id),document TEXT NOT NULL,name TEXT NOT NULL,email TEXT DEFAULT '',phone TEXT DEFAULT '',program TEXT DEFAULT '',semester TEXT DEFAULT '',course TEXT DEFAULT '',case_type TEXT NOT NULL,monitor_id INTEGER,difficulty TEXT DEFAULT '',UNIQUE(period_id,document,course));
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT,risk_student_id INTEGER REFERENCES risk_students(id),teacher_id INTEGER REFERENCES users(id),alert_type TEXT NOT NULL,grade TEXT DEFAULT '',action TEXT NOT NULL,observations TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS followups(id INTEGER PRIMARY KEY AUTOINCREMENT,risk_student_id INTEGER REFERENCES risk_students(id),monitor_id INTEGER REFERENCES users(id),medium TEXT NOT NULL,appointment_date TEXT NOT NULL,work TEXT NOT NULL,commitments TEXT NOT NULL,observations TEXT NOT NULL,evidence_path TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS surveys(id INTEGER PRIMARY KEY AUTOINCREMENT,risk_student_id INTEGER REFERENCES risk_students(id),reason TEXT NOT NULL,returned INTEGER DEFAULT 0,notes TEXT DEFAULT '',created_by INTEGER REFERENCES users(id),created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS catalog_options(id INTEGER PRIMARY KEY AUTOINCREMENT,catalog TEXT NOT NULL,value TEXT NOT NULL,active INTEGER DEFAULT 1,UNIQUE(catalog,value));
"""


@contextmanager
def conn():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with conn() as connection:
        connection.executescript(SCHEMA)
        try:
            connection.execute("ALTER TABLE surveys ADD COLUMN notes TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def row_dict(row):
    return dict(row) if row else None


def active_period(connection):
    return connection.execute("SELECT * FROM periods WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()


def bogota_today():
    return datetime.now(BOGOTA).date()


def payload():
    return request.get_json(silent=True) or request.form.to_dict()


def token_response(user):
    token = jwt.encode({"id": user["id"], "role": user["role"], "exp": datetime.now(timezone.utc) + timedelta(hours=8)}, SECRET, algorithm="HS256")
    response = jsonify({"user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}})
    response.set_cookie("session", token, httponly=True, samesite="Lax", secure=os.getenv("COOKIE_SECURE") == "true", max_age=28800)
    return response


def require_auth(*roles):
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            token = request.cookies.get("session")
            try:
                claims = jwt.decode(token, SECRET, algorithms=["HS256"]) if token else None
                with conn() as connection:
                    user = connection.execute("SELECT id,name,email,role,active FROM users WHERE id=?", (claims["id"],)).fetchone() if claims else None
                if not user or not user["active"] or user["role"] != claims["role"]:
                    return jsonify(error="Sesion invalida o requerida."), 401
                if roles and user["role"] not in roles:
                    return jsonify(error="No tienes permiso para esta operacion."), 403
                request.user = row_dict(user)
                return function(*args, **kwargs)
            except (jwt.InvalidTokenError, KeyError, TypeError):
                return jsonify(error="Sesion invalida o vencida."), 401
        return wrapped
    return decorator


def active_catalog(connection, catalog):
    return [r["value"] for r in connection.execute("SELECT value FROM catalog_options WHERE catalog=? AND active=1 ORDER BY value", (catalog,))]


def generate_sessions(connection, availability_id, weekday, start, end, place, capacity):
    today = bogota_today()
    offset = (weekday - today.weekday()) % 7
    first = today + timedelta(days=offset)
    for week in range(4):
        session_date = first + timedelta(days=week * 7)
        connection.execute("INSERT OR IGNORE INTO sessions(availability_id,session_date,capacity) VALUES(?,?,?)", (availability_id, session_date.isoformat(), capacity))


def generate_upcoming_sessions(connection):
    rows = connection.execute("""SELECT a.id,a.weekday,a.start_time,a.end_time,a.place,a.capacity
        FROM availability a JOIN monitor_assignments ma ON ma.id=a.assignment_id
        JOIN periods p ON p.id=ma.period_id
        WHERE a.active=1 AND ma.active=1 AND p.active=1""").fetchall()
    for row in rows:
        generate_sessions(connection, row["id"], row["weekday"], row["start_time"], row["end_time"], row["place"], row["capacity"])


@app.get("/api/config")
def config():
    return jsonify(demoMode=os.getenv("DEMO_MODE") == "true")


@app.post("/api/auth/login")
def login():
    data = payload()
    email = str(data.get("email", "")).strip().lower()
    with conn() as connection:
        user = connection.execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], str(data.get("password", ""))):
        return jsonify(error="Credenciales invalidas."), 401
    return token_response(user)


@app.post("/api/auth/logout")
def logout():
    response = jsonify(ok=True)
    response.delete_cookie("session")
    return response


@app.get("/api/auth/me")
@require_auth()
def me():
    return jsonify(user={k: request.user[k] for k in ("id", "name", "email", "role")})


@app.patch("/api/auth/password")
@require_auth()
def change_password():
    password = str(payload().get("password", ""))
    if len(password) < 8:
        return jsonify(error="La contrasena debe tener al menos 8 caracteres."), 400
    with conn() as connection:
        connection.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(password), request.user["id"]))
    return jsonify(ok=True)


@app.get("/api/periods")
@require_auth()
def periods():
    with conn() as connection:
        return jsonify([row_dict(r) for r in connection.execute("SELECT * FROM periods ORDER BY id DESC")])


@app.get("/api/subjects")
@require_auth()
def subjects():
    with conn() as connection:
        rows = connection.execute("""SELECT s.*,u.name teacher,ma.id assignment_id,ma.monitor_id,
            us.name monitor,se.id session_id,se.session_date,se.capacity,se.status,
            a.start_time,a.end_time,a.place,
            se.capacity-COUNT(CASE WHEN b.status='confirmed' THEN 1 END) seats,COALESCE(AVG(r.score),0) rating
            FROM subjects s JOIN monitor_assignments ma ON ma.subject_id=s.id AND ma.active=1
            JOIN users us ON us.id=ma.monitor_id JOIN availability a ON a.assignment_id=ma.id AND a.active=1
            JOIN sessions se ON se.availability_id=a.id LEFT JOIN bookings b ON b.session_id=se.id
            LEFT JOIN users u ON u.id=s.teacher_id LEFT JOIN ratings r ON r.booking_id=b.id
            WHERE se.session_date>=? AND (? IS NULL OR ma.period_id=?)
            GROUP BY se.id ORDER BY se.session_date""",
            (bogota_today().isoformat(), request.args.get("periodId"), request.args.get("periodId"))).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.post("/api/bookings")
@require_auth("student")
def create_booking():
    data = payload()
    session_id = int(data.get("sessionId", 0))
    with conn() as connection:
        session = connection.execute("SELECT * FROM sessions WHERE id=? AND status='open' AND session_date>=?", (session_id, bogota_today().isoformat())).fetchone()
        if not session:
            return jsonify(error="Sesion no disponible."), 400
        count = connection.execute("SELECT COUNT(*) n FROM bookings WHERE session_id=? AND status='confirmed'", (session_id,)).fetchone()["n"]
        if count >= session["capacity"]:
            return jsonify(error="No hay cupos disponibles."), 400
        old = connection.execute("SELECT id,status FROM bookings WHERE session_id=? AND student_id=?", (session_id, request.user["id"])).fetchone()
        if old:
            connection.execute("UPDATE bookings SET status='confirmed' WHERE id=?", (old["id"],))
            return jsonify(id=old["id"]), 201
        result = connection.execute("INSERT INTO bookings(session_id,student_id) VALUES(?,?)", (session_id, request.user["id"]))
        return jsonify(id=result.lastrowid), 201


@app.patch("/api/bookings/<int:booking_id>/cancel")
@require_auth("student")
def cancel_booking(booking_id):
    with conn() as connection:
        booking = connection.execute("""SELECT b.id,se.session_date FROM bookings b JOIN sessions se ON se.id=b.session_id
            WHERE b.id=? AND b.student_id=?""", (booking_id, request.user["id"])).fetchone()
        if not booking or booking["session_date"] < bogota_today().isoformat():
            return jsonify(error="Solo puedes cancelar reservas futuras."), 400
        connection.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    return jsonify(ok=True)


@app.get("/api/bookings")
@require_auth("student", "monitor")
def bookings():
    with conn() as connection:
        params = (request.user["id"],)
        where = "b.student_id=?" if request.user["role"] == "student" else "ma.monitor_id=?"
        rows = connection.execute(f"""SELECT b.*,se.session_date,se.status session_status,s.name subject,
            av.start_time,av.end_time,av.place,u.name student,att.attended,ra.score rating_score,ra.comment rating_comment
            FROM bookings b JOIN sessions se ON se.id=b.session_id JOIN availability av ON av.id=se.availability_id
            JOIN monitor_assignments ma ON ma.id=av.assignment_id JOIN subjects s ON s.id=ma.subject_id
            JOIN users u ON u.id=b.student_id LEFT JOIN attendance att ON att.booking_id=b.id
            LEFT JOIN ratings ra ON ra.booking_id=b.id WHERE {where} ORDER BY se.session_date DESC""", params).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.post("/api/ratings")
@require_auth("student")
def rating():
    data = payload()
    score = int(data.get("score", 0))
    with conn() as connection:
        valid = connection.execute("""SELECT b.id FROM bookings b JOIN attendance a ON a.booking_id=b.id
            WHERE b.id=? AND b.student_id=? AND b.status='confirmed' AND a.attended=1""", (data.get("bookingId"), request.user["id"])).fetchone()
        if not valid or score not in range(1, 6):
            return jsonify(error="La reserva no permite esta calificacion."), 400
        connection.execute("INSERT INTO ratings(booking_id,score,comment) VALUES(?,?,?)", (valid["id"], score, str(data.get("comment", ""))[:500]))
    return jsonify(ok=True), 201


@app.get("/api/availability")
@require_auth("monitor")
def availability():
    with conn() as connection:
        rows = connection.execute("""SELECT a.*,ma.monitor_id,s.code,s.name
            FROM availability a JOIN monitor_assignments ma ON ma.id=a.assignment_id
            JOIN subjects s ON s.id=ma.subject_id WHERE ma.monitor_id=? AND a.active=1 ORDER BY a.weekday,a.start_time""", (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.post("/api/availability")
@require_auth("monitor")
def create_availability():
    data = payload()
    required = ("subjectId", "weekday", "startTime", "endTime", "place")
    if any(not str(data.get(key, "")).strip() for key in required):
        return jsonify(error="Completa todos los campos obligatorios."), 400
    with conn() as connection:
        assignment = connection.execute("""SELECT id FROM monitor_assignments WHERE subject_id=? AND monitor_id=?
            AND period_id=(SELECT id FROM periods WHERE active=1 LIMIT 1) AND active=1""", (data["subjectId"], request.user["id"])).fetchone()
        if not assignment:
            return jsonify(error="La asignatura no esta asignada a este monitor."), 403
        capacity = max(1, int(data.get("capacity", 10)))
        result = connection.execute("""INSERT INTO availability(assignment_id,weekday,start_time,end_time,place,capacity)
            VALUES(?,?,?,?,?,?)""", (assignment["id"], data["weekday"], data["startTime"], data["endTime"], data["place"], capacity))
        generate_sessions(connection, result.lastrowid, int(data["weekday"]), data["startTime"], data["endTime"], data["place"], capacity)
    return jsonify(id=result.lastrowid), 201


@app.delete("/api/availability/<int:availability_id>")
@require_auth("monitor")
def delete_availability(availability_id):
    with conn() as connection:
        connection.execute("""UPDATE availability SET active=0 WHERE id=? AND assignment_id IN
            (SELECT id FROM monitor_assignments WHERE monitor_id=?)""", (availability_id, request.user["id"]))
    return jsonify(ok=True)


@app.get("/api/attendance")
@require_auth("monitor")
def attendance():
    with conn() as connection:
        rows = connection.execute("""SELECT b.id booking_id,b.status,se.id session_id,se.session_date,s.name subject,
            a.attended,se.status session_status FROM bookings b JOIN users u ON u.id=b.student_id
            JOIN sessions se ON se.id=b.session_id JOIN availability av ON av.id=se.availability_id
            JOIN monitor_assignments ma ON ma.id=av.assignment_id JOIN subjects s ON s.id=ma.subject_id LEFT JOIN attendance a ON a.booking_id=b.id
            WHERE ma.monitor_id=? ORDER BY se.session_date""", (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.post("/api/attendance")
@require_auth("monitor")
def mark_attendance():
    data = payload()
    with conn() as connection:
        booking = connection.execute("""SELECT b.id,b.status booking_status,se.status session_status,ma.monitor_id FROM bookings b JOIN sessions se ON se.id=b.session_id
            JOIN availability av ON av.id=se.availability_id JOIN monitor_assignments ma ON ma.id=av.assignment_id
            WHERE b.id=? AND ma.monitor_id=?""", (data.get("bookingId"), request.user["id"])).fetchone()
        if not booking or booking["booking_status"] != "confirmed" or booking["session_status"] == "closed":
            return jsonify(error="La asistencia ya no se puede modificar."), 400
        connection.execute("""INSERT INTO attendance(booking_id,attended,marked_by) VALUES(?,?,?)
            ON CONFLICT(booking_id) DO UPDATE SET attended=excluded.attended,marked_by=excluded.marked_by,marked_at=CURRENT_TIMESTAMP""",
            (booking["id"], int(data.get("attended", 0)), request.user["id"]))
    return jsonify(ok=True)


@app.post("/api/sessions/<int:session_id>/close")
@require_auth("monitor")
def close_session(session_id):
    with conn() as connection:
        bookings_rows = connection.execute("""SELECT b.id FROM bookings b JOIN sessions se ON se.id=b.session_id
            JOIN availability av ON av.id=se.availability_id JOIN monitor_assignments ma ON ma.id=av.assignment_id
            WHERE se.id=? AND ma.monitor_id=? AND b.status='confirmed'""", (session_id, request.user["id"])).fetchall()
        if not bookings_rows or any(connection.execute("SELECT 1 FROM attendance WHERE booking_id=?", (r["id"],)).fetchone() is None for r in bookings_rows):
            return jsonify(error="Debes marcar la asistencia de todos los confirmados."), 400
        connection.execute("UPDATE sessions SET status='closed' WHERE id=?", (session_id,))
        session = connection.execute("""SELECT ma.id assignment_id,se.session_date,av.start_time,av.end_time
            FROM sessions se JOIN availability av ON av.id=se.availability_id JOIN monitor_assignments ma ON ma.id=av.assignment_id
            WHERE se.id=?""", (session_id,)).fetchone()
        month = session["session_date"][:7]
        hours = (datetime.strptime(session["end_time"], "%H:%M") - datetime.strptime(session["start_time"], "%H:%M")).seconds / 3600
        report = connection.execute("SELECT id,status,hours FROM hour_reports WHERE assignment_id=? AND month=?", (session["assignment_id"], month)).fetchone()
        if not report:
            connection.execute("INSERT INTO hour_reports(assignment_id,month,hours) VALUES(?,?,?)", (session["assignment_id"], month, hours))
        elif report["status"] != "approved":
            connection.execute("UPDATE hour_reports SET hours=hours+? WHERE id=?", (hours, report["id"]))
    return jsonify(ok=True)


@app.get("/api/monitor/hours")
@require_auth("monitor")
def monitor_hours():
    with conn() as connection:
        reports = connection.execute("""SELECT h.*,s.code,s.name subject FROM hour_reports h
            JOIN monitor_assignments ma ON ma.id=h.assignment_id JOIN subjects s ON s.id=ma.subject_id
            WHERE ma.monitor_id=? ORDER BY h.month DESC""", (request.user["id"],)).fetchall()
        history = connection.execute("""SELECT s.code,s.name,se.session_date,
            (julianday('2000-01-01 '||av.end_time)-julianday('2000-01-01 '||av.start_time))*24 hours
            FROM sessions se JOIN availability av ON av.id=se.availability_id JOIN monitor_assignments ma ON ma.id=av.assignment_id
            JOIN subjects s ON s.id=ma.subject_id WHERE ma.monitor_id=? AND se.status='closed' ORDER BY se.session_date DESC""", (request.user["id"],)).fetchall()
    return jsonify(reports=[row_dict(r) for r in reports], history=[row_dict(r) for r in history])


@app.get("/api/reports")
@require_auth("teacher")
def reports():
    period_id = request.args.get("periodId")
    with conn() as connection:
        rows = connection.execute("""SELECT h.*,s.code,s.name subject,u.name monitor FROM hour_reports h
            JOIN monitor_assignments ma ON ma.id=h.assignment_id JOIN subjects s ON s.id=ma.subject_id JOIN users u ON u.id=ma.monitor_id
            WHERE s.teacher_id=? AND (? IS NULL OR ma.period_id=?) ORDER BY h.month DESC""",
            (request.user["id"], period_id, period_id)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.patch("/api/reports/<int:report_id>")
@require_auth("teacher")
def review_report(report_id):
    data = payload()
    if data.get("status") not in ("approved", "rejected"):
        return jsonify(error="Estado invalido."), 400
    with conn() as connection:
        changed = connection.execute("""UPDATE hour_reports SET status=?,observations=?,reviewed_by=? WHERE id=?
            AND assignment_id IN (SELECT ma.id FROM monitor_assignments ma JOIN subjects s ON s.id=ma.subject_id WHERE s.teacher_id=?)""",
            (data["status"], str(data.get("observations", "")), request.user["id"], report_id, request.user["id"]))
    return jsonify(ok=changed.rowcount == 1)


@app.get("/api/dashboard")
@require_auth()
def dashboard():
    with conn() as connection:
        period = active_period(connection)
        if request.user["role"] == "student":
            own = connection.execute("SELECT COUNT(*) n FROM bookings WHERE student_id=?", (request.user["id"],)).fetchone()["n"]
        elif request.user["role"] == "monitor":
            own = connection.execute("""SELECT COUNT(*) n FROM sessions se JOIN availability av ON av.id=se.availability_id
                JOIN monitor_assignments ma ON ma.id=av.assignment_id WHERE ma.monitor_id=?""", (request.user["id"],)).fetchone()["n"]
        elif request.user["role"] == "teacher":
            own = connection.execute("SELECT COUNT(*) n FROM subjects WHERE teacher_id=?", (request.user["id"],)).fetchone()["n"]
        elif request.user["role"] == "coordinator":
            own = connection.execute("SELECT COUNT(*) n FROM risk_students WHERE period_id=? AND monitor_id IS NULL", (period["id"],)).fetchone()["n"] if period else 0
        else:
            own = connection.execute("SELECT COUNT(*) n FROM users WHERE active=1").fetchone()["n"]
        sessions = connection.execute("SELECT COUNT(*) n FROM sessions WHERE status='open'").fetchone()["n"]
        attendance_rate = connection.execute("SELECT COALESCE(AVG(attended)*100,0) n FROM attendance").fetchone()["n"]
    return jsonify(period=row_dict(period), counts={"own": own, "sessions": sessions, "attendance": attendance_rate}, notifications=[])


@app.get("/api/admin/users")
@require_auth("admin")
def admin_users():
    with conn() as connection:
        rows = connection.execute("SELECT id,name,email,role,active FROM users ORDER BY name").fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.post("/api/admin/users")
@require_auth("admin")
def create_user():
    data = payload()
    if not data.get("name") or not data.get("email") or data.get("role") not in {"student", "monitor", "teacher", "coordinator", "admin"}:
        return jsonify(error="Usuario invalido."), 400
    with conn() as connection:
        try:
            result = connection.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                (str(data["name"]).strip(), str(data["email"]).lower().strip(), generate_password_hash(data.get("password", "Demo1234!")), data["role"]))
        except sqlite3.IntegrityError:
            return jsonify(error="El correo ya existe."), 409
    return jsonify(id=result.lastrowid), 201


@app.patch("/api/admin/users/<int:user_id>")
@require_auth("admin")
def update_user(user_id):
    data = payload()
    updates, values = [], []
    if "active" in data:
        updates.append("active=?")
        values.append(1 if str(data["active"]).lower() in ("1", "true") else 0)
    if data.get("role"):
        updates.append("role=?")
        values.append(data["role"])
    if data.get("name"):
        updates.append("name=?")
        values.append(str(data["name"]).strip())
    if data.get("email"):
        updates.append("email=?")
        values.append(str(data["email"]).strip().lower())
    if data.get("password"):
        if len(str(data["password"])) < 8:
            return jsonify(error="La contrasena debe tener al menos 8 caracteres."), 400
        updates.append("password_hash=?")
        values.append(generate_password_hash(str(data["password"])))
    if not updates:
        return jsonify(error="No hay cambios."), 400
    values.append(user_id)
    with conn() as connection:
        connection.execute(f"UPDATE users SET {','.join(updates)} WHERE id=?", values)
    return jsonify(ok=True)


@app.delete("/api/admin/users/<int:user_id>")
@require_auth("admin")
def delete_user(user_id):
    with conn() as connection:
        connection.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
    return jsonify(ok=True)


@app.post("/api/admin/users/<int:user_id>/reset-password")
@require_auth("admin")
def reset_password(user_id):
    password = str(payload().get("password", "Demo1234!"))
    if len(password) < 8:
        return jsonify(error="La contrasena debe tener al menos 8 caracteres."), 400
    with conn() as connection:
        connection.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(password), user_id))
    return jsonify(ok=True)


@app.get("/api/admin/subjects")
@require_auth("admin")
def admin_subjects():
    with conn() as connection:
        rows = connection.execute("SELECT s.*,u.name teacher FROM subjects s LEFT JOIN users u ON u.id=s.teacher_id ORDER BY s.code").fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.post("/api/admin/subjects")
@require_auth("admin")
def create_subject():
    data = payload()
    if not data.get("code") or not data.get("name"):
        return jsonify(error="Codigo y nombre son obligatorios."), 400
    with conn() as connection:
        result = connection.execute("INSERT INTO subjects(code,name,teacher_id) VALUES(?,?,?)", (data["code"], data["name"], data.get("teacherId") or None))
    return jsonify(id=result.lastrowid), 201


@app.patch("/api/admin/subjects/<int:subject_id>")
@require_auth("admin")
def update_subject(subject_id):
    data = payload()
    with conn() as connection:
        connection.execute("UPDATE subjects SET code=?,name=?,teacher_id=? WHERE id=?", (data["code"], data["name"], data.get("teacherId") or None, subject_id))
    return jsonify(ok=True)


@app.delete("/api/admin/subjects/<int:subject_id>")
@require_auth("admin")
def delete_subject(subject_id):
    try:
        with conn() as connection:
            connection.execute("DELETE FROM subjects WHERE id=?", (subject_id,))
    except sqlite3.IntegrityError:
        return jsonify(error="No puedes eliminar una asignatura con historial. Desactiva sus asignaciones."), 409
    return jsonify(ok=True)


@app.get("/api/admin/periods")
@require_auth("admin")
def admin_periods():
    return periods()


@app.post("/api/admin/periods")
@require_auth("admin")
def create_period():
    name = str(payload().get("name", "")).strip()
    if not name:
        return jsonify(error="El nombre del periodo es obligatorio."), 400
    with conn() as connection:
        connection.execute("UPDATE periods SET active=0")
        result = connection.execute("INSERT INTO periods(name,active) VALUES(?,1)", (name,))
    return jsonify(id=result.lastrowid), 201


@app.delete("/api/admin/periods/<int:period_id>")
@require_auth("admin")
def delete_period(period_id):
    with conn() as connection:
        period = connection.execute("SELECT active FROM periods WHERE id=?", (period_id,)).fetchone()
        if not period or period["active"]:
            return jsonify(error="No puedes eliminar el periodo activo."), 400
        connection.execute("DELETE FROM periods WHERE id=?", (period_id,))
    return jsonify(ok=True)


@app.get("/api/catalogs")
@require_auth()
def catalogs():
    with conn() as connection:
        rows = connection.execute("SELECT * FROM catalog_options WHERE active=1 ORDER BY catalog,value").fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.post("/api/admin/catalogs")
@require_auth("admin")
def create_catalog():
    data = payload()
    if data.get("catalog") not in {"alert_type", "action", "survey_reason"} or not data.get("value"):
        return jsonify(error="Catalogo invalido."), 400
    with conn() as connection:
        result = connection.execute("INSERT INTO catalog_options(catalog,value) VALUES(?,?)", (data["catalog"], data["value"]))
    return jsonify(id=result.lastrowid), 201


@app.patch("/api/admin/catalogs/<int:catalog_id>")
@require_auth("admin")
def update_catalog(catalog_id):
    with conn() as connection:
        connection.execute("UPDATE catalog_options SET active=? WHERE id=?", (1 if payload().get("active") else 0, catalog_id))
    return jsonify(ok=True)


@app.post("/api/teacher/assignments")
@require_auth("teacher", "admin")
def assign_monitor():
    data = payload()
    with conn() as connection:
        subject = connection.execute("SELECT * FROM subjects WHERE id=?", (data.get("subjectId"),)).fetchone()
        if request.user["role"] == "teacher" and (not subject or subject["teacher_id"] != request.user["id"]):
            return jsonify(error="Solo puedes gestionar tus asignaturas."), 403
        period = active_period(connection)
        result = connection.execute("INSERT OR IGNORE INTO monitor_assignments(subject_id,monitor_id,period_id) VALUES(?,?,?)",
            (data.get("subjectId"), data.get("monitorId"), period["id"]))
    return jsonify(id=result.lastrowid), 201


@app.get("/api/teacher/assignments")
@require_auth("teacher")
def teacher_assignments():
    with conn() as connection:
        rows = connection.execute("""SELECT ma.id,s.code,s.name,u.name monitor FROM monitor_assignments ma
            JOIN subjects s ON s.id=ma.subject_id JOIN users u ON u.id=ma.monitor_id
            WHERE s.teacher_id=? AND ma.active=1 ORDER BY s.code,u.name""", (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.delete("/api/teacher/assignments/<int:assignment_id>")
@require_auth("teacher")
def unassign_monitor(assignment_id):
    with conn() as connection:
        connection.execute("""UPDATE monitor_assignments SET active=0 WHERE id=? AND subject_id IN
            (SELECT id FROM subjects WHERE teacher_id=?)""", (assignment_id, request.user["id"]))
    return jsonify(ok=True)


@app.get("/api/teacher/subjects")
@require_auth("teacher")
def teacher_subjects():
    with conn() as connection:
        rows = connection.execute("SELECT * FROM subjects WHERE teacher_id=? ORDER BY code", (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.get("/api/monitor/subjects")
@require_auth("monitor")
def monitor_subjects():
    with conn() as connection:
        rows = connection.execute("""SELECT s.id,s.code,s.name FROM subjects s JOIN monitor_assignments ma ON ma.subject_id=s.id
            WHERE ma.monitor_id=? AND ma.active=1 AND ma.period_id=(SELECT id FROM periods WHERE active=1 LIMIT 1) ORDER BY s.code""",
            (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.get("/api/users/monitors")
@require_auth("teacher", "admin", "coordinator")
def monitors():
    with conn() as connection:
        rows = connection.execute("SELECT id,name,email FROM users WHERE role='monitor' AND active=1 ORDER BY name").fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.get("/api/risk/catalogs")
@require_auth()
def risk_catalogs():
    with conn() as connection:
        return jsonify(alertTypes=active_catalog(connection, "alert_type"), actions=active_catalog(connection, "action"), reasons=active_catalog(connection, "survey_reason"))


@app.get("/api/risk/students")
@require_auth("coordinator", "monitor")
def risk_students():
    page = max(1, int(request.args.get("page", 1)))
    limit = min(50, max(1, int(request.args.get("limit", 20))))
    with conn() as connection:
        where = "WHERE r.monitor_id=?" if request.user["role"] == "monitor" else "WHERE 1=1"
        args = [request.user["id"]] if request.user["role"] == "monitor" else []
        if request.args.get("program"):
            where += " AND r.program LIKE ?"
            args.append(f"%{request.args['program']}%")
        total = connection.execute(f"SELECT COUNT(*) n FROM risk_students r {where}", args).fetchone()["n"]
        rows = connection.execute(f"""SELECT r.*,u.name monitor FROM risk_students r LEFT JOIN users u ON u.id=r.monitor_id
            {where} ORDER BY r.monitor_id IS NOT NULL,r.name LIMIT ? OFFSET ?""", args + [limit, (page - 1) * limit]).fetchall()
    return jsonify(rows=[row_dict(r) for r in rows], page=page, pages=(total + limit - 1) // limit, total=total)


@app.post("/api/risk/assign")
@require_auth("coordinator")
def assign_risk():
    ids = [int(value) for value in payload().get("studentIds", [])]
    with conn() as connection:
        monitors = connection.execute("SELECT id FROM users WHERE role='monitor' AND active=1").fetchall()
        if not monitors:
            return jsonify(error="No hay monitores activos."), 400
        loads = {r["id"]: connection.execute("SELECT COUNT(*) n FROM risk_students WHERE monitor_id=?", (r["id"],)).fetchone()["n"] for r in monitors}
        assigned = 0
        for student_id in ids:
            monitor_id = min(loads, key=loads.get)
            changed = connection.execute("UPDATE risk_students SET monitor_id=? WHERE id=? AND monitor_id IS NULL", (monitor_id, student_id))
            if changed.rowcount:
                loads[monitor_id] += 1
                assigned += 1
    return jsonify(assigned=assigned)


@app.get("/api/teacher/risk-students")
@require_auth("teacher")
def teacher_risk_students():
    subject_id = request.args.get("subjectId")
    with conn() as connection:
        subject = connection.execute("SELECT code,name FROM subjects WHERE id=? AND teacher_id=?", (subject_id, request.user["id"])).fetchone()
        if not subject:
            return jsonify([])
        rows = connection.execute("SELECT * FROM risk_students WHERE course=? OR course=?", (subject["code"], subject["name"])).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.post("/api/alerts/bulk")
@require_auth("teacher")
def bulk_alerts():
    data = payload()
    rows = data.get("rows", [])
    with conn() as connection:
        valid_types = set(active_catalog(connection, "alert_type"))
        valid_actions = set(active_catalog(connection, "action"))
        subject = connection.execute("SELECT code,name FROM subjects WHERE id=? AND teacher_id=?", (data.get("subjectId"), request.user["id"])).fetchone()
        if not subject:
            return jsonify(error="Asignatura invalida."), 400
        try:
            connection.execute("BEGIN")
            for item in rows:
                if item.get("alertType") not in valid_types or item.get("action") not in valid_actions:
                    raise ValueError("Catalogo invalido.")
                student = connection.execute("SELECT id FROM risk_students WHERE id=? AND (course=? OR course=?)", (item.get("studentId"), subject["code"], subject["name"])).fetchone()
                if not student:
                    raise ValueError("Estudiante invalido.")
                connection.execute("""INSERT INTO alerts(risk_student_id,teacher_id,alert_type,grade,action,observations)
                    VALUES(?,?,?,?,?,?)""", (student["id"], request.user["id"], item["alertType"], item.get("grade", ""), item["action"], item.get("observations", "")))
            connection.commit()
        except (ValueError, sqlite3.Error) as error:
            connection.rollback()
            return jsonify(error=str(error)), 400
    return jsonify(saved=len(rows)), 201


@app.get("/api/risk/followups")
@require_auth("monitor", "coordinator")
def followups():
    with conn() as connection:
        query = """SELECT f.*,r.name student,r.document,r.email,r.phone,r.difficulty,u.name monitor
            FROM followups f JOIN risk_students r ON r.id=f.risk_student_id JOIN users u ON u.id=f.monitor_id"""
        args = ()
        if request.user["role"] == "monitor":
            query += " WHERE f.monitor_id=?"
            args = (request.user["id"],)
        query += " ORDER BY f.appointment_date DESC"
        rows = connection.execute(query, args).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.post("/api/risk/followups")
@require_auth("monitor", "coordinator")
def create_followup():
    data = request.form
    required = ("studentId", "medium", "appointmentDate", "work", "commitments", "observations")
    if any(not data.get(key, "").strip() for key in required):
        return jsonify(error="Completa todos los campos del seguimiento."), 400
    with conn() as connection:
        student = connection.execute("SELECT id,monitor_id FROM risk_students WHERE id=?", (data["studentId"],)).fetchone()
        if not student or request.user["role"] == "monitor" and student["monitor_id"] != request.user["id"]:
            return jsonify(error="Estudiante no asignado."), 403
        filename = None
        uploaded = request.files.get("evidence")
        if uploaded and uploaded.filename:
            extension = Path(uploaded.filename).suffix.lower()
            if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
                return jsonify(error="Formato de evidencia no permitido."), 400
            filename = f"{secrets.token_hex(16)}{extension}"
            uploaded.save(UPLOADS_DIR / filename)
        monitor_id = request.user["id"] if request.user["role"] == "monitor" else int(data.get("monitorId", student["monitor_id"] or 0))
        result = connection.execute("""INSERT INTO followups(risk_student_id,monitor_id,medium,appointment_date,work,commitments,observations,evidence_path)
            VALUES(?,?,?,?,?,?,?,?)""", (student["id"], monitor_id, data["medium"], data["appointmentDate"], data["work"], data["commitments"], data["observations"], filename))
    return jsonify(id=result.lastrowid), 201


@app.get("/api/evidence/<int:followup_id>")
@require_auth("monitor", "coordinator", "admin")
def evidence(followup_id):
    with conn() as connection:
        row = connection.execute("SELECT f.evidence_path,f.monitor_id FROM followups f WHERE f.id=?", (followup_id,)).fetchone()
    if not row or not row["evidence_path"] or request.user["role"] == "monitor" and row["monitor_id"] != request.user["id"]:
        return jsonify(error="Evidencia no encontrada."), 404
    return send_from_directory(UPLOADS_DIR, row["evidence_path"])


@app.post("/api/surveys")
@require_auth("coordinator")
def create_survey():
    data = payload()
    with conn() as connection:
        if data.get("reason") not in set(active_catalog(connection, "survey_reason")):
            return jsonify(error="Motivo invalido."), 400
        result = connection.execute("""INSERT INTO surveys(risk_student_id,reason,returned,notes,created_by)
            VALUES(?,?,?,?,?)""", (data.get("studentId"), data["reason"], 1 if data.get("returned") in ("yes", "1", 1, True) else 0, data.get("notes", ""), request.user["id"]))
    return jsonify(id=result.lastrowid), 201


@app.get("/api/surveys/summary")
@require_auth("coordinator")
def survey_summary():
    with conn() as connection:
        rows = connection.execute("SELECT reason,COUNT(*) count FROM surveys GROUP BY reason ORDER BY count DESC").fetchall()
        total = sum(r["count"] for r in rows)
    return jsonify([dict(row_dict(r), percentage=(r["count"] * 100 / total if total else 0)) for r in rows])


def parse_import(upload):
    filename = upload.filename.lower()
    if filename.endswith(".csv"):
        text = upload.stream.read().decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        return list(rows[0].keys()) if rows else [], rows
    if filename.endswith(".xlsx"):
        from openpyxl import load_workbook
        workbook = load_workbook(upload, read_only=True, data_only=True)
        sheet = workbook.active
        values = list(sheet.values)
        headers = [str(value or "").strip() for value in values[0]] if values else []
        rows = [dict(zip(headers, [str(value or "").strip() for value in values_row])) for values_row in values[1:]]
        return headers, rows
    raise ValueError("Solo se aceptan archivos CSV o XLSX.")


def suggested_mapping(headers):
    def find(*terms):
        return next((header for header in headers if any(term in header.lower() for term in terms)), "")
    return {
        "document": find("documento", "cedula", "identificacion"), "name": find("nombre", "estudiante"),
        "email": find("correo", "email"), "phone": find("celular", "telefono"), "program": find("programa"),
        "semester": find("semestre"), "course": find("curso", "materia", "asignatura"),
        "caseType": find("tipo", "caso"), "difficulty": find("dificultad"),
    }


@app.post("/api/risk/import/preview")
@require_auth("coordinator")
def import_preview():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="Selecciona un archivo CSV o XLSX."), 400
    try:
        headers, rows = parse_import(upload)
        key = f"import-{uuid.uuid4().hex}.json"
        (DATA_DIR / key).write_text(json.dumps({"headers": headers, "rows": rows}, ensure_ascii=False), encoding="utf-8")
        return jsonify(columns=headers, sample=rows[:10], suggested=suggested_mapping(headers), tempName=key)
    except (ValueError, UnicodeDecodeError, OSError) as error:
        return jsonify(error=str(error)), 400


@app.post("/api/risk/import/confirm")
@require_auth("coordinator")
def import_confirm():
    temp_name = request.form.get("tempName", "")
    source = DATA_DIR / Path(temp_name).name
    if not source.is_file():
        return jsonify(error="La vista previa expiro. Vuelve a cargar el archivo."), 400
    try:
        content = json.loads(source.read_text(encoding="utf-8"))
        mapping = json.loads(request.form.get("mapping", "{}"))
        with conn() as period_connection:
            period = active_period(period_connection)
        imported = updated = 0
        omitted = []
        with conn() as connection:
            for index, row in enumerate(content["rows"], start=2):
                document = str(row.get(mapping.get("document", ""), "")).strip()
                name = str(row.get(mapping.get("name", ""), "")).strip()
                if not document:
                    omitted.append({"row": index, "reason": "Sin documento"})
                    continue
                if not name:
                    omitted.append({"row": index, "reason": "Sin nombre"})
                    continue
                values = (period["id"], document, name, str(row.get(mapping.get("email", ""), "")), str(row.get(mapping.get("phone", ""), "")),
                          str(row.get(mapping.get("program", ""), "")), str(row.get(mapping.get("semester", ""), "")), str(row.get(mapping.get("course", ""), "")),
                          str(row.get(mapping.get("caseType", ""), "")), str(row.get(mapping.get("difficulty", ""), "")))
                existing = connection.execute("SELECT id FROM risk_students WHERE period_id=? AND document=? AND course=?", (period["id"], document, values[7])).fetchone()
                connection.execute("""INSERT INTO risk_students(period_id,document,name,email,phone,program,semester,course,case_type,difficulty)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(period_id,document,course) DO UPDATE SET name=excluded.name,email=excluded.email,
                    phone=excluded.phone,program=excluded.program,semester=excluded.semester,case_type=excluded.case_type,difficulty=excluded.difficulty""", values)
                if existing:
                    updated += 1
                else:
                    imported += 1
        return jsonify(imported=imported, updated=updated, omitted=omitted)
    except (ValueError, KeyError, sqlite3.Error, OSError) as error:
        return jsonify(error=str(error)), 400
    finally:
        source.unlink(missing_ok=True)


@app.get("/api/export/final.zip")
@require_auth("coordinator", "admin")
def export_final():
    from openpyxl import Workbook
    period = request.args.get("periodId")
    monitor_id = request.args.get("monitorId")
    program = request.args.get("program")
    with conn() as connection:
        period_row = connection.execute("SELECT id FROM periods WHERE id=?", (period,)).fetchone() if period else active_period(connection)
        if not period_row:
            return jsonify(error="No hay periodo activo."), 400
        args = [period_row["id"]]
        filters = ""
        if monitor_id:
            filters += " AND r.monitor_id=?"
            args.append(monitor_id)
        if program:
            filters += " AND r.program=?"
            args.append(program)
        data = {
            "estudiantes": connection.execute(f"SELECT r.document,r.name,r.email,r.phone,r.program,r.semester,r.course,r.case_type,r.difficulty,u.name monitor FROM risk_students r LEFT JOIN users u ON u.id=r.monitor_id WHERE r.period_id=?{filters}", args).fetchall(),
            "seguimientos": connection.execute(f"SELECT f.id,r.document,r.name student,f.medium,f.appointment_date,f.work,f.commitments,f.observations FROM followups f JOIN risk_students r ON r.id=f.risk_student_id WHERE r.period_id=?{filters}", args).fetchall(),
            "alertas": connection.execute("SELECT r.document,r.name,a.alert_type,a.grade,a.action,a.observations FROM alerts a JOIN risk_students r ON r.id=a.risk_student_id WHERE r.period_id=?", (period_row["id"],)).fetchall(),
            "encuestas": connection.execute("SELECT reason,returned,notes,created_at FROM surveys").fetchall(),
        }
        files = connection.execute("""SELECT f.evidence_path,r.document,r.name student,u.name monitor FROM followups f
            JOIN risk_students r ON r.id=f.risk_student_id JOIN users u ON u.id=f.monitor_id
            WHERE r.period_id=? AND f.evidence_path IS NOT NULL""", (period_row["id"],)).fetchall()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for sheet_name, rows in data.items():
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = sheet_name
            if rows:
                sheet.append(list(rows[0].keys()))
                for row in rows:
                    sheet.append(list(row))
            workbook_output = io.BytesIO()
            workbook.save(workbook_output)
            archive.writestr(f"{sheet_name}.xlsx", workbook_output.getvalue())
        for row in files:
            path = UPLOADS_DIR / row["evidence_path"]
            if path.is_file():
                archive.write(path, f"evidencias/{row['monitor']}/{row['document']}-{row['student']}/{row['evidence_path']}")
    output.seek(0)
    return send_file(output, mimetype="application/zip", as_attachment=True, download_name="reporte-monitorias.zip")


@app.get("/api/analytics")
@require_auth("teacher", "coordinator", "admin")
def analytics():
    period = request.args.get("periodId")
    with conn() as connection:
        query = """SELECT s.code,s.name,COUNT(DISTINCT b.id) participation,
            COALESCE(AVG(a.attended)*100,0) attendance,COALESCE(AVG(r.score),0) satisfaction,
            COUNT(DISTINCT CASE WHEN se.status='closed' THEN se.id END) completed,
            COALESCE(SUM(h.hours),0) hours FROM subjects s
            LEFT JOIN monitor_assignments ma ON ma.subject_id=s.id LEFT JOIN availability av ON av.assignment_id=ma.id
            LEFT JOIN sessions se ON se.availability_id=av.id LEFT JOIN bookings b ON b.session_id=se.id
            LEFT JOIN attendance a ON a.booking_id=b.id LEFT JOIN ratings r ON r.booking_id=b.id
            LEFT JOIN hour_reports h ON h.assignment_id=ma.id"""
        args = []
        if request.user["role"] == "teacher":
            query += " WHERE s.teacher_id=?"
            args.append(request.user["id"])
        if period:
            query += " AND ma.period_id=?" if " WHERE " in query else " WHERE ma.period_id=?"
            args.append(period)
        query += " GROUP BY s.id ORDER BY s.code"
        rows = connection.execute(query, args).fetchall()
    return jsonify([row_dict(r) for r in rows])


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify(error="Ruta API no encontrada."), 404
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.errorhandler(413)
def too_large(error):
    return jsonify(error="El archivo supera el limite permitido."), 413


@app.errorhandler(500)
def server_error(error):
    if request.path.startswith("/api/"):
        return jsonify(error="Ocurrio un error interno. Revisa los datos e intenta de nuevo."), 500
    return "Ocurrio un error interno.", 500


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def frontend(path):
    requested = PUBLIC_DIR / path
    if path and requested.is_file():
        return send_from_directory(PUBLIC_DIR, path)
    return send_from_directory(PUBLIC_DIR, "index.html")


init_db()
with conn() as startup_connection:
    generate_upcoming_sessions(startup_connection)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "3000")), debug=False)
