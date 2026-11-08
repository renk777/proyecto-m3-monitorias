"""Carga datos de demostración: usuarios por rol, asignaturas, periodo activo, sesiones y estudiantes en riesgo.

Uso: python seed.py   (es idempotente: puede ejecutarse varias veces sin duplicar datos)
"""
import os
import sqlite3
from datetime import datetime

from werkzeug.security import generate_password_hash

os.environ.setdefault("JWT_SECRET", "local-development-secret-change-me-32")
from monitorias import create_app
from monitorias.config import BOGOTA, DEMO_PASSWORD
from monitorias.services.sessions import generate_sessions

USERS = [
    ("María Pérez", "maria.perez@ucc.edu.co", "student"),
    ("Carlos Mejía", "carlos.mejia@ucc.edu.co", "student"),
    ("Laura Gómez", "laura.gomez@ucc.edu.co", "monitor"),
    ("Diego Vargas", "diego.vargas@ucc.edu.co", "monitor"),
    ("Andrés Ruiz", "andres.ruiz@ucc.edu.co", "teacher"),
    ("Camila Torres", "camila.torres@ucc.edu.co", "coordinator"),
    ("Administrador UCC", "admin@ucc.edu.co", "admin"),
]
CATALOGS = [
    ("alert_type", "Inasistencia"), ("alert_type", "Bajo rendimiento académico"),
    ("action", "Remitir a monitoría"), ("action", "Tutoría directa con el profesor"), ("action", "Otra"),
    ("survey_reason", "Económico"), ("survey_reason", "Laboral"), ("survey_reason", "Salud"),
    ("survey_reason", "Académico"), ("survey_reason", "Otro"),
]
FIRST = ["Ana", "Luis", "Marta", "Pedro", "Sara", "Jorge", "Lina", "Camilo", "Paula", "Andrés", "Daniela", "Felipe", "Valentina", "Mateo", "Isabela"]
LAST = ["Torres", "Rojas", "Castro", "Ortiz", "Mora", "Pardo", "Salazar", "Duque", "Cano", "Lara"]
PROGRAMS = ["Ingeniería de Sistemas", "Contaduría Pública", "Derecho", "Administración de Empresas"]
CASES = ["Repitente", "Ausencia", "Bajo rendimiento"]
DIFFICULTIES = ["Dificultad en límites", "Dificultad de horarios", "Problemas de conectividad", "Carga laboral"]


def seed():
    app = create_app()
    with sqlite3.connect(app.config["DB_PATH"]) as db:
        db.row_factory = sqlite3.Row
        for name, email, role in USERS:
            db.execute("INSERT OR IGNORE INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                       (name, email, generate_password_hash(DEMO_PASSWORD), role))
        uid = lambda email: db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
        today = datetime.now(BOGOTA).date()
        period_name = f"{today.year}-{'1' if today.month <= 6 else '2'}"
        db.execute("UPDATE periods SET active=0")
        db.execute("INSERT OR IGNORE INTO periods(name,active) VALUES(?,1)", (period_name,))
        db.execute("UPDATE periods SET active=1 WHERE name=?", (period_name,))
        period = db.execute("SELECT id FROM periods WHERE name=?", (period_name,)).fetchone()["id"]
        teacher = uid("andres.ruiz@ucc.edu.co")
        for code, name in (("MAT101", "Cálculo diferencial"), ("PRO202", "Programación II"), ("FIS110", "Física mecánica")):
            db.execute("INSERT OR IGNORE INTO subjects(code,name,teacher_id) VALUES(?,?,?)", (code, name, teacher))
        # Cada monitor atiende una asignatura, con un bloque semanal de 14:00 a 16:00.
        for offset, (email, code, place) in enumerate((("laura.gomez@ucc.edu.co", "MAT101", "Sala 204"),
                                                       ("diego.vargas@ucc.edu.co", "PRO202", "Laboratorio 3"))):
            subject = db.execute("SELECT id FROM subjects WHERE code=?", (code,)).fetchone()["id"]
            db.execute("INSERT OR IGNORE INTO monitor_assignments(subject_id,monitor_id,period_id) VALUES(?,?,?)", (subject, uid(email), period))
            assignment = db.execute("SELECT id FROM monitor_assignments WHERE subject_id=? AND monitor_id=? AND period_id=?",
                                    (subject, uid(email), period)).fetchone()["id"]
            weekday = min((today.weekday() + offset) % 7, 5)  # lunes=0 ... sábado=5
            if not db.execute("SELECT 1 FROM availability WHERE assignment_id=?", (assignment,)).fetchone():
                db.execute("INSERT INTO availability(assignment_id,weekday,start_time,end_time,place,capacity) VALUES(?,?,?,?,?,5)",
                           (assignment, weekday, "14:00", "16:00", place))
            availability = db.execute("SELECT id FROM availability WHERE assignment_id=?", (assignment,)).fetchone()["id"]
            generate_sessions(db, availability, weekday, 5)
        for catalog, value in CATALOGS:
            db.execute("INSERT OR IGNORE INTO catalog_options(catalog,value) VALUES(?,?)", (catalog, value))
        # 30 estudiantes en riesgo (permiten probar paginación, filtros y reparto).
        for index in range(30):
            name = f"{FIRST[index % len(FIRST)]} {LAST[index % len(LAST)]}"
            db.execute("""INSERT OR IGNORE INTO risk_students(period_id,document,name,email,phone,program,semester,course,case_type,difficulty)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (period, str(1001 + index), name, f"estudiante{index + 1}@ucc.edu.co", f"30000000{index:02d}",
                        PROGRAMS[index % len(PROGRAMS)], str(1 + index % 8), ("MAT101", "PRO202", "FIS110")[index % 3],
                        CASES[index % len(CASES)], DIFFICULTIES[index % len(DIFFICULTIES)]))
        db.commit()
    print(f"Datos de demostración cargados. Contraseña de todos los usuarios: {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
