"""Controlador del monitor: disponibilidad, asistencia, cierre de sesiones y horas."""

from datetime import datetime

from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..models import conn, notify, row_dict
from ..services.sessions import generate_sessions
from ..utils import bogota_today, dates_enforced, parse_time, payload, to_int


bp = Blueprint("monitor", __name__)


@bp.get("/api/monitor/subjects")
@require_auth("monitor")
def monitor_subjects():
    with conn() as connection:
        rows = connection.execute("""SELECT s.id,s.code,s.name FROM subjects s JOIN monitor_assignments ma ON ma.subject_id=s.id
            WHERE ma.monitor_id=? AND ma.active=1 AND ma.period_id=(SELECT id FROM periods WHERE active=1 LIMIT 1) ORDER BY s.code""",
            (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.get("/api/availability")
@require_auth("monitor")
def availability():
    with conn() as connection:
        rows = connection.execute("""SELECT a.*,ma.monitor_id,s.code,s.name
            FROM availability a JOIN monitor_assignments ma ON ma.id=a.assignment_id
            JOIN subjects s ON s.id=ma.subject_id WHERE ma.monitor_id=? AND a.active=1 ORDER BY a.weekday,a.start_time""", (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.post("/api/availability")
@require_auth("monitor")
def create_availability():
    data = payload()
    required = ("subjectId", "weekday", "startTime", "endTime", "place")
    if any(not str(data.get(key, "")).strip() for key in required):
        return jsonify(error="Completa todos los campos obligatorios."), 400
    weekday = to_int(data["weekday"])
    if weekday not in range(0, 7):
        return jsonify(error="El día de la semana no es válido."), 400
    start, end = parse_time(data["startTime"]), parse_time(data["endTime"])
    if not start or not end:
        return jsonify(error="La hora no es válida."), 400
    if end <= start:
        return jsonify(error="La hora final debe ser posterior a la inicial."), 400
    start_text, end_text = start.strftime("%H:%M"), end.strftime("%H:%M")
    capacity = max(1, min(50, to_int(data.get("capacity"), 10)))
    with conn() as connection:
        assignment = connection.execute("""SELECT id FROM monitor_assignments WHERE subject_id=? AND monitor_id=?
            AND period_id=(SELECT id FROM periods WHERE active=1 LIMIT 1) AND active=1""", (to_int(data["subjectId"]), request.user["id"])).fetchone()
        if not assignment:
            return jsonify(error="La asignatura no está asignada a este monitor."), 403
        overlap = connection.execute("""SELECT 1 FROM availability a JOIN monitor_assignments ma ON ma.id=a.assignment_id
            WHERE ma.monitor_id=? AND a.active=1 AND a.weekday=? AND a.start_time<? AND a.end_time>?""",
            (request.user["id"], weekday, end_text, start_text)).fetchone()
        if overlap:
            return jsonify(error="Ya tienes un bloque que se cruza con ese horario."), 409
        result = connection.execute("""INSERT INTO availability(assignment_id,weekday,start_time,end_time,place,capacity)
            VALUES(?,?,?,?,?,?)""", (assignment["id"], weekday, start_text, end_text, str(data["place"]).strip(), capacity))
        generate_sessions(connection, result.lastrowid, weekday, capacity)
    return jsonify(id=result.lastrowid), 201


@bp.patch("/api/availability/<int:availability_id>")
@require_auth("monitor")
def update_availability(availability_id):
    """Edita horario, lugar y cupos de un bloque (el día no cambia: las sesiones ya existen)."""
    data = payload()
    start, end = parse_time(data.get("startTime")), parse_time(data.get("endTime"))
    place, capacity = str(data.get("place", "")).strip(), to_int(data.get("capacity"))
    if not start or not end or not place or capacity is None:
        return jsonify(error="Completa todos los campos obligatorios."), 400
    if end <= start:
        return jsonify(error="La hora final debe ser posterior a la inicial."), 400
    if not 1 <= capacity <= 50:
        return jsonify(error="Los cupos deben estar entre 1 y 50."), 400
    start_text, end_text = start.strftime("%H:%M"), end.strftime("%H:%M")
    with conn() as connection:
        block_row = connection.execute("""SELECT a.id,a.weekday FROM availability a JOIN monitor_assignments ma ON ma.id=a.assignment_id
            WHERE a.id=? AND ma.monitor_id=? AND a.active=1""", (availability_id, request.user["id"])).fetchone()
        if not block_row:
            return jsonify(error="Bloque no encontrado."), 404
        overlap = connection.execute("""SELECT 1 FROM availability a JOIN monitor_assignments ma ON ma.id=a.assignment_id
            WHERE ma.monitor_id=? AND a.active=1 AND a.id<>? AND a.weekday=? AND a.start_time<? AND a.end_time>?""",
            (request.user["id"], availability_id, block_row["weekday"], end_text, start_text)).fetchone()
        if overlap:
            return jsonify(error="Ya tienes un bloque que se cruza con ese horario."), 409
        connection.execute("UPDATE availability SET start_time=?,end_time=?,place=?,capacity=? WHERE id=?",
                           (start_text, end_text, place, capacity, availability_id))
        connection.execute("""UPDATE sessions SET capacity=? WHERE availability_id=? AND status='open' AND
            (SELECT COUNT(*) FROM bookings b WHERE b.session_id=sessions.id AND b.status='confirmed')<=?""",
                           (capacity, availability_id, capacity))
    return jsonify(ok=True)


@bp.delete("/api/availability/<int:availability_id>")
@require_auth("monitor")
def delete_availability(availability_id):
    today = bogota_today().isoformat()
    with conn() as connection:
        owned = connection.execute("""SELECT a.id FROM availability a JOIN monitor_assignments ma ON ma.id=a.assignment_id
            WHERE a.id=? AND ma.monitor_id=?""", (availability_id, request.user["id"])).fetchone()
        if not owned:
            return jsonify(error="Bloque no encontrado."), 404
        connection.execute("UPDATE availability SET active=0 WHERE id=?", (availability_id,))
        connection.execute("""UPDATE bookings SET status='cancelled' WHERE status='confirmed' AND session_id IN
            (SELECT id FROM sessions WHERE availability_id=? AND session_date>=? AND status='open')""", (availability_id, today))
        connection.execute("UPDATE sessions SET status='cancelled' WHERE availability_id=? AND session_date>=? AND status='open'", (availability_id, today))
    return jsonify(ok=True)


@bp.get("/api/attendance")
@require_auth("monitor")
def attendance():
    with conn() as connection:
        rows = connection.execute("""SELECT b.id,b.id booking_id,b.status,u.name student,se.id session_id,se.session_date,
            av.start_time,av.end_time,s.name subject,
            a.attended,se.status session_status FROM bookings b JOIN users u ON u.id=b.student_id
            JOIN sessions se ON se.id=b.session_id JOIN availability av ON av.id=se.availability_id
            JOIN monitor_assignments ma ON ma.id=av.assignment_id JOIN subjects s ON s.id=ma.subject_id LEFT JOIN attendance a ON a.booking_id=b.id
            WHERE ma.monitor_id=? AND b.status='confirmed' ORDER BY se.session_date""", (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.post("/api/attendance")
@require_auth("monitor")
def mark_attendance():
    data = payload()
    attended = 1 if str(data.get("attended", 0)).lower() in ("1", "true") else 0
    with conn() as connection:
        booking = connection.execute("""SELECT b.id,b.status booking_status,se.status session_status,se.session_date FROM bookings b JOIN sessions se ON se.id=b.session_id
            JOIN availability av ON av.id=se.availability_id JOIN monitor_assignments ma ON ma.id=av.assignment_id
            WHERE b.id=? AND ma.monitor_id=?""", (to_int(data.get("bookingId")), request.user["id"])).fetchone()
        if not booking or booking["booking_status"] != "confirmed" or booking["session_status"] != "open":
            return jsonify(error="La asistencia ya no se puede modificar."), 400
        if dates_enforced() and booking["session_date"] > bogota_today().isoformat():
            return jsonify(error="Aún no puedes marcar asistencia de una sesión futura."), 400
        connection.execute("""INSERT INTO attendance(booking_id,attended,marked_by) VALUES(?,?,?)
            ON CONFLICT(booking_id) DO UPDATE SET attended=excluded.attended,marked_by=excluded.marked_by,marked_at=CURRENT_TIMESTAMP""",
            (booking["id"], attended, request.user["id"]))
    return jsonify(ok=True)


@bp.post("/api/sessions/<int:session_id>/close")
@require_auth("monitor")
def close_session(session_id):
    with conn() as connection:
        session = connection.execute("""SELECT se.status,se.session_date,ma.id assignment_id,av.start_time,av.end_time,s.name subject
            FROM sessions se JOIN availability av ON av.id=se.availability_id JOIN monitor_assignments ma ON ma.id=av.assignment_id
            JOIN subjects s ON s.id=ma.subject_id WHERE se.id=? AND ma.monitor_id=?""", (session_id, request.user["id"])).fetchone()
        if not session:
            return jsonify(error="Sesión no encontrada."), 404
        if session["status"] == "closed":
            return jsonify(error="La sesión ya está cerrada."), 409
        if dates_enforced() and session["session_date"] > bogota_today().isoformat():
            return jsonify(error="No puedes cerrar una sesión futura."), 400
        confirmed = connection.execute("""SELECT b.id,b.student_id,att.attended FROM bookings b
            LEFT JOIN attendance att ON att.booking_id=b.id WHERE b.session_id=? AND b.status='confirmed'""", (session_id,)).fetchall()
        if not confirmed:
            return jsonify(error="La sesión no tiene reservas confirmadas."), 400
        if any(r["attended"] is None for r in confirmed):
            return jsonify(error="Debes marcar la asistencia de todos los confirmados."), 400
        connection.execute("UPDATE sessions SET status='closed' WHERE id=?", (session_id,))
        month = session["session_date"][:7]
        hours = max(0, (datetime.strptime(session["end_time"], "%H:%M") - datetime.strptime(session["start_time"], "%H:%M")).total_seconds() / 3600)
        report = connection.execute("SELECT id FROM hour_reports WHERE assignment_id=? AND month=?", (session["assignment_id"], month)).fetchone()
        if not report:
            connection.execute("INSERT INTO hour_reports(assignment_id,month,hours) VALUES(?,?,?)", (session["assignment_id"], month, hours))
        else:
            # una sesión nueva devuelve el reporte a revisión para que sus horas no se pierdan
            connection.execute("UPDATE hour_reports SET hours=hours+?,status='pending' WHERE id=?", (hours, report["id"]))
        for row in confirmed:
            if row["attended"]:
                notify(connection, row["student_id"], "Califica tu monitoría",
                       f"La sesión de {session['subject']} del {session['session_date']} ya fue cerrada; cuéntanos cómo te fue.")
    return jsonify(ok=True)


@bp.get("/api/monitor/hours")
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
