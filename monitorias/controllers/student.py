"""Controlador del estudiante: oferta de monitorías, reservas y calificaciones."""

from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..models import conn, notify, row_dict
from ..services.sessions import generate_upcoming_sessions
from ..utils import bogota_now_time, bogota_today, dates_enforced, payload, to_int


bp = Blueprint("student", __name__)


@bp.get("/api/subjects")
@require_auth()
def subjects():
    """Oferta de monitorías abiertas, con cupos y si el usuario ya reservó."""
    period_id = request.args.get("periodId") or None
    enforce = dates_enforced()
    today = bogota_today().isoformat()
    with conn() as connection:
        generate_upcoming_sessions(connection)
        rows = connection.execute("""SELECT s.*,u.name teacher,ma.id assignment_id,ma.monitor_id,
            us.name monitor,se.id session_id,se.session_date,se.capacity,se.status,
            a.start_time,a.end_time,a.place,
            se.capacity-COUNT(CASE WHEN b.status='confirmed' THEN 1 END) seats,
            COUNT(CASE WHEN b.status='confirmed' AND b.student_id=? THEN 1 END) mine,
            (SELECT COALESCE(AVG(r2.score),0) FROM ratings r2 JOIN bookings b2 ON b2.id=r2.booking_id
                JOIN sessions se2 ON se2.id=b2.session_id JOIN availability a2 ON a2.id=se2.availability_id
                WHERE a2.assignment_id=ma.id) rating
            FROM subjects s JOIN monitor_assignments ma ON ma.subject_id=s.id AND ma.active=1
            JOIN users us ON us.id=ma.monitor_id JOIN availability a ON a.assignment_id=ma.id AND a.active=1
            JOIN sessions se ON se.availability_id=a.id LEFT JOIN bookings b ON b.session_id=se.id
            LEFT JOIN users u ON u.id=s.teacher_id
            WHERE se.status='open' AND (?=0 OR se.session_date>=?)
              AND ma.period_id=COALESCE(?, (SELECT id FROM periods WHERE active=1 LIMIT 1))
            GROUP BY se.id ORDER BY se.session_date,a.start_time""",
            (request.user["id"], 1 if enforce else 0, today, period_id)).fetchall()
    if enforce:  # sesiones de hoy que ya terminaron no se ofrecen
        now = bogota_now_time()
        rows = [r for r in rows if not (r["session_date"] == today and r["end_time"] <= now)]
    return jsonify([row_dict(r) for r in rows])


@bp.post("/api/bookings")
@require_auth("student")
def create_booking():
    session_id = to_int(payload().get("sessionId"), 0)
    today = bogota_today().isoformat()
    with conn() as connection:
        connection.execute("BEGIN IMMEDIATE")  # evita sobrecupo con reservas simultáneas
        session = connection.execute("""SELECT se.id,se.capacity,se.session_date,av.end_time,ma.monitor_id,s.name subject
            FROM sessions se JOIN availability av ON av.id=se.availability_id
            JOIN monitor_assignments ma ON ma.id=av.assignment_id JOIN subjects s ON s.id=ma.subject_id
            WHERE se.id=? AND se.status='open' AND av.active=1 AND ma.active=1""", (session_id,)).fetchone()
        ended = session and dates_enforced() and (
            session["session_date"] < today or (session["session_date"] == today and session["end_time"] <= bogota_now_time()))
        if not session or ended:
            return jsonify(error="La sesión no está disponible."), 400
        old = connection.execute("SELECT id,status FROM bookings WHERE session_id=? AND student_id=?", (session_id, request.user["id"])).fetchone()
        if old and old["status"] == "confirmed":
            return jsonify(error="Ya tienes una reserva en esta sesión."), 409
        count = connection.execute("SELECT COUNT(*) n FROM bookings WHERE session_id=? AND status='confirmed'", (session_id,)).fetchone()["n"]
        if count >= session["capacity"]:
            return jsonify(error="No hay cupos disponibles."), 400
        if old:
            connection.execute("UPDATE bookings SET status='confirmed' WHERE id=?", (old["id"],))
            booking_id = old["id"]
        else:
            booking_id = connection.execute("INSERT INTO bookings(session_id,student_id) VALUES(?,?)", (session_id, request.user["id"])).lastrowid
        notify(connection, session["monitor_id"], "Nueva reserva",
               f"{request.user['name']} reservó {session['subject']} para el {session['session_date']}.")
        return jsonify(id=booking_id), 201


@bp.patch("/api/bookings/<int:booking_id>/cancel")
@require_auth("student")
def cancel_booking(booking_id):
    with conn() as connection:
        booking = connection.execute("""SELECT b.id,b.status,se.session_date,se.status session_status,ma.monitor_id,s.name subject
            FROM bookings b JOIN sessions se ON se.id=b.session_id JOIN availability av ON av.id=se.availability_id
            JOIN monitor_assignments ma ON ma.id=av.assignment_id JOIN subjects s ON s.id=ma.subject_id
            WHERE b.id=? AND b.student_id=?""", (booking_id, request.user["id"])).fetchone()
        if not booking:
            return jsonify(error="Reserva no encontrada."), 404
        if booking["status"] != "confirmed":
            return jsonify(error="La reserva ya no está activa."), 400
        if booking["session_status"] != "open" or (dates_enforced() and booking["session_date"] < bogota_today().isoformat()):
            return jsonify(error="Solo puedes cancelar reservas de sesiones futuras."), 400
        connection.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
        notify(connection, booking["monitor_id"], "Reserva cancelada",
               f"{request.user['name']} canceló su reserva de {booking['subject']} del {booking['session_date']}.")
    return jsonify(ok=True)


@bp.get("/api/bookings")
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


@bp.post("/api/ratings")
@require_auth("student")
def rating():
    data = payload()
    score = to_int(data.get("score"), 0)
    with conn() as connection:
        valid = connection.execute("""SELECT b.id FROM bookings b JOIN attendance a ON a.booking_id=b.id
            WHERE b.id=? AND b.student_id=? AND b.status='confirmed' AND a.attended=1""", (to_int(data.get("bookingId")), request.user["id"])).fetchone()
        if not valid or score not in range(1, 6):
            return jsonify(error="Solo puedes calificar sesiones a las que asististe."), 400
        if connection.execute("SELECT 1 FROM ratings WHERE booking_id=?", (valid["id"],)).fetchone():
            return jsonify(error="Ya calificaste esta sesión."), 409
        connection.execute("INSERT INTO ratings(booking_id,score,comment) VALUES(?,?,?)", (valid["id"], score, str(data.get("comment", ""))[:500]))
    return jsonify(ok=True), 201
