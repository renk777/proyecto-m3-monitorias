"""Controlador de estudiantes en riesgo: importación DARP, reparto, seguimientos, encuestas y exportación."""

import io
import json
import secrets
import sqlite3
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory

from ..auth import require_auth
from ..models import active_catalog, active_period, conn, notify, row_dict
from ..services.imports import parse_import, suggested_mapping
from ..utils import payload, to_int


bp = Blueprint("risk", __name__)


@bp.get("/api/risk/catalogs")
@require_auth()
def risk_catalogs():
    with conn() as connection:
        return jsonify(alertTypes=active_catalog(connection, "alert_type"), actions=active_catalog(connection, "action"), reasons=active_catalog(connection, "survey_reason"))


@bp.get("/api/risk/students")
@require_auth("coordinator", "monitor")
def risk_students():
    """Estudiantes en riesgo del periodo activo con búsqueda, filtros y paginación en el servidor."""
    page = max(1, to_int(request.args.get("page"), 1))
    limit = min(200, max(1, to_int(request.args.get("limit"), 20)))
    with conn() as connection:
        where = "WHERE r.period_id=(SELECT id FROM periods WHERE active=1 LIMIT 1)"
        args = []
        if request.user["role"] == "monitor":
            where += " AND r.monitor_id=?"
            args.append(request.user["id"])
        programs = [p["program"] for p in connection.execute(
            f"SELECT DISTINCT r.program FROM risk_students r {where} AND r.program<>'' ORDER BY r.program", args)]
        query = request.args.get("q", "").strip()
        if query:
            where += " AND (r.name LIKE ? OR r.document LIKE ? OR r.email LIKE ? OR r.course LIKE ? OR r.case_type LIKE ?)"
            args += [f"%{query}%"] * 5
        if request.args.get("program"):
            where += " AND r.program=?"
            args.append(request.args["program"])
        if request.args.get("assigned") == "no":
            where += " AND r.monitor_id IS NULL"
        elif request.args.get("assigned") == "yes":
            where += " AND r.monitor_id IS NOT NULL"
        total = connection.execute(f"SELECT COUNT(*) n FROM risk_students r {where}", args).fetchone()["n"]
        rows = connection.execute(f"""SELECT r.*,u.name monitor FROM risk_students r LEFT JOIN users u ON u.id=r.monitor_id
            {where} ORDER BY r.monitor_id IS NOT NULL,r.name,r.id LIMIT ? OFFSET ?""", args + [limit, (page - 1) * limit]).fetchall()
    return jsonify(rows=[row_dict(x) for x in rows], page=page, pages=max(1, (total + limit - 1) // limit), total=total, programs=programs)


@bp.post("/api/risk/assign")
@require_auth("coordinator")
def assign_risk():
    raw = payload().get("studentIds", [])
    ids = [i for i in (to_int(v) for v in raw) if i is not None] if isinstance(raw, list) else []
    with conn() as connection:
        period = active_period(connection)
        if not period:
            return jsonify(error="No hay periodo activo."), 400
        monitors = connection.execute("SELECT id FROM users WHERE role='monitor' AND active=1").fetchall()
        if not monitors:
            return jsonify(error="No hay monitores activos."), 400
        if not ids:  # sin seleccion: reparte todos los que aun no tienen monitor
            ids = [r["id"] for r in connection.execute("SELECT id FROM risk_students WHERE period_id=? AND monitor_id IS NULL ORDER BY id", (period["id"],))]
        loads = {r["id"]: connection.execute("SELECT COUNT(*) n FROM risk_students WHERE monitor_id=? AND period_id=?", (r["id"], period["id"])).fetchone()["n"] for r in monitors}
        assigned = 0
        received = {}
        for student_id in ids:
            monitor_id = min(loads, key=loads.get)
            changed = connection.execute("UPDATE risk_students SET monitor_id=? WHERE id=? AND monitor_id IS NULL AND period_id=?", (monitor_id, student_id, period["id"]))
            if changed.rowcount:
                loads[monitor_id] += 1
                assigned += 1
                received[monitor_id] = received.get(monitor_id, 0) + 1
        for monitor_id, amount in received.items():
            notify(connection, monitor_id, "Nuevos estudiantes asignados", f"Se te asignaron {amount} estudiantes en riesgo para acompañamiento.")
    return jsonify(assigned=assigned)


@bp.get("/api/risk/followups")
@require_auth("monitor", "coordinator")
def followups():
    with conn() as connection:
        query = """SELECT f.*,r.name student,r.document,r.email,r.phone,r.difficulty,u.name monitor
            FROM followups f JOIN risk_students r ON r.id=f.risk_student_id JOIN users u ON u.id=f.monitor_id"""
        args = ()
        if request.user["role"] == "monitor":
            query += " WHERE f.monitor_id=?"
            args = (request.user["id"],)
        query += " ORDER BY f.appointment_date DESC"
        rows = connection.execute(query, args).fetchall()
    return jsonify([row_dict(r) for r in rows])


@bp.post("/api/risk/followups")
@require_auth("monitor", "coordinator")
def create_followup():
    data = request.form
    required = ("studentId", "medium", "appointmentDate", "work", "commitments", "observations")
    if any(not data.get(key, "").strip() for key in required):
        return jsonify(error="Completa todos los campos del seguimiento."), 400
    try:
        date.fromisoformat(data["appointmentDate"])
    except ValueError:
        return jsonify(error="La fecha no es válida."), 400
    with conn() as connection:
        student = connection.execute("SELECT id,monitor_id FROM risk_students WHERE id=?", (to_int(data["studentId"]),)).fetchone()
        if not student or (request.user["role"] == "monitor" and student["monitor_id"] != request.user["id"]):
            return jsonify(error="Estudiante no asignado."), 403
        if not student["monitor_id"]:
            return jsonify(error="El estudiante aún no tiene monitor asignado."), 400
        filename = None
        uploaded = request.files.get("evidence")
        if uploaded and uploaded.filename:
            extension = Path(uploaded.filename).suffix.lower()
            if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
                return jsonify(error="Formato de evidencia no permitido."), 400
            filename = f"{secrets.token_hex(16)}{extension}"
            uploaded.save(current_app.config["UPLOADS_DIR"] / filename)
        result = connection.execute("""INSERT INTO followups(risk_student_id,monitor_id,medium,appointment_date,work,commitments,observations,evidence_path)
            VALUES(?,?,?,?,?,?,?,?)""", (student["id"], student["monitor_id"], data["medium"], data["appointmentDate"], data["work"], data["commitments"], data["observations"], filename))
    return jsonify(id=result.lastrowid), 201


@bp.patch("/api/risk/followups/<int:followup_id>")
@require_auth("monitor", "coordinator")
def update_followup(followup_id):
    """Edita los textos de un seguimiento (el monitor solo los suyos)."""
    data = payload()
    required = ("medium", "appointmentDate", "work", "commitments", "observations")
    if any(not str(data.get(key, "")).strip() for key in required):
        return jsonify(error="Completa todos los campos del seguimiento."), 400
    try:
        date.fromisoformat(str(data["appointmentDate"]))
    except ValueError:
        return jsonify(error="La fecha no es válida."), 400
    owner = "" if request.user["role"] == "coordinator" else " AND monitor_id=?"
    args = [data["medium"], data["appointmentDate"], data["work"], data["commitments"], data["observations"], followup_id]
    if owner:
        args.append(request.user["id"])
    with conn() as connection:
        changed = connection.execute(
            f"UPDATE followups SET medium=?,appointment_date=?,work=?,commitments=?,observations=? WHERE id=?{owner}", args)
    if changed.rowcount != 1:
        return jsonify(error="Seguimiento no encontrado."), 404
    return jsonify(ok=True)


@bp.delete("/api/risk/followups/<int:followup_id>")
@require_auth("monitor", "coordinator")
def delete_followup(followup_id):
    with conn() as connection:
        row = connection.execute("SELECT monitor_id,evidence_path FROM followups WHERE id=?", (followup_id,)).fetchone()
        if not row or (request.user["role"] == "monitor" and row["monitor_id"] != request.user["id"]):
            return jsonify(error="Seguimiento no encontrado."), 404
        connection.execute("DELETE FROM followups WHERE id=?", (followup_id,))
    if row["evidence_path"]:
        (current_app.config["UPLOADS_DIR"] / row["evidence_path"]).unlink(missing_ok=True)
    return jsonify(ok=True)


@bp.get("/api/evidence/<int:followup_id>")
@require_auth("monitor", "coordinator", "admin")
def evidence(followup_id):
    with conn() as connection:
        row = connection.execute("SELECT f.evidence_path,f.monitor_id FROM followups f WHERE f.id=?", (followup_id,)).fetchone()
    if not row or not row["evidence_path"] or request.user["role"] == "monitor" and row["monitor_id"] != request.user["id"]:
        return jsonify(error="Evidencia no encontrada."), 404
    return send_from_directory(current_app.config["UPLOADS_DIR"], row["evidence_path"])


@bp.post("/api/surveys")
@require_auth("coordinator")
def create_survey():
    data = payload()
    returned = data.get("returned")
    if returned not in ("yes", "no", "1", "0", 1, 0):
        return jsonify(error="Indica si el estudiante regresó."), 400
    with conn() as connection:
        if data.get("reason") not in set(active_catalog(connection, "survey_reason")):
            return jsonify(error="El motivo no es válido."), 400
        if not connection.execute("SELECT 1 FROM risk_students WHERE id=?", (to_int(data.get("studentId")),)).fetchone():
            return jsonify(error="El estudiante no es válido."), 400
        result = connection.execute("""INSERT INTO surveys(risk_student_id,reason,returned,notes,created_by)
            VALUES(?,?,?,?,?)""", (to_int(data.get("studentId")), data["reason"], int(returned in ("yes", "1", 1)), data.get("notes", ""), request.user["id"]))
    return jsonify(id=result.lastrowid), 201


@bp.get("/api/surveys/summary")
@require_auth("coordinator")
def survey_summary():
    """Conteo y porcentaje de encuestas por motivo en el periodo activo."""
    with conn() as connection:
        rows = connection.execute("""SELECT s.reason,COUNT(*) count FROM surveys s JOIN risk_students r ON r.id=s.risk_student_id
            WHERE r.period_id=(SELECT id FROM periods WHERE active=1 LIMIT 1) GROUP BY s.reason ORDER BY count DESC""").fetchall()
        total = sum(r["count"] for r in rows)
    return jsonify([dict(row_dict(r), percentage=(r["count"] * 100 / total if total else 0)) for r in rows])


@bp.get("/api/surveys")
@require_auth("coordinator")
def list_surveys():
    """Encuestas de ausentismo registradas en el periodo activo."""
    with conn() as connection:
        rows = connection.execute("""SELECT s.id,s.reason,s.returned,s.notes,s.created_at,r.name student,r.document
            FROM surveys s JOIN risk_students r ON r.id=s.risk_student_id
            WHERE r.period_id=(SELECT id FROM periods WHERE active=1 LIMIT 1) ORDER BY s.id DESC""").fetchall()
    return jsonify([row_dict(x) for x in rows])


@bp.delete("/api/surveys/<int:survey_id>")
@require_auth("coordinator")
def delete_survey(survey_id):
    with conn() as connection:
        changed = connection.execute("DELETE FROM surveys WHERE id=?", (survey_id,))
    if changed.rowcount != 1:
        return jsonify(error="Encuesta no encontrada."), 404
    return jsonify(ok=True)


@bp.post("/api/risk/import/preview")
@require_auth("coordinator")
def import_preview():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="Selecciona un archivo CSV o XLSX."), 400
    try:
        headers, rows = parse_import(upload)
        for old in current_app.config["DATA_DIR"].glob("import-*.json"):
            if datetime.now().timestamp() - old.stat().st_mtime > 3600:
                old.unlink(missing_ok=True)
        key = f"import-{uuid.uuid4().hex}.json"
        (current_app.config["DATA_DIR"] / key).write_text(json.dumps({"headers": headers, "rows": rows}, ensure_ascii=False), encoding="utf-8")
        return jsonify(columns=headers, sample=rows[:10], suggested=suggested_mapping(headers), tempName=key)
    except (ValueError, UnicodeDecodeError, OSError, KeyError) as error:
        return jsonify(error=str(error)), 400


@bp.post("/api/risk/import/confirm")
@require_auth("coordinator")
def import_confirm():
    temp_name = request.form.get("tempName", "")
    source = current_app.config["DATA_DIR"] / Path(temp_name).name
    if not source.is_file():
        return jsonify(error="La vista previa expiró. Vuelve a cargar el archivo."), 400
    try:
        content = json.loads(source.read_text(encoding="utf-8"))
        mapping = json.loads(request.form.get("mapping", "{}"))
        with conn() as period_connection:
            period = active_period(period_connection)
        if not period:
            return jsonify(error="No hay periodo activo."), 400
        imported = updated = 0
        omitted = []
        with conn() as connection:
            for index, row in enumerate(content["rows"], start=2):
                document = str(row.get(mapping.get("document", ""), "")).strip()
                name = str(row.get(mapping.get("name", ""), "")).strip()
                if not document:
                    omitted.append({"row": index, "reason": "Sin documento"})
                    continue
                if not name:
                    omitted.append({"row": index, "reason": "Sin nombre"})
                    continue
                values = (period["id"], document, name, str(row.get(mapping.get("email", ""), "")), str(row.get(mapping.get("phone", ""), "")),
                          str(row.get(mapping.get("program", ""), "")), str(row.get(mapping.get("semester", ""), "")), str(row.get(mapping.get("course", ""), "")),
                          str(row.get(mapping.get("caseType", ""), "")), str(row.get(mapping.get("difficulty", ""), "")))
                existing = connection.execute("SELECT id FROM risk_students WHERE period_id=? AND document=? AND course=?", (period["id"], document, values[7])).fetchone()
                connection.execute("""INSERT INTO risk_students(period_id,document,name,email,phone,program,semester,course,case_type,difficulty)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(period_id,document,course) DO UPDATE SET name=excluded.name,email=excluded.email,
                    phone=excluded.phone,program=excluded.program,semester=excluded.semester,case_type=excluded.case_type,difficulty=excluded.difficulty""", values)
                if existing:
                    updated += 1
                else:
                    imported += 1
        return jsonify(imported=imported, updated=updated, omitted=omitted)
    except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as error:
        return jsonify(error=str(error)), 400
    finally:
        source.unlink(missing_ok=True)


@bp.get("/api/export/final.zip")
@require_auth("coordinator", "admin")
def export_final():
    from openpyxl import Workbook
    period = request.args.get("periodId")
    monitor_id = request.args.get("monitorId")
    program = request.args.get("program")
    with conn() as connection:
        period_row = connection.execute("SELECT id FROM periods WHERE id=?", (period,)).fetchone() if period else active_period(connection)
        if not period_row:
            return jsonify(error="No hay periodo activo."), 400
        args = [period_row["id"]]
        filters = ""
        if monitor_id:
            filters += " AND r.monitor_id=?"
            args.append(monitor_id)
        if program:
            filters += " AND r.program=?"
            args.append(program)
        data = {
            "estudiantes": connection.execute(f"SELECT r.document \"Documento\",r.name \"Nombre\",r.email \"Correo\",r.phone \"Teléfono\",r.program \"Programa\",r.semester \"Semestre\",r.course \"Curso\",r.case_type \"Tipo de caso\",r.difficulty \"Dificultad\",u.name \"Monitor\" FROM risk_students r LEFT JOIN users u ON u.id=r.monitor_id WHERE r.period_id=?{filters}", args).fetchall(),
            "seguimientos": connection.execute(f"SELECT f.id \"N.°\",r.document \"Documento\",r.name \"Estudiante\",f.medium \"Medio\",f.appointment_date \"Fecha\",f.work \"Trabajo socializado\",f.commitments \"Compromisos\",f.observations \"Observaciones\" FROM followups f JOIN risk_students r ON r.id=f.risk_student_id WHERE r.period_id=?{filters}", args).fetchall(),
            "alertas": connection.execute(f"SELECT r.document \"Documento\",r.name \"Estudiante\",a.alert_type \"Tipo de alerta\",a.grade \"Calificación\",a.action \"Acción\",a.observations \"Observaciones\" FROM alerts a JOIN risk_students r ON r.id=a.risk_student_id WHERE r.period_id=?{filters}", args).fetchall(),
            "encuestas": connection.execute(f"SELECT r.document \"Documento\",r.name \"Estudiante\",s.reason \"Motivo\",CASE s.returned WHEN 1 THEN 'Sí' ELSE 'No' END \"¿Regresó?\",s.notes \"Notas\",s.created_at \"Fecha\" FROM surveys s JOIN risk_students r ON r.id=s.risk_student_id WHERE r.period_id=?{filters}", args).fetchall(),
        }
        files = connection.execute(f"""SELECT f.evidence_path,r.document,r.name student,u.name monitor FROM followups f
            JOIN risk_students r ON r.id=f.risk_student_id JOIN users u ON u.id=f.monitor_id
            WHERE r.period_id=?{filters} AND f.evidence_path IS NOT NULL""", args).fetchall()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for sheet_name, rows in data.items():
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = sheet_name
            if rows:
                sheet.append(list(rows[0].keys()))
                for row in rows:
                    sheet.append(list(row))
            workbook_output = io.BytesIO()
            workbook.save(workbook_output)
            archive.writestr(f"{sheet_name}.xlsx", workbook_output.getvalue())
        for row in files:
            path = current_app.config["UPLOADS_DIR"] / row["evidence_path"]
            if path.is_file():
                archive.write(path, f"evidencias/{row['monitor']}/{row['document']}-{row['student']}/{row['evidence_path']}")
    output.seek(0)
    return send_file(output, mimetype="application/zip", as_attachment=True, download_name="reporte-monitorias.zip")
