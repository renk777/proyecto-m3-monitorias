"""Controlador general: periodos, catálogos, tablero e indicadores."""

from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..models import active_period, conn, row_dict
from ..utils import bogota_today, dates_enforced


bp = Blueprint("general", __name__)


@bp.get("/api/periods")
@require_auth()
def periods():
    with conn() as connection:
        return jsonify([row_dict(r) for r in connection.execute("SELECT * FROM periods ORDER BY id DESC")])


@bp.get("/api/catalogs")
@require_auth()
def catalogs():
    """Opciones configurables; el administrador puede pedir también las inactivas con ?all=1."""
    include_all = request.args.get("all") == "1" and request.user["role"] == "admin"
    with conn() as connection:
        rows = connection.execute(f"SELECT * FROM catalog_options {'' if include_all else 'WHERE active=1'} ORDER BY catalog,value").fetchall()
    return jsonify([row_dict(x) for x in rows])


@bp.get("/api/dashboard")
@require_auth()
def dashboard():
    """Resumen por rol: actividad propia, sesiones abiertas, asistencia y notificaciones."""
    today = bogota_today().isoformat()
    uid, role = request.user["id"], request.user["role"]
    only_future = "AND se.session_date>=?" if dates_enforced() else "AND ?<>''"
    with conn() as connection:
        period = active_period(connection)
        if role == "student":
            own = connection.execute("SELECT COUNT(*) n FROM bookings WHERE student_id=? AND status='confirmed'", (uid,)).fetchone()["n"]
        elif role == "monitor":
            own = connection.execute(f"""SELECT COUNT(*) n FROM sessions se JOIN availability av ON av.id=se.availability_id
                JOIN monitor_assignments ma ON ma.id=av.assignment_id WHERE ma.monitor_id=? AND se.status='open' {only_future}""", (uid, today)).fetchone()["n"]
        elif role == "teacher":
            own = connection.execute("SELECT COUNT(*) n FROM subjects WHERE teacher_id=?", (uid,)).fetchone()["n"]
        elif role == "coordinator":
            own = connection.execute("SELECT COUNT(*) n FROM risk_students WHERE period_id=? AND monitor_id IS NULL", (period["id"],)).fetchone()["n"] if period else 0
        else:
            own = connection.execute("SELECT COUNT(*) n FROM users WHERE active=1").fetchone()["n"]
        sessions = connection.execute(f"""SELECT COUNT(*) n FROM sessions se JOIN availability av ON av.id=se.availability_id
            JOIN monitor_assignments ma ON ma.id=av.assignment_id WHERE se.status='open' AND av.active=1 AND ma.active=1 {only_future}""", (today,)).fetchone()["n"]
        attendance_rate = connection.execute("SELECT COALESCE(AVG(attended)*100,0) n FROM attendance").fetchone()["n"]
        notes = connection.execute("""SELECT id,title,body,is_read,created_at FROM notifications WHERE user_id=?
            ORDER BY is_read,id DESC LIMIT 10""", (uid,)).fetchall()
    return jsonify(period=row_dict(period), counts={"own": own, "sessions": sessions, "attendance": attendance_rate},
                   notifications=[row_dict(x) for x in notes], unread=sum(1 for x in notes if not x["is_read"]))


@bp.post("/api/notifications/read")
@require_auth()
def read_notifications():
    with conn() as connection:
        connection.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (request.user["id"],))
    return jsonify(ok=True)


@bp.get("/api/analytics")
@require_auth("teacher", "coordinator", "admin")
def analytics():
    period = request.args.get("periodId") or None
    with conn() as connection:
        query = """SELECT s.code,s.name,
            COUNT(DISTINCT CASE WHEN b.status='confirmed' THEN b.id END) participation,
            COALESCE(AVG(a.attended)*100,0) attendance,COALESCE(AVG(r.score),0) satisfaction,
            COUNT(DISTINCT CASE WHEN se.status='closed' THEN se.id END) completed,
            COALESCE((SELECT SUM(h.hours) FROM hour_reports h JOIN monitor_assignments ma2 ON ma2.id=h.assignment_id
                WHERE ma2.subject_id=s.id AND (? IS NULL OR ma2.period_id=?)),0) hours
            FROM subjects s
            LEFT JOIN monitor_assignments ma ON ma.subject_id=s.id AND (? IS NULL OR ma.period_id=?)
            LEFT JOIN availability av ON av.assignment_id=ma.id
            LEFT JOIN sessions se ON se.availability_id=av.id LEFT JOIN bookings b ON b.session_id=se.id AND b.status='confirmed'
            LEFT JOIN attendance a ON a.booking_id=b.id LEFT JOIN ratings r ON r.booking_id=b.id"""
        args = [period, period, period, period]
        if request.user["role"] == "teacher":
            query += " WHERE s.teacher_id=?"
            args.append(request.user["id"])
        query += " GROUP BY s.id ORDER BY s.code"
        rows = connection.execute(query, args).fetchall()
    return jsonify([row_dict(r) for r in rows])
