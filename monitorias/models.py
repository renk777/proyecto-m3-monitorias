"""Capa de modelo: esquema relacional de SQLite y acceso a datos.

El esquema define llaves primarias, llaves foráneas, restricciones UNIQUE y
CHECK para garantizar la integridad de los datos desde la propia base.
"""
import sqlite3
from contextlib import contextmanager

from flask import current_app

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS periods(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('student','monitor','teacher','coordinator','admin')),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS subjects(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    teacher_id INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS monitor_assignments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES subjects(id),
    monitor_id INTEGER NOT NULL REFERENCES users(id),
    period_id INTEGER NOT NULL REFERENCES periods(id),
    active INTEGER DEFAULT 1 CHECK(active IN (0,1)),
    UNIQUE(subject_id,monitor_id,period_id));
CREATE TABLE IF NOT EXISTS availability(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES monitor_assignments(id),
    weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    place TEXT NOT NULL,
    capacity INTEGER DEFAULT 10 CHECK(capacity > 0),
    active INTEGER DEFAULT 1 CHECK(active IN (0,1)),
    CHECK(start_time < end_time));
CREATE TABLE IF NOT EXISTS sessions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    availability_id INTEGER NOT NULL REFERENCES availability(id),
    session_date TEXT NOT NULL,
    capacity INTEGER DEFAULT 10 CHECK(capacity > 0),
    status TEXT DEFAULT 'open' CHECK(status IN ('open','closed','cancelled')),
    UNIQUE(availability_id,session_date));
CREATE TABLE IF NOT EXISTS bookings(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    student_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT DEFAULT 'confirmed' CHECK(status IN ('confirmed','cancelled')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id,student_id));
CREATE TABLE IF NOT EXISTS attendance(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER UNIQUE NOT NULL REFERENCES bookings(id),
    attended INTEGER NOT NULL CHECK(attended IN (0,1)),
    marked_by INTEGER REFERENCES users(id),
    marked_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ratings(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER UNIQUE NOT NULL REFERENCES bookings(id),
    score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5),
    comment TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS hour_reports(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES monitor_assignments(id),
    month TEXT NOT NULL,
    hours REAL DEFAULT 0 CHECK(hours >= 0),
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    observations TEXT DEFAULT '',
    reviewed_by INTEGER REFERENCES users(id),
    UNIQUE(assignment_id,month));
CREATE TABLE IF NOT EXISTS risk_students(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NOT NULL REFERENCES periods(id),
    document TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    program TEXT DEFAULT '',
    semester TEXT DEFAULT '',
    course TEXT DEFAULT '',
    case_type TEXT NOT NULL,
    monitor_id INTEGER REFERENCES users(id),
    difficulty TEXT DEFAULT '',
    UNIQUE(period_id,document,course));
CREATE TABLE IF NOT EXISTS alerts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_student_id INTEGER NOT NULL REFERENCES risk_students(id),
    teacher_id INTEGER NOT NULL REFERENCES users(id),
    alert_type TEXT NOT NULL,
    grade TEXT DEFAULT '',
    action TEXT NOT NULL,
    observations TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS followups(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_student_id INTEGER NOT NULL REFERENCES risk_students(id),
    monitor_id INTEGER NOT NULL REFERENCES users(id),
    medium TEXT NOT NULL,
    appointment_date TEXT NOT NULL,
    work TEXT NOT NULL,
    commitments TEXT NOT NULL,
    observations TEXT NOT NULL,
    evidence_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS surveys(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_student_id INTEGER NOT NULL REFERENCES risk_students(id),
    reason TEXT NOT NULL,
    returned INTEGER DEFAULT 0 CHECK(returned IN (0,1)),
    notes TEXT DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS catalog_options(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog TEXT NOT NULL,
    value TEXT NOT NULL,
    active INTEGER DEFAULT 1 CHECK(active IN (0,1)),
    UNIQUE(catalog,value));
CREATE TABLE IF NOT EXISTS notifications(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(session_date);
CREATE INDEX IF NOT EXISTS idx_bookings_student ON bookings(student_id);
CREATE INDEX IF NOT EXISTS idx_risk_period ON risk_students(period_id,monitor_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,is_read);
"""


@contextmanager
def conn():
    """Abre una conexión con claves foráneas activas; confirma o revierte al salir."""
    connection = sqlite3.connect(current_app.config["DB_PATH"])
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
    """Crea las tablas si no existen (idempotente)."""
    with conn() as connection:
        connection.executescript(SCHEMA)


def row_dict(row):
    return dict(row) if row else None


def active_period(connection):
    return connection.execute("SELECT * FROM periods WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()


def active_catalog(connection, catalog):
    return [r["value"] for r in connection.execute(
        "SELECT value FROM catalog_options WHERE catalog=? AND active=1 ORDER BY value", (catalog,))]


def notify(connection, user_id, title, body):
    """Registra una notificación interna para un usuario."""
    if user_id:
        connection.execute("INSERT INTO notifications(user_id,title,body) VALUES(?,?,?)", (user_id, title, body))
