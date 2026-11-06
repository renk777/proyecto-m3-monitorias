import os
import sqlite3
from datetime import date, timedelta, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from werkzeug.security import generate_password_hash

os.environ.setdefault("JWT_SECRET", "local-development-secret-change-me-32")
from app import DB_PATH, init_db, generate_sessions

BOGOTA = ZoneInfo("America/Bogota")


def seed():
    init_db()
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        users = [
            ("Maria Perez", "maria.perez@ucc.edu.co", "student"),
            ("Laura Gomez", "laura.gomez@ucc.edu.co", "monitor"),
            ("Andres Ruiz", "andres.ruiz@ucc.edu.co", "teacher"),
            ("Camila Torres", "camila.torres@ucc.edu.co", "coordinator"),
            ("Admin UCC", "admin@ucc.edu.co", "admin"),
        ]
        for name, email, role in users:
            db.execute("INSERT OR IGNORE INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                       (name, email, generate_password_hash("Demo1234!"), role))
        today = datetime.now(BOGOTA).date()
        period_name = f"{today.year}-{'1' if today.month <= 6 else '2'}"
        db.execute("UPDATE periods SET active=0")
        db.execute("INSERT OR IGNORE INTO periods(name,active) VALUES(?,1)", (period_name,))
        teacher = db.execute("SELECT id FROM users WHERE email='andres.ruiz@ucc.edu.co'").fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO subjects(code,name,teacher_id) VALUES('MAT101','Calculo diferencial',?)", (teacher,))
        db.execute("INSERT OR IGNORE INTO subjects(code,name,teacher_id) VALUES('PRO202','Programacion II',?)", (teacher,))
        period = db.execute("SELECT id FROM periods WHERE name=?", (period_name,)).fetchone()["id"]
        monitor = db.execute("SELECT id FROM users WHERE email='laura.gomez@ucc.edu.co'").fetchone()["id"]
        subject = db.execute("SELECT id FROM subjects WHERE code='MAT101'").fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO monitor_assignments(subject_id,monitor_id,period_id) VALUES(?,?,?)", (subject, monitor, period))
        assignment = db.execute("SELECT id FROM monitor_assignments WHERE subject_id=? AND monitor_id=?", (subject, monitor)).fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO availability(assignment_id,weekday,start_time,end_time,place,capacity) VALUES(?,?,?,?,?,5)",
                   (assignment, today.weekday(), "14:00", "16:00", "Sala 204"))
        availability = db.execute("SELECT id FROM availability WHERE assignment_id=?", (assignment,)).fetchone()["id"]
        generate_sessions(db, availability, today.weekday(), "14:00", "16:00", "Sala 204", 5)
        catalogs = [
            ("alert_type", "Inasistencia"), ("alert_type", "Bajo rendimiento academico"),
            ("action", "Remitir a monitoria"), ("action", "Tutoria directa con el profesor"), ("action", "Otra"),
            ("survey_reason", "Economico"), ("survey_reason", "Laboral"), ("survey_reason", "Salud"),
            ("survey_reason", "Academico"), ("survey_reason", "Otro"),
        ]
        for catalog, value in catalogs:
            db.execute("INSERT OR IGNORE INTO catalog_options(catalog,value) VALUES(?,?)", (catalog, value))
        risk = [
            ("1001", "Ana Torres", "ana.torres@ucc.edu.co", "3000000001", "Ingenieria de sistemas", "3", "MAT101", "Repitente", "Dificultad en limites"),
            ("1002", "Luis Rojas", "luis.rojas@ucc.edu.co", "3000000002", "Contaduria", "2", "PRO202", "Ausencia", "Dificultad de horarios"),
        ]
        for item in risk:
            db.execute("""INSERT OR IGNORE INTO risk_students(period_id,document,name,email,phone,program,semester,course,case_type,difficulty)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (period, *item))
        db.commit()
    print("Datos demo cargados. Contrasena para todos: Demo1234!")


if __name__ == "__main__":
    seed()
