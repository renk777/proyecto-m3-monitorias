import io
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PWD = "Demo1234!"


def book_today(env):
    """Reserva (por SQL) al estudiante en la sesion de hoy y devuelve (session_id, booking_id)."""
    sid = env.q("SELECT id FROM sessions WHERE session_date=?", (env.today.isoformat(),))[0][0]
    stu = env.q("SELECT id FROM users WHERE email='maria@ucc.edu.co'")[0][0]
    env.run("INSERT INTO bookings(session_id,student_id) VALUES(?,?)", (sid, stu))
    return sid, env.q("SELECT max(id) FROM bookings")[0][0]


def test_weekday_sessions_match_selected_day(env):
    m = env.login("laura@ucc.edu.co")
    r = m.post("/api/availability", json={"subjectId": 1, "weekday": 0, "startTime": "08:00", "endTime": "09:00", "place": "X", "capacity": ""})
    assert r.status_code == 201
    dates = env.q("SELECT session_date FROM sessions WHERE availability_id=?", (r.get_json()["id"],))
    assert dates and all(__import__("datetime").date.fromisoformat(d[0]).weekday() == 0 for d in dates)


def test_availability_validation(env):
    m = env.login("laura@ucc.edu.co")
    base = {"subjectId": 1, "weekday": 3, "place": "X"}
    assert m.post("/api/availability", json={**base, "startTime": "14:00", "endTime": "10:00"}).status_code == 400
    assert m.post("/api/availability", json={**base, "startTime": "99:00", "endTime": "10:00"}).status_code == 400
    assert m.post("/api/availability", json={**base, "weekday": 9, "startTime": "08:00", "endTime": "09:00"}).status_code == 400
    assert m.post("/api/availability", json={**base, "startTime": "08:00", "endTime": "10:00"}).status_code == 201
    assert m.post("/api/availability", json={**base, "startTime": "09:00", "endTime": "11:00"}).status_code == 409


def test_hours_reports_and_analytics(env):
    sid, bid = book_today(env)
    m, t = env.login("laura@ucc.edu.co"), env.login("andres@ucc.edu.co")
    assert m.post("/api/sessions/%d/close" % sid).status_code == 400  # asistencia pendiente
    assert m.post("/api/attendance", json={"bookingId": bid, "attended": 1}).status_code == 200
    assert m.post("/api/sessions/%d/close" % sid).status_code == 200
    assert m.post("/api/sessions/%d/close" % sid).status_code == 409  # no se cierra dos veces
    assert env.q("SELECT hours FROM hour_reports")[0][0] == 2.0
    assert len(t.get("/api/reports?periodId=").get_json()) == 1     # periodId vacio
    assert len(t.get("/api/reports").get_json()) == 1
    assert t.get("/api/analytics").get_json()[0]["hours"] == 2.0   # sin multiplicar por JOINs


def test_rating_only_once(env):
    sid, bid = book_today(env)
    m, s = env.login("laura@ucc.edu.co"), env.login("maria@ucc.edu.co")
    m.post("/api/attendance", json={"bookingId": bid, "attended": 1})
    m.post("/api/sessions/%d/close" % sid)
    assert s.post("/api/ratings", json={"bookingId": bid, "score": 5}).status_code == 201
    assert s.post("/api/ratings", json={"bookingId": bid, "score": 4}).status_code == 409
    assert s.get("/api/bookings").get_json()[0]["rating_score"] == 5


def test_booking_rules_and_attendance_list(env):
    s, m = env.login("maria@ucc.edu.co"), env.login("laura@ucc.edu.co")
    tomorrow = (env.today + timedelta(days=1)).isoformat()
    offer = [x for x in s.get("/api/subjects").get_json() if x["session_date"] == tomorrow][0]
    assert offer["mine"] == 0
    assert s.post("/api/bookings", json={"sessionId": offer["session_id"]}).status_code == 201
    assert s.post("/api/bookings", json={"sessionId": offer["session_id"]}).status_code == 409
    assert [x for x in s.get("/api/subjects").get_json() if x["session_id"] == offer["session_id"]][0]["mine"] == 1
    bid = s.get("/api/bookings").get_json()[0]["id"]
    assert s.patch("/api/bookings/%d/cancel" % bid).status_code == 200
    assert s.patch("/api/bookings/%d/cancel" % bid).status_code == 400
    assert m.get("/api/attendance").get_json() == []                # canceladas no aparecen
    assert m.post("/api/attendance", json={"bookingId": bid, "attended": 1}).status_code == 400


def test_cannot_mark_future_session(env):
    s, m = env.login("maria@ucc.edu.co"), env.login("laura@ucc.edu.co")
    tomorrow = (env.today + timedelta(days=1)).isoformat()
    sid = [x for x in s.get("/api/subjects").get_json() if x["session_date"] == tomorrow][0]["session_id"]
    bid = s.post("/api/bookings", json={"sessionId": sid}).get_json()["id"]
    assert m.post("/api/attendance", json={"bookingId": bid, "attended": 1}).status_code == 400
    assert m.post("/api/sessions/%d/close" % sid).status_code == 400


def test_reassign_monitor_after_removal(env):
    t = env.login("andres@ucc.edu.co")
    aid = t.get("/api/teacher/assignments").get_json()[0]["id"]
    assert t.delete("/api/teacher/assignments/%d" % aid).status_code == 200
    assert t.get("/api/teacher/assignments").get_json() == []
    monitor = t.get("/api/users/monitors").get_json()[0]["id"]
    assert t.post("/api/teacher/assignments", json={"subjectId": 1, "monitorId": monitor}).status_code == 201
    assert len(t.get("/api/teacher/assignments").get_json()) == 1
    assert t.post("/api/teacher/assignments", json={"subjectId": 1, "monitorId": 9999}).status_code == 400


@pytest.mark.parametrize("content,name", [
    (b"documento;nombre;programa\n1;Ana;Sistemas\n", "a.csv"),
    ("documento;nombre;programa\n1;Ana;Ingeniería\n".encode("latin-1"), "b.csv"),
])
def test_csv_semicolon_and_latin1(env, content, name):
    c = env.login("camila@ucc.edu.co")
    r = c.post("/api/risk/import/preview", data={"file": (io.BytesIO(content), name)}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["columns"] == ["documento", "nombre", "programa"]


def test_xlsx_import(env):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["Documento", "Nombre", "Programa"]); ws.append([1001.0, "Ana", "Sistemas"])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    c = env.login("camila@ucc.edu.co")
    prev = c.post("/api/risk/import/preview", data={"file": (buf, "d.xlsx")}, content_type="multipart/form-data").get_json()
    assert prev["sample"][0]["Documento"] == "1001"
    out = c.post("/api/risk/import/confirm", data={"tempName": prev["tempName"], "mapping": '{"document":"Documento","name":"Nombre"}'}).get_json()
    assert out["imported"] == 1


def test_assign_all_unassigned_when_none_selected(env):
    c = env.login("camila@ucc.edu.co")
    for i in range(3):
        env.run("INSERT INTO risk_students(period_id,document,name,case_type) VALUES(1,?,?,'x')", (str(i), "E%d" % i))
    assert c.post("/api/risk/assign", json={"studentIds": []}).get_json()["assigned"] == 3


def test_user_admin_rules(env):
    a = env.login("admin@ucc.edu.co")
    me = [u for u in a.get("/api/admin/users").get_json() if u["email"] == "admin@ucc.edu.co"][0]["id"]
    assert a.patch("/api/admin/users/%d" % me, json={"role": "student"}).status_code == 400
    assert a.patch("/api/admin/users/%d" % me, json={"active": False}).status_code == 400
    assert a.delete("/api/admin/users/%d" % me).status_code == 400
    assert a.patch("/api/admin/users/%d" % me, json={"name": "Nuevo Nombre", "role": "admin"}).status_code == 200
    assert a.get("/api/admin/users").status_code == 200
    other = [u for u in a.get("/api/admin/users").get_json() if u["email"] == "maria@ucc.edu.co"][0]["id"]
    assert a.patch("/api/admin/users/%d" % other, json={"role": "hacker"}).status_code == 400
    assert a.patch("/api/admin/users/%d" % other, json={"email": "admin@ucc.edu.co"}).status_code == 409
    assert a.post("/api/admin/users", json={"name": "N", "email": "n@ucc.edu.co", "role": "student"}).status_code == 400  # sin clave
    assert a.post("/api/admin/users", json={"name": "N", "email": "n@ucc.edu.co", "role": "student", "password": "Clave1234!"}).status_code == 201


def test_change_password_requires_current(env):
    s = env.login("maria@ucc.edu.co")
    assert s.patch("/api/auth/password", json={"current": "mala", "password": "Nueva1234!"}).status_code == 400
    assert s.patch("/api/auth/password", json={"current": PWD, "password": "Nueva1234!"}).status_code == 200


def test_duplicates_and_bad_input_do_not_500(env):
    a = env.login("admin@ucc.edu.co")
    assert a.post("/api/admin/subjects", json={"code": "MAT101", "name": "x"}).status_code == 409
    assert a.patch("/api/admin/subjects/1", json={"name": "solo nombre"}).status_code == 400   # antes: 401 por KeyError
    assert a.post("/api/admin/catalogs", json={"catalog": "action", "value": "Otra"}).status_code == 409
    cid = env.q("SELECT id FROM catalog_options WHERE value='Otra'")[0][0]
    a.patch("/api/admin/catalogs/%d" % cid, json={"active": False})
    assert a.post("/api/admin/catalogs", json={"catalog": "action", "value": "Otra"}).status_code == 200  # reactiva
    assert a.post("/api/admin/periods", json={"name": "2026-2"}).status_code == 409
    assert a.post("/api/admin/periods", json={"name": "2027-1"}).status_code == 201
    assert a.delete("/api/admin/periods/1").status_code == 409   # tiene historial
    assert a.post("/api/admin/periods/1/activate").status_code == 200
    assert env.q("SELECT name FROM periods WHERE active=1") == [("2026-2",)]


def test_followup_and_survey_rules(env):
    env.run("INSERT INTO risk_students(period_id,document,name,case_type) VALUES(1,'9','Sin monitor','x')")
    c = env.login("camila@ucc.edu.co")
    form = {"studentId": "1", "medium": "Correo", "appointmentDate": "2026-11-10", "work": "a", "commitments": "b", "observations": "c"}
    assert c.post("/api/risk/followups", data=form, content_type="multipart/form-data").status_code == 400
    assert c.post("/api/surveys", json={"studentId": 999, "reason": "Salud"}).status_code == 400
    assert c.post("/api/surveys", json={"studentId": 1, "reason": "Salud", "returned": "yes"}).status_code == 201
    c.post("/api/risk/assign", json={"studentIds": []})
    m = env.login("laura@ucc.edu.co")
    assert m.post("/api/risk/followups", data={**form, "appointmentDate": "no-es-fecha"}, content_type="multipart/form-data").status_code == 400
    assert m.post("/api/risk/followups", data=form, content_type="multipart/form-data").status_code == 201


def test_bulk_alerts_requires_selection(env):
    env.run("INSERT INTO risk_students(period_id,document,name,case_type,course) VALUES(1,'9','Ana','x','MAT101')")
    t = env.login("andres@ucc.edu.co")
    assert t.post("/api/alerts/bulk", json={"subjectId": 1, "rows": []}).status_code == 400
    row = {"studentId": 1, "alertType": "Inasistencia", "action": "Otra", "grade": "2.0"}
    assert t.post("/api/alerts/bulk", json={"subjectId": 1, "rows": [row]}).status_code == 201


def test_seed_twice_keeps_active_period(tmp_path):
    envv = {**os.environ, "DB_PATH": str(tmp_path / "s.sqlite"), "JWT_SECRET": "x" * 40}
    for _ in range(2):
        subprocess.run([sys.executable, "seed.py"], cwd=ROOT, env=envv, check=True, capture_output=True)
    db = sqlite3.connect(tmp_path / "s.sqlite")
    assert db.execute("SELECT COUNT(*) FROM periods WHERE active=1").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM availability").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM risk_students").fetchone()[0] == 30


# ---------------------------------------------------------------- modo demo
def test_demo_mode_disables_date_rules(demo_env):
    env = demo_env
    s, m = env.login("maria@ucc.edu.co"), env.login("laura@ucc.edu.co")
    tomorrow = (env.today + timedelta(days=1)).isoformat()
    sid = [x for x in s.get("/api/subjects").get_json() if x["session_date"] == tomorrow][0]["session_id"]
    bid = s.post("/api/bookings", json={"sessionId": sid}).get_json()["id"]
    # el monitor puede marcar asistencia y cerrar una sesión futura
    assert m.post("/api/attendance", json={"bookingId": bid, "attended": 1}).status_code == 200
    assert m.post("/api/sessions/%d/close" % sid).status_code == 200
    assert s.post("/api/ratings", json={"bookingId": bid, "score": 5}).status_code == 201
    # y una sesión de ayer (ya pasada) se puede reservar y cancelar
    env.run("INSERT INTO sessions(availability_id,session_date,capacity) VALUES(1,?,5)", ((env.today - timedelta(days=1)).isoformat(),))
    past = env.q("SELECT max(id) FROM sessions")[0][0]
    booking = s.post("/api/bookings", json={"sessionId": past})
    assert booking.status_code == 201
    assert s.patch("/api/bookings/%d/cancel" % booking.get_json()["id"]).status_code == 200


def test_strict_mode_rejects_past_session(env):
    s = env.login("maria@ucc.edu.co")
    env.run("INSERT INTO sessions(availability_id,session_date,capacity) VALUES(1,?,5)", ((env.today - timedelta(days=1)).isoformat(),))
    past = env.q("SELECT max(id) FROM sessions")[0][0]
    assert s.post("/api/bookings", json={"sessionId": past}).status_code == 400


# ---------------------------------------------------------------- notificaciones
def test_notifications_flow(env):
    s, m = env.login("maria@ucc.edu.co"), env.login("laura@ucc.edu.co")
    tomorrow = (env.today + timedelta(days=1)).isoformat()
    sid = [x for x in s.get("/api/subjects").get_json() if x["session_date"] == tomorrow][0]["session_id"]
    s.post("/api/bookings", json={"sessionId": sid})
    data = m.get("/api/dashboard").get_json()
    assert data["unread"] == 1 and data["notifications"][0]["title"] == "Nueva reserva"
    assert m.post("/api/notifications/read").status_code == 200
    assert m.get("/api/dashboard").get_json()["unread"] == 0


# ---------------------------------------------------------------- CRUD adicional
def test_availability_edit(env):
    m = env.login("laura@ucc.edu.co")
    block = m.get("/api/availability").get_json()[0]
    ok = m.patch("/api/availability/%d" % block["id"], json={"startTime": "07:00", "endTime": "09:00", "place": "Aula 9", "capacity": 8})
    assert ok.status_code == 200
    updated = [b for b in m.get("/api/availability").get_json() if b["id"] == block["id"]][0]
    assert (updated["start_time"], updated["place"], updated["capacity"]) == ("07:00", "Aula 9", 8)
    assert m.patch("/api/availability/%d" % block["id"], json={"startTime": "10:00", "endTime": "09:00", "place": "X", "capacity": 8}).status_code == 400
    assert m.patch("/api/availability/9999", json={"startTime": "07:00", "endTime": "09:00", "place": "X", "capacity": 8}).status_code == 404


def test_followup_edit_and_delete(env):
    env.run("INSERT INTO risk_students(period_id,document,name,case_type,monitor_id) VALUES(1,'9','Ana','x',2)")
    m, c = env.login("laura@ucc.edu.co"), env.login("camila@ucc.edu.co")
    form = {"studentId": "1", "medium": "Correo", "appointmentDate": "2026-11-10", "work": "a", "commitments": "b", "observations": "c"}
    fid = m.post("/api/risk/followups", data=form, content_type="multipart/form-data").get_json()["id"]
    edit = {k: v for k, v in form.items() if k != "studentId"} | {"observations": "editado"}
    assert m.patch("/api/risk/followups/%d" % fid, json=edit).status_code == 200
    assert m.get("/api/risk/followups").get_json()[0]["observations"] == "editado"
    assert m.patch("/api/risk/followups/%d" % fid, json={**edit, "work": ""}).status_code == 400
    assert c.delete("/api/risk/followups/%d" % fid).status_code == 200
    assert m.get("/api/risk/followups").get_json() == []


def test_alerts_list_and_delete(env):
    env.run("INSERT INTO risk_students(period_id,document,name,case_type,course) VALUES(1,'9','Ana','x','MAT101')")
    t = env.login("andres@ucc.edu.co")
    t.post("/api/alerts/bulk", json={"subjectId": 1, "rows": [{"studentId": 1, "alertType": "Inasistencia", "action": "Otra", "grade": "2.0"}]})
    rows = t.get("/api/alerts").get_json()
    assert len(rows) == 1 and rows[0]["student"] == "Ana"
    assert t.delete("/api/alerts/%d" % rows[0]["id"]).status_code == 200
    assert t.delete("/api/alerts/%d" % rows[0]["id"]).status_code == 404


def test_attendance_rows_have_student_and_id(env):
    sid, bid = book_today(env)
    row = env.login("laura@ucc.edu.co").get("/api/attendance").get_json()[0]
    assert row["id"] == bid and row["student"] == "Maria Perez" and row["start_time"] == "10:00"


def test_risk_students_search_and_filters(env):
    for i in range(5):
        env.run("INSERT INTO risk_students(period_id,document,name,program,case_type) VALUES(1,?,?,?,'x')",
                (str(i), "Persona %d" % i, "Derecho" if i < 2 else "Sistemas"))
    c = env.login("camila@ucc.edu.co")
    assert c.get("/api/risk/students?q=Persona 3").get_json()["total"] == 1
    body = c.get("/api/risk/students?program=Derecho").get_json()
    assert body["total"] == 2 and set(body["programs"]) == {"Derecho", "Sistemas"}
    assert c.get("/api/risk/students?assigned=yes").get_json()["total"] == 0
    assert c.get("/api/risk/students?limit=2&page=2").get_json()["page"] == 2


# ---------------------------------------------------------------- errores sin Traceback
def test_errors_are_json_without_traceback(env):
    @env.app.get("/api/boom")
    def boom():
        raise RuntimeError("fallo interno secreto")
    client = env.app.test_client()
    for path, status in (("/api/boom", 500), ("/api/auth/nope", 404)):
        r = client.get(path)
        assert r.status_code == status and "Traceback" not in r.get_data(as_text=True)
        assert "secreto" not in r.get_data(as_text=True) and r.get_json()["error"]
    assert client.delete("/api/auth/me").status_code == 405
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/pagina-que-no-existe").status_code == 200  # SPA
