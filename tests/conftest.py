"""Fixtures compartidas: una aplicación Flask aislada con base de datos temporal."""
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from monitorias import create_app  # noqa: E402
from monitorias.utils import bogota_today  # noqa: E402

PWD = "Demo1234!"


class Env:
    """Agrupa la app de pruebas, atajos SQL y un cliente autenticado por correo."""

    def __init__(self, app, db_path):
        self.app, self.db_path, self.today = app, db_path, bogota_today()

    def q(self, sql, args=()):
        return sqlite3.connect(self.db_path).execute(sql, args).fetchall()

    def run(self, sql, args=()):
        db = sqlite3.connect(self.db_path)
        db.execute(sql, args)
        db.commit()
        db.close()

    def login(self, email):
        client = self.app.test_client()
        assert client.post("/api/auth/login", json={"email": email, "password": PWD}).status_code == 200
        return client


def build_env(tmp_path, demo):
    db_path = tmp_path / "test.sqlite"
    app = create_app({"DB_PATH": db_path, "DATA_DIR": tmp_path, "UPLOADS_DIR": tmp_path / "uploads",
                      "JWT_SECRET": "test-secret-with-more-than-32-characters", "DEMO_MODE": demo})
    today = bogota_today()
    db = sqlite3.connect(db_path)
    db.execute("INSERT INTO periods(name,active) VALUES('2026-2',1)")
    pwd = generate_password_hash(PWD)
    for name, email, role in (
        ("Maria Perez", "maria@ucc.edu.co", "student"),
        ("Laura Gomez", "laura@ucc.edu.co", "monitor"),
        ("Andres Ruiz", "andres@ucc.edu.co", "teacher"),
        ("Camila Torres", "camila@ucc.edu.co", "coordinator"),
        ("Admin UCC", "admin@ucc.edu.co", "admin"),
    ):
        db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)", (name, email, pwd, role))
    uid = lambda e: db.execute("SELECT id FROM users WHERE email=?", (e,)).fetchone()[0]
    db.execute("INSERT INTO subjects(code,name,teacher_id) VALUES('MAT101','Calculo',?)", (uid("andres@ucc.edu.co"),))
    db.execute("INSERT INTO monitor_assignments(subject_id,monitor_id,period_id) VALUES(1,?,1)", (uid("laura@ucc.edu.co"),))
    # bloque de hoy (10:00-12:00 = 2 h) y bloque de mañana (14:00-16:00)
    for day, start, end in ((today, "10:00", "12:00"), (today + timedelta(days=1), "14:00", "16:00")):
        db.execute("INSERT INTO availability(assignment_id,weekday,start_time,end_time,place,capacity) VALUES(1,?,?,?,'Sala',5)",
                   (day.weekday(), start, end))
        aid = db.execute("SELECT max(id) FROM availability").fetchone()[0]
        db.execute("INSERT INTO sessions(availability_id,session_date,capacity) VALUES(?,?,5)", (aid, day.isoformat()))
    for catalog, value in (("alert_type", "Inasistencia"), ("action", "Otra"), ("survey_reason", "Salud")):
        db.execute("INSERT INTO catalog_options(catalog,value) VALUES(?,?)", (catalog, value))
    db.commit()
    db.close()
    return Env(app, db_path)


@pytest.fixture()
def env(tmp_path):
    """Modo estricto: las reglas de fecha están activas."""
    return build_env(tmp_path, demo=False)


@pytest.fixture()
def demo_env(tmp_path):
    """Modo demo: las reglas de fecha están desactivadas."""
    return build_env(tmp_path, demo=True)
