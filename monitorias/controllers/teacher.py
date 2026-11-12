"""Controlador del profesor: asignación de monitores, reportes de horas y alertas tempranas."""

import sqlite3

from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..models import active_catalog, active_period, conn, notify, row_dict
from ..utils import payload, to_int


bp = Blueprint("teacher", __name__)


@bp.get("/api/reports")
@require_auth("teacher")
def reports():
    period_id = request.args.get("periodId") or None
    with conn() as connection:
        rows = connection.execute("""SELECT h.*,s.code,s.name subject,u.name monitor FROM hour_reports h
            JOIN monitor_assignments ma ON ma.id=h.assignment_id JOIN subjects s ON s.id=ma.subject_id JOIN users u ON u.id=ma.monitor_id
            WHERE s.teacher_id=? AND (? IS NULL OR ma.period_id=?) ORDER BY h.month DESC""",
            (request.user["id"], period_id, period_id)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.patch("/api/reports/<int:report_id>")
@require_auth("teacher")
def review_report(report_id):
    data = payload()
    if data.get("status") not in ("approved", "rejected"):
        return jsonify(error="El estado no es válido."), 400
    observations = data.get("observations", "")
    if not isinstance(observations, str) or len(observations) > 500:
        return jsonify(error="Las observaciones deben ser un texto de hasta 500 caracteres."), 400
    observations = observations.strip()
    if data["status"] == "rejected" and not observations:
        return jsonify(error="Escribe el motivo del rechazo en Observaciones."), 400
    with conn() as connection:
        changed = connection.execute("""UPDATE hour_reports SET status=?,observations=?,reviewed_by=? WHERE id=?
            AND assignment_id IN (SELECT ma.id FROM monitor_assignments ma JOIN subjects s ON s.id=ma.subject_id WHERE s.teacher_id=?)""",
            (data["status"], observations, request.user["id"], report_id, request.user["id"]))
        if changed.rowcount != 1:
            return jsonify(error="Reporte no encontrado."), 404
        info = connection.execute("""SELECT ma.monitor_id,s.name subject,h.month FROM hour_reports h
            JOIN monitor_assignments ma ON ma.id=h.assignment_id JOIN subjects s ON s.id=ma.subject_id WHERE h.id=?""", (report_id,)).fetchone()
        verdict = "aprobado" if data["status"] == "approved" else "rechazado"
        notify(connection, info["monitor_id"], "Reporte de horas revisado", f"Tu reporte de {info['subject']} ({info['month']}) fue {verdict}.")
    return jsonify(ok=True)


@bp.get("/api/teacher/subjects")
@require_auth("teacher")
def teacher_subjects():
    with conn() as connection:
        rows = connection.execute("SELECT * FROM subjects WHERE teacher_id=? ORDER BY code", (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.get("/api/teacher/assignments")
@require_auth("teacher")
def teacher_assignments():
    with conn() as connection:
        rows = connection.execute("""SELECT ma.id,s.code,s.name,u.name monitor FROM monitor_assignments ma
            JOIN subjects s ON s.id=ma.subject_id JOIN users u ON u.id=ma.monitor_id
            WHERE s.teacher_id=? AND ma.active=1 ORDER BY s.code,u.name""", (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.post("/api/teacher/assignments")
@require_auth("teacher", "admin")
def assign_monitor():
    data = payload()
    with conn() as connection:
        subject = connection.execute("SELECT * FROM subjects WHERE id=?", (to_int(data.get("subjectId")),)).fetchone()
        if not subject:
            return jsonify(error="La asignatura no es válida."), 400
        if request.user["role"] == "teacher" and subject["teacher_id"] != request.user["id"]:
            return jsonify(error="Solo puedes gestionar tus asignaturas."), 403
        monitor = connection.execute("SELECT id FROM users WHERE id=? AND role='monitor' AND active=1", (to_int(data.get("monitorId")),)).fetchone()
        if not monitor:
            return jsonify(error="El monitor indicado no es válido."), 400
        period = active_period(connection)
        if not period:
            return jsonify(error="No hay periodo activo."), 400
        connection.execute("""INSERT INTO monitor_assignments(subject_id,monitor_id,period_id) VALUES(?,?,?)
            ON CONFLICT(subject_id,monitor_id,period_id) DO UPDATE SET active=1""", (subject["id"], monitor["id"], period["id"]))
        notify(connection, monitor["id"], "Nueva asignatura", f"Fuiste asignado como monitor de {subject['code']} - {subject['name']}.")
        row = connection.execute("SELECT id FROM monitor_assignments WHERE subject_id=? AND monitor_id=? AND period_id=?",
            (subject["id"], monitor["id"], period["id"])).fetchone()
    return jsonify(id=row["id"]), 201


@bp.delete("/api/teacher/assignments/<int:assignment_id>")
@require_auth("teacher")
def unassign_monitor(assignment_id):
    with conn() as connection:
        connection.execute("""UPDATE monitor_assignments SET active=0 WHERE id=? AND subject_id IN
            (SELECT id FROM subjects WHERE teacher_id=?)""", (assignment_id, request.user["id"]))
    return jsonify(ok=True)


@bp.get("/api/users/monitors")
@require_auth("teacher", "admin", "coordinator")
def monitors():
    with conn() as connection:
        rows = connection.execute("SELECT id,name,email FROM users WHERE role='monitor' AND active=1 ORDER BY name").fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.get("/api/teacher/risk-students")
@require_auth("teacher")
def teacher_risk_students():
    subject_id = request.args.get("subjectId")
    with conn() as connection:
        subject = connection.execute("SELECT code,name FROM subjects WHERE id=? AND teacher_id=?", (subject_id, request.user["id"])).fetchone()
        if not subject:
            return jsonify([])
        rows = connection.execute("""SELECT * FROM risk_students WHERE (course=? OR course=?)
            AND period_id=(SELECT id FROM periods WHERE active=1 LIMIT 1) ORDER BY name""", (subject["code"], subject["name"])).fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.post("/api/alerts/bulk")
@require_auth("teacher")
def bulk_alerts():
    data = payload()
    rows = data.get("rows", [])
    if not isinstance(rows, list) or not rows:
        return jsonify(error="Selecciona al menos un estudiante."), 400
    with conn() as connection:
        valid_types = set(active_catalog(connection, "alert_type"))
        valid_actions = set(active_catalog(connection, "action"))
        subject = connection.execute("SELECT code,name FROM subjects WHERE id=? AND teacher_id=?", (data.get("subjectId"), request.user["id"])).fetchone()
        if not subject:
            return jsonify(error="La asignatura no es válida."), 400
        try:
            connection.execute("BEGIN")
            for item in rows:
                if item.get("alertType") not in valid_types or item.get("action") not in valid_actions:
                    raise ValueError("El catálogo no es válido.")
                student = connection.execute("SELECT id FROM risk_students WHERE id=? AND (course=? OR course=?)", (item.get("studentId"), subject["code"], subject["name"])).fetchone()
                if not student:
                    raise ValueError("El estudiante no es válido.")
                connection.execute("""INSERT INTO alerts(risk_student_id,teacher_id,alert_type,grade,action,observations)
                    VALUES(?,?,?,?,?,?)""", (student["id"], request.user["id"], item["alertType"], item.get("grade", ""), item["action"], item.get("observations", "")))
            connection.commit()
        except (ValueError, sqlite3.Error) as error:
            connection.rollback()
            return jsonify(error=str(error)), 400
    return jsonify(saved=len(rows)), 201


@bp.get("/api/alerts")
@require_auth("teacher")
def list_alerts():
    """Alertas tempranas registradas por el profesor."""
    with conn() as connection:
        rows = connection.execute("""SELECT a.id,a.alert_type,a.grade,a.action,a.observations,a.created_at,
            r.name student,r.document,r.course FROM alerts a JOIN risk_students r ON r.id=a.risk_student_id
            WHERE a.teacher_id=? ORDER BY a.id DESC""", (request.user["id"],)).fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.delete("/api/alerts/<int:alert_id>")
@require_auth("teacher")
def delete_alert(alert_id):
    with conn() as connection:
        changed = connection.execute("DELETE FROM alerts WHERE id=? AND teacher_id=?", (alert_id, request.user["id"]))
    if changed.rowcount != 1:
        return jsonify(error="Alerta no encontrada."), 404
    return jsonify(ok=True)
