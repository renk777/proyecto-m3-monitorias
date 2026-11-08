/* Vistas del monitor: disponibilidad, asistencia, horas y seguimientos. */
'use strict';

async function availabilityView() {
  const [rows, subjects] = await Promise.all([api('/api/availability'), api('/api/monitor/subjects')]);
  const form = formPanel('availabilityForm',
    `<label>Asignatura<select name="subjectId" required>${optionsHtml(subjects.map(s => [s.id, `${s.code} - ${s.name}`]))}</select></label>
     <label>Día<select name="weekday" required>${optionsHtml(WEEKDAYS.map((d, i) => [i, d]))}</select></label>
     <label>Desde<input name="startTime" type="time" required></label>
     <label>Hasta<input name="endTime" type="time" required data-after="startTime"></label>
     <label>Lugar<input name="place" required maxlength="80"></label>
     <label>Cupos<input name="capacity" type="number" min="1" max="50" value="10" required></label>`, 'Publicar bloque');
  const grid = WEEKDAYS.map((day, i) => `<div><h3>${day}</h3>${rows.filter(r => r.weekday === i).map(r => `<div class="calendar-block"><b>${esc(r.code)} - ${esc(r.name)}</b><small>${esc(r.start_time)}-${esc(r.end_time)} · ${esc(r.place)} · ${r.capacity} cupos</small><button type="button" class="link-btn" data-action="editAvailability" data-id="${r.id}" data-start="${esc(r.start_time)}" data-end="${esc(r.end_time)}" data-place="${esc(r.place)}" data-capacity="${r.capacity}">Editar</button><button type="button" class="link-btn" data-action="deleteAvailability" data-id="${r.id}">Eliminar</button></div>`).join('') || '<small>Sin bloques</small>'}</div>`).join('');
  return viewFrame('Disponibilidad semanal', 'Publica bloques y genera sesiones para cuatro semanas.', `${subjects.length ? form : panel(emptyState('Aún no tienes asignaturas asignadas. Pide a tu profesor que te asigne una.'))}<div class="calendar-grid">${grid}</div>`);
}

async function attendanceView() {
  const rows = await api('/api/attendance');
  const groups = [...new Set(rows.map(r => r.session_id))].map(id => {
    const students = rows.filter(r => r.session_id === id), first = students[0];
    return { id, subject: first.subject, date: first.session_date, time: `${first.start_time}-${first.end_time}`, closed: first.session_status === 'closed', students };
  });
  const body = items => items.map(g => `<div class="panel session-panel">${panelHead(`${esc(g.subject)} · ${fmtDate(g.date)} · ${esc(g.time)}`, g.closed ? '<span class="tag green">Cerrada</span>' : `<button type="button" class="primary small-btn" data-action="closeSession" data-id="${g.id}">Cerrar sesión</button>`)}<div class="list">${g.students.map(r => `<div class="list-row"><div><b>${esc(r.student)}</b><small>Estado: ${r.attended === null ? 'Sin marcar' : r.attended ? 'Asistió' : 'No asistió'}</small></div>${g.closed ? '' : `<button type="button" class="${r.attended === null ? 'primary' : 'secondary'} small-btn" data-action="attendance" data-id="${r.id}" data-value="${r.attended === 1 ? 0 : 1}">${r.attended === 1 ? 'Marcar: no asistió' : 'Marcar: asistió'}</button>`}</div>`).join('')}</div></div>`).join('');
  const list = collection('attendance', groups, {
    placeholder: 'Buscar por asignatura o estudiante', pageSize: 3, empty: 'No hay reservas confirmadas.',
    search: g => `${g.subject} ${g.date} ${g.students.map(s => s.student).join(' ')}`,
    filters: [{ key: 'closed', label: 'Estado', get: g => g.closed, options: [['false', 'Abiertas'], ['true', 'Cerradas']] }],
    renderBody: body
  });
  return viewFrame('Control de asistencia', 'La sesión solo puede cerrarse cuando todos estén marcados.', list);
}

async function hoursView() {
  const data = await api('/api/monitor/hours');
  const sum = status => data.reports.filter(r => r.status === status).reduce((n, r) => n + r.hours, 0);
  const history = collection('hoursHistory', data.history, {
    placeholder: 'Buscar sesiones cerradas', empty: 'Aún no hay sesiones cerradas.', pageSize: 6,
    search: r => `${r.name} ${r.code} ${r.session_date}`,
    filters: [{ key: 'subject', label: 'Asignatura', get: r => `${r.code} - ${r.name}` }],
    renderBody: items => tableHtml(['ASIGNATURA', 'FECHA', 'HORAS'], items.map(r => `<tr><td>${esc(r.code)} - ${esc(r.name)}</td><td>${fmtDate(r.session_date)}</td><td>${Number(r.hours).toFixed(2)}</td></tr>`).join(''))
  });
  const reports = tableHtml(['ASIGNATURA', 'MES', 'HORAS', 'ESTADO', 'OBSERVACIONES'], data.reports.map(r => `<tr><td>${esc(r.code)} - ${esc(r.subject)}</td><td>${fmtMonth(r.month)}</td><td>${fmtHours(r.hours)}</td><td>${statusTag(r.status)}</td><td>${esc(r.observations || '—')}</td></tr>`).join('') || '<tr><td colspan="5">Sin reportes.</td></tr>');
  return viewFrame('Mis horas', 'Resumen calculado desde sesiones cerradas.', `<div class="stats">${stat('Aprobadas', fmtHours(sum('approved')), 'check')}${stat('Pendientes', fmtHours(sum('pending')), 'calendar')}${stat('Sesiones cerradas', data.history.length, 'chart')}</div>${panel(reports, panelHead('Reportes mensuales'))}<div class="spacer"></div>${panel(history, panelHead('Historial de sesiones'))}`);
}

/* ---------- Seguimientos (monitor registra; coordinador consulta y corrige) ---------- */
async function followupsView() {
  const isMonitor = state.user.role === 'monitor';
  const [rows, students] = await Promise.all([api('/api/risk/followups'), isMonitor ? api('/api/risk/students?limit=200') : { rows: [] }]);
  const form = isMonitor ? formPanel('followupForm',
    `<label>Estudiante<select name="studentId" required>${optionsHtml(students.rows.map(s => [s.id, `${s.name} · ${s.difficulty || s.case_type}`]))}</select></label>
     <label>Medio<select name="medium" required>${optionsHtml(['WhatsApp', 'Correo', 'Videollamada', 'Presencial'].map(x => [x, x]))}</select></label>
     <label>Fecha<input name="appointmentDate" type="date" required></label>
     <label>Trabajo socializado<input name="work" required maxlength="300"></label>
     <label>Compromisos<input name="commitments" required maxlength="300"></label>
     <label>Observaciones<input name="observations" required maxlength="500"></label>
     <label>Evidencia (JPG, PNG o WEBP, máx. 5 MB)<input name="evidence" type="file" accept=".jpg,.jpeg,.png,.webp"></label>`, 'Guardar seguimiento', 'enctype="multipart/form-data"') : '';
  const list = collection('followups', rows, {
    placeholder: 'Buscar por estudiante, documento u observaciones', empty: 'Aún no hay seguimientos registrados.',
    search: r => `${r.student} ${r.document} ${r.observations} ${r.work} ${r.monitor}`,
    filters: [{ key: 'medium', label: 'Medio', get: r => r.medium }, ...(isMonitor ? [] : [{ key: 'monitor', label: 'Monitor', get: r => r.monitor }])],
    renderBody: items => `<div class="list">${items.map(r => `<div class="list-row"><div><b>${esc(r.student)} · ${esc(r.medium)}</b><small>${fmtDate(r.appointment_date)} · Monitor: ${esc(r.monitor)}</small><small>${esc(r.observations)}</small></div><div>${r.evidence_path ? `<a class="link-btn" href="/api/evidence/${r.id}" target="_blank" rel="noopener">Evidencia</a>` : ''}<button type="button" class="secondary small-btn" data-action="editFollowup" data-id="${r.id}" data-medium="${esc(r.medium)}" data-date="${esc(r.appointment_date)}" data-work="${esc(r.work)}" data-commitments="${esc(r.commitments)}" data-observations="${esc(r.observations)}">Editar</button><button type="button" class="secondary small-btn" data-action="deleteFollowup" data-id="${r.id}">Eliminar</button></div></div>`).join('')}</div>`
  });
  return viewFrame('Seguimientos', 'Registra contactos y evidencias.', `${isMonitor && !students.rows.length ? panel(emptyState('Aún no tienes estudiantes asignados para registrar seguimientos.')) : form}${panel(list)}`);
}
