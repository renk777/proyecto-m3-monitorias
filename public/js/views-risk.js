/* Vistas de estudiantes en riesgo (coordinador y monitor): listado, importación DARP, encuestas y exportación. */
'use strict';

const IMPORT_FIELDS = { document: 'Documento', name: 'Nombre', email: 'Correo', phone: 'Teléfono', program: 'Programa', semester: 'Semestre', course: 'Curso', caseType: 'Tipo de caso', difficulty: 'Dificultad' };

const riskStudentPicker = () => `
  <div class="student-picker" data-student-picker>
    <label>Buscar estudiante<input type="search" placeholder="Nombre o documento" autocomplete="off"></label>
    <label>Estudiante<select name="studentId" required><option value="">Selecciona un estudiante</option></select></label>
    <p class="hint" data-student-status role="status"></p>
    <nav class="pager" aria-label="Páginas de estudiantes"></nav>
  </div>`;

function mountRiskStudentPicker(picker) {
  if (!picker) return;
  const search = picker.querySelector('input');
  const select = picker.querySelector('select');
  const status = picker.querySelector('[data-student-status]');
  const pager = picker.querySelector('nav');
  const size = 20;
  let requestId = 0;
  let timer;

  async function load(page, id) {
    status.textContent = 'Buscando estudiantes…';
    pager.innerHTML = '';
    try {
      const params = new URLSearchParams({ page, limit: size, q: search.value.trim() });
      const result = await api('/api/risk/students?' + params);
      if (id !== requestId || !picker.isConnected) return;
      const selected = select.selectedOptions[0];
      const options = result.rows.map(s => [s.id, `${s.name} · ${s.document}`]);
      if (selected?.value && !result.rows.some(s => String(s.id) === selected.value)) {
        options.unshift([selected.value, selected.textContent]);
      }
      select.innerHTML = '<option value="">Selecciona un estudiante</option>' + optionsHtml(options, selected?.value);
      status.textContent = result.total ? '' : 'No se encontraron estudiantes.';
      pager.innerHTML = pagerHtml({ ...result, size }, 'data-student-page');
    } catch (error) {
      if (id !== requestId || !picker.isConnected) return;
      status.textContent = error.message;
      pager.innerHTML = `<button type="button" class="secondary small-btn" data-student-page="${page}">Reintentar</button>`;
    }
  }

  search.addEventListener('input', () => {
    clearTimeout(timer);
    const id = ++requestId;
    pager.innerHTML = '';
    timer = setTimeout(() => {
      if (picker.isConnected) load(1, id);
    }, 250);
  });
  pager.addEventListener('click', event => {
    const button = event.target.closest('[data-student-page]');
    if (button) load(Number(button.dataset.studentPage), ++requestId);
  });
  load(1, ++requestId);
}

/** Listado con búsqueda, filtros y paginación ejecutados en el servidor (puede haber miles de registros). */
function riskView() {
  const coordinator = state.user.role === 'coordinator', r = state.risk;
  const assignedFilter = coordinator ? `<label class="filter"><span class="sr-only">Asignación</span><select id="riskAssigned" aria-label="Asignación">${optionsHtml([['', 'Asignación: todos'], ['no', 'Sin monitor'], ['yes', 'Con monitor']], r.assigned)}</select></label>` : '';
  const toolbar = `<div class="toolbar"><div class="search-box">${icon('search')}<input type="search" id="riskSearch" value="${esc(r.q)}" placeholder="Buscar por nombre, documento, correo o curso" aria-label="Buscar estudiantes"></div><label class="filter"><span class="sr-only">Programa</span><select id="riskProgram" aria-label="Programa"><option value="">Programa: todos</option></select></label>${assignedFilter}<span class="count" id="riskCount" aria-live="polite"></span></div>`;
  const action = coordinator ? '<button type="button" class="primary small-btn" data-action="assignRisk">Repartir sin asignar</button>' : '';
  const note = coordinator ? '<p class="hint">Marca estudiantes para repartir solo esos; si no marcas ninguno, se reparten todos los que no tienen monitor.</p>' : '';
  return viewFrame(coordinator ? 'Repartir estudiantes' : 'Mis estudiantes', coordinator ? 'Filtra y reparte estudiantes entre monitores.' : 'Estudiantes en riesgo que tienes asignados.',
    panel(`${toolbar}<div id="riskBody"></div><nav class="pager" id="riskPager" aria-label="Paginación"></nav>`, panelHead('Estudiantes en riesgo', action)) + note);
}
/** Consulta la página actual al servidor y redibuja solo la tabla y el paginador. */
let riskRequestId = 0;
async function loadRisk() {
  const body = document.getElementById('riskBody');
  if (!body) return;
  const requestId = ++riskRequestId;
  const r = state.risk, coordinator = state.user.role === 'coordinator';
  const result = await api('/api/risk/students?' + new URLSearchParams({ page: r.page, limit: 10, q: r.q, program: r.program, assigned: r.assigned }));
  if (!body.isConnected || requestId !== riskRequestId) return;
  const select = document.getElementById('riskProgram');
  if (select && select.options.length === 1) select.insertAdjacentHTML('beforeend', optionsHtml(result.programs.map(p => [p, p]), r.program));
  r.page = result.page;
  const head = [...(coordinator ? ['<span class="sr-only">Seleccionar</span>'] : []), 'ESTUDIANTE', 'TIPO', 'PROGRAMA', 'CURSO', 'DIFICULTAD', 'MONITOR'];
  const rows = result.rows.map(s => `<tr>${coordinator ? `<td><input type="checkbox" class="risk-check" value="${s.id}" aria-label="Seleccionar a ${esc(s.name)}" ${r.selected?.has(String(s.id)) ? 'checked' : ''}></td>` : ''}<td>${esc(s.name)}<small>${esc(s.email)} · ${esc(s.phone)}</small></td><td>${esc(s.case_type)}</td><td>${esc(s.program)}</td><td>${esc(s.course)}</td><td>${esc(s.difficulty)}</td><td>${s.monitor ? esc(s.monitor) : '<span class="tag orange">Sin asignar</span>'}</td></tr>`).join('');
  body.innerHTML = result.rows.length ? tableHtml(head, rows) : emptyState('No hay estudiantes que coincidan con la búsqueda.');
  document.getElementById('riskCount').textContent = `${result.total} ${result.total === 1 ? 'estudiante' : 'estudiantes'}`;
  document.getElementById('riskPager').innerHTML = pagerHtml({ page: result.page, pages: result.pages, total: result.total, size: 10 }, 'data-risk-page');
}

/* ---------- Importación DARP ---------- */
const importView = () => viewFrame('Importar reportes DARP', 'Previsualiza columnas y confirma el mapeo.',
  `<div class="form-panel"><form id="previewForm" class="inline-form" novalidate><label>Archivo CSV o XLSX (máx. 5 MB)<input name="file" type="file" accept=".csv,.xlsx" required></label><button class="primary" type="submit">Previsualizar</button></form><div id="preview"></div></div>`);
/** Muestra las columnas detectadas, una vista previa y el formulario de mapeo. */
function renderImportPreview(result, fileName) {
  const sample = result.sample.slice(0, 5);
  const table = sample.length ? tableHtml(result.columns.map(esc), sample.map(row => `<tr>${result.columns.map(c => `<td>${esc(row[c])}</td>`).join('')}</tr>`).join('')) : '';
  const selects = Object.entries(IMPORT_FIELDS).map(([key, label]) => `<label>${label}<select name="${key}" ${['document', 'name'].includes(key) ? 'required' : ''}><option value="">-- Sin importar --</option>${optionsHtml(result.columns.map(c => [c, c]), result.suggested[key])}</select></label>`).join('');
  document.getElementById('preview').innerHTML = `<h3 class="sub-title">Vista previa (primeras ${sample.length} filas)</h3>${table}<form id="confirmImport" class="inline-form" novalidate><p class="required-note">Elige a qué columna corresponde cada dato del sistema.</p>${selects}<input type="hidden" name="tempName" value="${esc(result.tempName)}"><button class="primary" type="submit">Confirmar importación</button></form>`;
  markRequired(document.getElementById('preview'));
}

/* ---------- Encuestas de ausentismo ---------- */
async function surveysView() {
  const [summary, catalogs, rows] = await Promise.all([api('/api/surveys/summary'), api('/api/risk/catalogs'), api('/api/surveys')]);
  const form = formPanel('surveyForm',
    `${riskStudentPicker()}
     <label>Motivo<select name="reason" required>${optionsHtml(catalogs.reasons.map(x => [x, x]))}</select></label>
     <label>¿Regresó?<select name="returned" required>${optionsHtml([['yes', 'Sí'], ['no', 'No']])}</select></label>
     <label>Notas<textarea name="notes" maxlength="500"></textarea></label>`, 'Guardar encuesta');
  const summaryTable = tableHtml(['MOTIVO', 'CONTEO', 'PORCENTAJE'], summary.map(r => `<tr><td>${esc(r.reason)}</td><td>${r.count}</td><td>${Number(r.percentage).toFixed(1)}%</td></tr>`).join('') || '<tr><td colspan="3">Sin respuestas.</td></tr>');
  const list = collection('surveys', rows, {
    placeholder: 'Buscar por estudiante o notas', empty: 'Aún no hay encuestas.',
    search: s => `${s.student} ${s.document} ${s.notes} ${s.reason}`,
    filters: [{ key: 'reason', label: 'Motivo', get: s => s.reason }, { key: 'returned', label: '¿Regresó?', get: s => s.returned, options: [['1', 'Sí'], ['0', 'No']] }],
    renderBody: items => tableHtml(['ESTUDIANTE', 'MOTIVO', '¿REGRESÓ?', 'NOTAS', 'FECHA', ''], items.map(s => `<tr><td>${esc(s.student)}</td><td>${esc(s.reason)}</td><td>${s.returned ? 'Sí' : 'No'}</td><td>${esc(s.notes || '—')}</td><td>${esc(String(s.created_at).slice(0, 10))}</td><td><button type="button" class="link-btn" data-action="deleteSurvey" data-id="${s.id}">Eliminar</button></td></tr>`).join(''))
  });
  return viewFrame('Encuestas de ausentismo', 'Registra motivos y consulta el resumen.', `${form}${panel(summaryTable, panelHead('Resumen por motivo'))}<div class="spacer"></div>${panel(list, panelHead('Encuestas registradas'))}`);
}

/* ---------- Exportación ---------- */
async function exportView() {
  const [monitors, students] = await Promise.all([api('/api/users/monitors'), api('/api/risk/students?limit=1')]);
  return viewFrame('Reporte final', 'Descarga el ZIP filtrado por periodo.', panel(`<div class="toolbar"><label class="filter"><span class="sr-only">Monitor</span><select id="exportMonitor" data-export-filter aria-label="Monitor"><option value="">Monitor: todos</option>${optionsHtml(monitors.map(m => [m.id, m.name]))}</select></label><label class="filter"><span class="sr-only">Programa</span><select id="exportProgram" data-export-filter aria-label="Programa"><option value="">Programa: todos</option>${optionsHtml(students.programs.map(p => [p, p]))}</select></label></div><p class="hint">Incluye hojas de Excel (estudiantes, seguimientos, alertas y encuestas) y las evidencias organizadas por monitor.</p>`, panelHead('Exportación', '<a id="exportLink" class="primary small-btn" href="/api/export/final.zip" download>Descargar ZIP del periodo activo</a>')));
}
