import os
import sqlite3
import io
import zipfile
import importlib
from datetime import date, timedelta
from pathlib import Path

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "smoke.sqlite"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("JWT_SECRET", "test-secret-with-more-than-32-characters")
    import app as application
    application = importlib.reload(application)
    application.init_db()
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO periods(name,active) VALUES('2026-2',1)")
        password = application.generate_password_hash("Demo1234!")
        for name, email, role in (
            ("Maria Perez", "maria.perez@ucc.edu.co", "student"),
            ("Laura Gomez", "laura.gomez@ucc.edu.co", "monitor"),
            ("Andres Ruiz", "andres.ruiz@ucc.edu.co", "teacher"),
            ("Camila Torres", "camila.torres@ucc.edu.co", "coordinator"),
            ("Admin UCC", "admin@ucc.edu.co", "admin"),
        ):
            db.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)", (name, email, password, role))
        teacher = db.execute("SELECT id FROM users WHERE email='andres.ruiz@ucc.edu.co'").fetchone()[0]
        monitor = db.execute("SELECT id FROM users WHERE email='laura.gomez@ucc.edu.co'").fetchone()[0]
        db.execute("INSERT INTO subjects(code,name,teacher_id) VALUES('MAT101','Calculo diferencial',?)", (teacher,))
        subject = db.execute("SELECT id FROM subjects").fetchone()[0]
        db.execute("INSERT INTO monitor_assignments(subject_id,monitor_id,period_id) VALUES(?,?,1)", (subject, monitor))
        assignment = db.execute("SELECT id FROM monitor_assignments").fetchone()[0]
        db.execute("INSERT INTO availability(assignment_id,weekday,start_time,end_time,place) VALUES(?,?,?,?,?)", (assignment, 0, "14:00", "16:00", "Sala 1"))
        availability = db.execute("SELECT id FROM availability").fetchone()[0]
        db.execute("INSERT INTO sessions(availability_id,session_date,capacity) VALUES(?,?,5)",
                   (availability, (date.today() + timedelta(days=1)).isoformat()))
        db.commit()
    return application.app.test_client()


def login(client, email):
    response = client.post("/api/auth/login", json={"email": email, "password": "Demo1234!"})
    assert response.status_code == 200


def test_roles_and_persistence(client):
    login(client, "maria.perez@ucc.edu.co")
    subjects = client.get("/api/subjects").get_json()
    assert subjects
    session_id = subjects[0]["session_id"]
    assert client.post("/api/bookings", json={"sessionId": session_id}).status_code == 201
    assert client.get("/api/bookings").get_json()
    login(client, "admin@ucc.edu.co")
    assert client.post("/api/admin/users", json={"name": "Nueva Persona", "email": "nueva@ucc.edu.co", "role": "monitor"}).status_code == 201
    assert client.get("/api/admin/users").status_code == 200
    assert client.get("/api/no-existe").status_code == 404
    assert client.get("/api/no-existe").get_json()["error"]


def test_validation_import_pagination_and_export(client):
    login(client, "camila.torres@ucc.edu.co")
    preview = client.post("/api/risk/import/preview", data={"file": (io.BytesIO(b"documento,nombre,programa\n9001,Persona Demo,Ingenieria"), "demo.csv")}, content_type="multipart/form-data")
    assert preview.status_code == 200
    data = preview.get_json()
    assert data["columns"] == ["documento", "nombre", "programa"]
    confirm = client.post("/api/risk/import/confirm", data={"tempName": data["tempName"], "mapping": '{"document":"documento","name":"nombre","program":"programa"}'})
    assert confirm.status_code == 200
    assert confirm.get_json()["imported"] == 1
    students = client.get("/api/risk/students?page=1&limit=1").get_json()
    assert students["page"] == 1
    assert students["pages"] >= 1
    exported = client.get("/api/export/final.zip")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
        assert "estudiantes.xlsx" in archive.namelist()
    login(client, "admin@ucc.edu.co")
    invalid = client.post("/api/admin/users", json={"name": "", "email": "", "role": "bad"})
    assert invalid.status_code == 400
