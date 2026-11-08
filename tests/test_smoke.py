"""Pruebas de humo: flujos principales de extremo a extremo."""
import io
import zipfile


def test_roles_and_persistence(env):
    student = env.login("maria@ucc.edu.co")
    subjects = student.get("/api/subjects").get_json()
    assert subjects
    assert student.post("/api/bookings", json={"sessionId": subjects[-1]["session_id"]}).status_code == 201
    assert student.get("/api/bookings").get_json()
    admin = env.login("admin@ucc.edu.co")
    created = admin.post("/api/admin/users", json={"name": "Nueva Persona", "email": "nueva@ucc.edu.co", "role": "monitor", "password": "Clave1234!"})
    assert created.status_code == 201
    assert admin.get("/api/admin/users").status_code == 200
    assert admin.get("/api/no-existe").status_code == 404
    assert admin.get("/api/no-existe").get_json()["error"]


def test_validation_import_pagination_and_export(env):
    coordinator = env.login("camila@ucc.edu.co")
    preview = coordinator.post("/api/risk/import/preview", data={"file": (io.BytesIO(b"documento,nombre,programa\n9001,Persona Demo,Ingenieria"), "demo.csv")},
                               content_type="multipart/form-data")
    assert preview.status_code == 200
    data = preview.get_json()
    assert data["columns"] == ["documento", "nombre", "programa"]
    confirm = coordinator.post("/api/risk/import/confirm", data={"tempName": data["tempName"], "mapping": '{"document":"documento","name":"nombre","program":"programa"}'})
    assert confirm.get_json()["imported"] == 1
    students = coordinator.get("/api/risk/students?page=1&limit=1").get_json()
    assert students["page"] == 1 and students["pages"] >= 1
    exported = coordinator.get("/api/export/final.zip")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
        assert "estudiantes.xlsx" in archive.namelist()
    admin = env.login("admin@ucc.edu.co")
    assert admin.post("/api/admin/users", json={"name": "", "email": "", "role": "bad"}).status_code == 400
