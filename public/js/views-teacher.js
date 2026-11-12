/* Vistas del profesor: asignaciones, reportes de horas, indicadores y alertas tempranas. */
'use strict';

/** Selector de periodo que filtra reportes e indicadores sin cambiar el diseño de la página. */
async function periodSelect() {
  const periods = await api('/api/periods');
  return `<label class="filter period-filter"><span class="sr-only">Periodo</span><select id="periodFilter" aria-label="Periodo académico"><option value="">Periodo: todos</option>${optionsHtml(periods.map(p => [p.id, p.name + (p.active ? ' (activo)' : '')]), state.periodId)}</select></label>`;
}

async function assignmentsView() {
  const [rows, subjects, monitors] = await Promise.all([api('/api/teacher/assignments'), api('/api/teacher/subjects'), api('/api/users/monitors')]);
  const form = formPanel('assignmentForm',
    `<label>Asignatura<select name="subjectId" required>${optionsHtml(subjects.map(s => [s.id, `${s.code} - ${s.name}`]))}</select></label>
     <label>Monitor<select name="monitorId" required>${optionsHtml(monitors.map(u => [u.id, u.name]))}</select></label>`, 'Asignar monitor');
  const list = collection('assignments', rows, {
    placeholder: 'Buscar por asignatura o monitor', empty: 'No hay monitores asignados.',
    search: r => `${r.code} ${r.name} ${r.monitor}`,
    filters: [{ key: 'subject', label: 'Asignatura', get: r => `${r.code} - ${r.name}` }],
    renderBody: items => `<div class="list">${items.map(r => `<div class="list-row"><div><b>${esc(r.code)} - ${esc(r.name)}</b><small>Monitor: ${esc(r.monitor)}</small></div><button type="button" class="secondary small-btn" data-action="unassign" data-id="${r.id}">Quitar</button></div>`).join('')}</div>`
  });
  return viewFrame('Asignaciones de materias', 'Asigna y retira monitores de tus asignaturas.', `${form}${panel(list)}`);
}

async function reportsView() {
  const [rows, select] = await Promise.all([api('/api/reports?periodId=' + encodeURIComponent(state.periodId)), periodSelect()]);
  const list = collection('reports', rows, {
    placeholder: 'Buscar por asignatura o monitor', empty: 'No hay reportes de horas.',
    search: r => `${r.subject} ${r.code} ${r.monitor} ${r.month}`,
    filters: [{ key: 'status', label: 'Estado', get: r => r.status, format: v => STATUS_NAMES[v] }, { key: 'subject', label: 'Asignatura', get: r => r.subject }, { key: 'month', label: 'Mes', get: r => r.month, format: fmtMonth }],
    renderBody: items => tableHtml(['ASIGNATURA', 'MONITOR', 'MES', 'HORAS', 'ESTADO', 'ACCIONES'], items.map(r => `<tr><td>${esc(r.code)} - ${esc(r.subject)}</td><td>${esc(r.monitor)}</td><td>${fmtMonth(r.month)}</td><td>${fmtHours(r.hours)}</td><td>${statusTag(r.status)}</td><td>${r.status === 'pending' ? `<button type="button" class="primary small-btn" data-action="report" data-id="${r.id}" data-status="approved">Aprobar</button> <button type="button" class="secondary small-btn" data-action="report" data-id="${r.id}" data-status="rejected">Rechazar</button>` : esc(r.observations || '—')}</td></tr>`).join(''))
  });
  return viewFrame('Reportes de horas', 'Aprueba o rechaza reportes de tus materias.', panel(list, panelHead('Reportes mensuales', select)));
}

async function analyticsView() {
  const [rows, select] = await Promise.all([api('/api/analytics?periodId=' + encodeURIComponent(state.periodId)), periodSelect()]);
  const max = Math.max(1, ...rows.map(r => Number(r.participation)));
  const list = collection('analytics', rows, {
    placeholder: 'Buscar asignatura', empty: 'No hay datos para mostrar.', pageSize: 10,
    search: r => `${r.code} ${r.name}`,
    renderBody: items => tableHtml(['ASIGNATURA', 'PARTICIPACIÓN', 'ASISTENCIA', 'SATISFACCIÓN', 'HORAS'], items.map(r => `<tr><td>${esc(r.code)} - ${esc(r.name)}</td><td>${r.participation}</td><td>${Number(r.attendance).toFixed(0)}%</td><td>${Number(r.satisfaction).toFixed(1)}</td><td>${Number(r.hours).toFixed(1)}</td></tr>`).join(''))
  });
  const satisfaction = (rows.reduce((n, r) => n + r.satisfaction, 0) / (rows.length || 1)).toFixed(1);
  return viewFrame('Indicadores académicos', 'Consulta métricas reales del programa.', `<div class="stats">${stat('Materias', rows.length, 'grid')}${stat('Sesiones completadas', rows.reduce((n, r) => n + r.completed, 0), 'check')}${stat('Satisfacción', satisfaction, 'chart')}</div><div class="panel chart-panel"><h2>Participación por asignatura</h2><div class="bar-chart" role="img" aria-label="Gráfico de participación por asignatura">${rows.map(r => `<div class="bar-item"><div class="bar" style="height:${Math.max(8, Number(r.participation) * 100 / max)}%" title="${r.participation} reservas"></div><small>${esc(r.code)}</small></div>`).join('') || emptyState('No hay datos para graficar.')}</div></div><div class="spacer"></div>${panel(list, panelHead('Detalle por asignatura', select))}`);
}

/* ---------- Alertas tempranas ---------- */
/** Filas editables (una por estudiante en riesgo del curso). */
function alertRows(students, catalogs) {
  if (!students.length) return emptyState('No hay estudiantes en riesgo para este curso.');
  return students.map(s => `<div class="alert-row">
    <input type="hidden" name="studentId" value="${s.id}">
    <label class="alert-pick-label"><input type="checkbox" class="alert-pick"> ${esc(s.name)}</label>
    <label>Tipo de alerta<select name="alertType" required disabled><option value="">Selecciona un tipo</option>${optionsHtml(catalogs.alertTypes.map(x => [x, x]))}</select></label>
    <label>Calificación<input name="grade" placeholder="Ej.: 2,5" maxlength="10" disabled></label>
    <label>Acción<select name="action" required disabled><option value="">Selecciona una acción</option>${optionsHtml(catalogs.actions.map(x => [x, x]))}</select></label>
    <label>Observaciones<input name="observations" maxlength="300" disabled></label>
  </div>`).join('');
}
async function alertsView() {
  const [subjects, catalogs, history] = await Promise.all([api('/api/teacher/subjects'), api('/api/risk/catalogs'), api('/api/alerts')]);
  state.data.alertCatalogs = catalogs;
  const students = subjects.length ? await api(`/api/teacher/risk-students?subjectId=${subjects[0].id}`) : [];
  const historyList = collection('alertHistory', history, {
    placeholder: 'Buscar por estudiante u observaciones', empty: 'Aún no has registrado alertas.',
    search: a => `${a.student} ${a.document} ${a.observations} ${a.course}`,
    filters: [{ key: 'type', label: 'Tipo', get: a => a.alert_type }, { key: 'course', label: 'Curso', get: a => a.course }],
    renderBody: items => tableHtml(['ESTUDIANTE', 'CURSO', 'TIPO', 'CALIFICACIÓN', 'ACCIÓN', 'FECHA', ''], items.map(a => `<tr><td>${esc(a.student)}</td><td>${esc(a.course)}</td><td>${esc(a.alert_type)}</td><td>${esc(a.grade || '—')}</td><td>${esc(a.action)}</td><td>${esc(String(a.created_at).slice(0, 10))}</td><td><button type="button" class="link-btn" data-action="deleteAlert" data-id="${a.id}">Eliminar</button></td></tr>`).join(''))
  });
  return viewFrame('Alertas tempranas', 'Marca a los estudiantes que necesitan una alerta y guárdalas juntas.',
    `<div class="form-panel"><form id="alertForm" novalidate><label>Curso<select name="subjectId" id="alertSubject" required>${optionsHtml(subjects.map(s => [s.id, `${s.code} - ${s.name}`]))}</select></label><div class="sheet-wrap" id="alertSheet">${alertRows(students, catalogs)}</div><button class="primary" type="submit">Guardar alertas</button></form></div>${panel(historyList, panelHead('Alertas registradas'))}`);
}
