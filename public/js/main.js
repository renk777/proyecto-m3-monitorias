/* Arranque de la aplicación: rutas de vistas, formularios, acciones, eventos y renderizado. */
'use strict';

const VIEWS = {
  dashboard: dashboardView, password: passwordView, subjects: subjectsView, bookings: bookingsView,
  availability: availabilityView, attendance: attendanceView, hours: hoursView, risk: riskView, followups: followupsView,
  assignments: assignmentsView, reports: reportsView, analytics: analyticsView, alerts: alertsView,
  imports: importView, surveys: surveysView, export: exportView,
  users: usersView, subjectsAdmin: subjectsAdminView, periods: periodsView, catalogs: catalogsView
};
const freshRisk = () => ({ page: 1, q: '', program: '', assigned: '', selected: new Set() });
state.risk = freshRisk();
state.periodId = '';

/** Dibuja la vista actual consultando la API (datos 100 % dinámicos). */
async function render({ keepScroll = false } = {}) {
  if (!state.user) return showLogin();
  const scroll = keepScroll ? window.scrollY : 0;
  try {
    if (![...NAV[state.user.role], ['password']].some(x => x[0] === state.view)) state.view = 'dashboard';
    if (state.view !== 'dashboard') { try { state.data.dashboard = await api('/api/dashboard'); } catch (error) { if (!state.user) return; } }
    const content = await VIEWS[state.view]();
    shell(content);
    markRequired(app);
    mountCollections();
    mountRiskStudentPicker(app.querySelector('[data-student-picker]'));
    if (state.view === 'risk') await loadRisk();
    window.scrollTo(0, scroll);
  } catch (error) { toast(error.message, 'error'); }
}

/* ---------- Formularios (se enlazan por id; devolver false evita volver a dibujar la vista) ---------- */
const formHandlers = {
  loginForm: async data => { state.user = (await post('/api/auth/login', data)).user; state.view = 'dashboard'; },
  passwordForm: async (data, form) => { await patch('/api/auth/password', data); toast('Contraseña actualizada.', 'success'); form.reset(); return false; },
  availabilityForm: async data => { await post('/api/availability', data); toast('Bloque publicado y sesiones generadas.', 'success'); },
  assignmentForm: async data => { await post('/api/teacher/assignments', data); toast('Monitor asignado.', 'success'); },
  followupForm: async (data, form) => { await api('/api/risk/followups', { method: 'POST', body: new FormData(form) }); toast('Seguimiento guardado.', 'success'); },
  surveyForm: async data => { await post('/api/surveys', data); toast('Encuesta guardada.', 'success'); },
  userForm: async data => { await post('/api/admin/users', data); toast('Usuario creado.', 'success'); },
  subjectForm: async data => { await post('/api/admin/subjects', data); toast('Asignatura creada.', 'success'); },
  periodForm: async data => { await post('/api/admin/periods', data); toast('Periodo creado y activado.', 'success'); },
  catalogForm: async data => { await post('/api/admin/catalogs', data); toast('Opción agregada.', 'success'); },
  alertForm: async data => {
    const rows = [...document.querySelectorAll('#alertForm .alert-row')].filter(r => r.querySelector('.alert-pick')?.checked)
      .map(r => Object.fromEntries([...r.querySelectorAll('input[name],select[name]')].map(i => [i.name, i.value])));
    if (!rows.length) throw new Error('Marca al menos un estudiante para guardar su alerta.');
    await post('/api/alerts/bulk', { subjectId: data.subjectId, rows });
    toast(`${rows.length} ${rows.length === 1 ? 'alerta guardada' : 'alertas guardadas'}.`, 'success');
  },
  previewForm: async (data, form) => { renderImportPreview(await api('/api/risk/import/preview', { method: 'POST', body: new FormData(form) }), form.file.files[0].name); return false; },
  confirmImport: async (data, form) => {
    const mapping = Object.fromEntries(Object.keys(IMPORT_FIELDS).map(k => [k, form.elements[k].value]));
    const body = new FormData();
    body.set('tempName', form.elements.tempName.value);
    body.set('mapping', JSON.stringify(mapping));
    const out = await api('/api/risk/import/confirm', { method: 'POST', body });
    toast(`Importados: ${out.imported}. Actualizados: ${out.updated}. Omitidos: ${out.omitted.length}.`, 'success');
    state.risk = freshRisk();
  }
};

/* ---------- Acciones de botones (data-action) ---------- */
const ask = (message, confirmText = 'Sí, continuar', title = 'Confirmar acción') => confirmDialog({ title, message, confirmText });
const actionHandlers = {
  logout: async () => { await api('/api/auth/logout', { method: 'POST' }); state.user = null; state.view = 'dashboard'; state.data = {}; state.risk = freshRisk(); },
  readNotifications: () => post('/api/notifications/read'),
  book: async el => { await post('/api/bookings', { sessionId: el.dataset.id }); toast('Reserva confirmada.', 'success'); },
  cancel: async el => {
    if (!await ask('¿Seguro que quieres cancelar esta reserva?', 'Sí, cancelar', 'Cancelar reserva')) return false;
    await patch(`/api/bookings/${el.dataset.id}/cancel`); toast('Reserva cancelada.', 'success');
  },
  rate: async el => { if (!await ratingModal(Number(el.dataset.id))) return false; },
  attendance: el => post('/api/attendance', { bookingId: el.dataset.id, attended: el.dataset.value }),
  closeSession: async el => {
    if (!await ask('Al cerrar la sesión se calculan las horas del monitor y ya no se podrá modificar la asistencia.', 'Cerrar sesión', 'Cerrar sesión')) return false;
    await post(`/api/sessions/${el.dataset.id}/close`); toast('Sesión cerrada y horas actualizadas.', 'success');
  },
  editAvailability: async el => {
    const d = el.dataset;
    if (!await openModal({ title: 'Editar bloque', body: `<label>Desde<input name="startTime" type="time" required value="${esc(d.start)}"></label><label>Hasta<input name="endTime" type="time" required data-after="startTime" value="${esc(d.end)}"></label><label>Lugar<input name="place" required maxlength="80" value="${esc(d.place)}"></label><label>Cupos<input name="capacity" type="number" min="1" max="50" required value="${esc(d.capacity)}"></label>`, onSubmit: data => patch(`/api/availability/${d.id}`, data) })) return false;
    toast('Bloque actualizado.', 'success');
  },
  deleteAvailability: async el => {
    if (!await ask('Se cancelarán las reservas futuras de este bloque.', 'Eliminar bloque', 'Eliminar bloque')) return false;
    await del(`/api/availability/${el.dataset.id}`); toast('Bloque eliminado.', 'success');
  },
  unassign: async el => {
    if (!await ask('¿Quitar a este monitor de la asignatura?', 'Quitar monitor', 'Quitar monitor')) return false;
    await del(`/api/teacher/assignments/${el.dataset.id}`); toast('Monitor retirado.', 'success');
  },
  report: async el => {
    const rejecting = el.dataset.status === 'rejected';
    if (!await openModal({ title: rejecting ? 'Rechazar reporte' : 'Aprobar reporte', submitText: rejecting ? 'Rechazar' : 'Aprobar', danger: rejecting, body: `<label>Observaciones<textarea name="observations" maxlength="500" ${rejecting ? 'required' : ''}></textarea></label>`, onSubmit: data => patch(`/api/reports/${el.dataset.id}`, { status: el.dataset.status, ...data }) })) return false;
    toast(rejecting ? 'Reporte rechazado.' : 'Reporte aprobado.', 'success');
  },
  deleteAlert: async el => { if (!await ask('¿Eliminar esta alerta?', 'Eliminar', 'Eliminar alerta')) return false; await del(`/api/alerts/${el.dataset.id}`); toast('Alerta eliminada.', 'success'); },
  assignRisk: async () => {
    const ids = [...state.risk.selected].map(Number);
    const result = await post('/api/risk/assign', { studentIds: ids });
    state.risk.selected.clear();
    toast(`${result.assigned} ${result.assigned === 1 ? 'estudiante repartido' : 'estudiantes repartidos'}.`, result.assigned ? 'success' : 'info');
  },
  editFollowup: async el => {
    const d = el.dataset;
    if (!await openModal({ title: 'Editar seguimiento', body: `<label>Medio<select name="medium" required>${optionsHtml(['WhatsApp', 'Correo', 'Videollamada', 'Presencial'].map(x => [x, x]), d.medium)}</select></label><label>Fecha<input name="appointmentDate" type="date" required value="${esc(d.date)}"></label><label>Trabajo socializado<input name="work" required maxlength="300" value="${esc(d.work)}"></label><label>Compromisos<input name="commitments" required maxlength="300" value="${esc(d.commitments)}"></label><label>Observaciones<input name="observations" required maxlength="500" value="${esc(d.observations)}"></label>`, onSubmit: data => patch(`/api/risk/followups/${d.id}`, data) })) return false;
    toast('Seguimiento actualizado.', 'success');
  },
  deleteFollowup: async el => { if (!await ask('¿Eliminar este seguimiento y su evidencia?', 'Eliminar', 'Eliminar seguimiento')) return false; await del(`/api/risk/followups/${el.dataset.id}`); toast('Seguimiento eliminado.', 'success'); },
  deleteSurvey: async el => { if (!await ask('¿Eliminar esta encuesta?', 'Eliminar', 'Eliminar encuesta')) return false; await del(`/api/surveys/${el.dataset.id}`); toast('Encuesta eliminada.', 'success'); },
  editUser: async el => {
    const d = el.dataset;
    if (!await openModal({ title: 'Editar usuario', body: `<label>Nombre completo<input name="name" required maxlength="80" value="${esc(d.name)}"></label><label>Correo institucional<input name="email" type="email" required value="${esc(d.email)}"></label><label>Rol<select name="role" required>${roleOptions(d.role)}</select></label>`, onSubmit: data => patch(`/api/admin/users/${d.id}`, data) })) return false;
    toast('Usuario actualizado.', 'success');
  },
  resetUser: async el => {
    if (!await openModal({ title: 'Restablecer contraseña', body: '<label>Nueva contraseña<input name="password" type="password" minlength="8" required autocomplete="new-password"></label>', onSubmit: data => post(`/api/admin/users/${el.dataset.id}/reset-password`, data) })) return false;
    toast('Contraseña restablecida.', 'success');
  },
  toggleUser: async el => {
    const active = el.dataset.value === '1';
    if (!active && !await ask(`¿Desactivar la cuenta de ${esc(el.dataset.name)}? No podrá iniciar sesión.`, 'Desactivar', 'Desactivar usuario')) return false;
    await patch(`/api/admin/users/${el.dataset.id}`, { active }); toast(active ? 'Usuario activado.' : 'Usuario desactivado.', 'success');
  },
  editSubject: async el => {
    const d = el.dataset;
    if (!await openModal({ title: 'Editar asignatura', body: `<label>Código<input name="code" required maxlength="20" value="${esc(d.code)}"></label><label>Nombre de la asignatura<input name="name" required maxlength="80" value="${esc(d.name)}"></label><label>Profesor<select name="teacherId"><option value="">Sin profesor</option>${teacherOptions(d.teacher)}</select></label>`, onSubmit: data => patch(`/api/admin/subjects/${d.id}`, data) })) return false;
    toast('Asignatura actualizada.', 'success');
  },
  deleteSubject: async el => { if (!await ask(`¿Eliminar la asignatura ${esc(el.dataset.label)}?`, 'Eliminar', 'Eliminar asignatura')) return false; await del(`/api/admin/subjects/${el.dataset.id}`); toast('Asignatura eliminada.', 'success'); },
  activatePeriod: async el => { if (!await ask('Solo un periodo puede estar activo; el actual quedará inactivo.', 'Activar periodo', 'Activar periodo')) return false; await post(`/api/admin/periods/${el.dataset.id}/activate`); toast('Periodo activado.', 'success'); },
  deletePeriod: async el => { if (!await ask(`¿Eliminar el periodo ${esc(el.dataset.label)}?`, 'Eliminar', 'Eliminar periodo')) return false; await del(`/api/admin/periods/${el.dataset.id}`); toast('Periodo eliminado.', 'success'); },
  toggleCatalog: async el => { const active = el.dataset.value === '1'; await patch(`/api/admin/catalogs/${el.dataset.id}`, { active }); toast(active ? 'Opción activada.' : 'Opción desactivada.', 'success'); }
};

/* ---------- Eventos globales (delegación: funcionan con contenido que se redibuja) ---------- */
document.addEventListener('click', async event => {
  const target = event.target;
  const star = target.closest('[data-score]');
  if (star) {
    const form = star.closest('form');
    form.elements.score.value = star.dataset.score;
    form.querySelectorAll('[data-score]').forEach(s => {
      s.classList.toggle('selected', Number(s.dataset.score) <= Number(star.dataset.score));
      s.setAttribute('aria-pressed', String(s === star));
    });
    form.querySelector('[data-score-error]').textContent = '';
    return;
  }
  const view = target.closest('[data-view]');
  if (view) { state.view = view.dataset.view; return render(); }
  const collPage = target.closest('[data-coll-page]');
  if (collPage) { const id = collPage.closest('[data-collection]').dataset.collection; collections[id].page = Number(collPage.dataset.collPage); return refreshCollection(id); }
  const riskPage = target.closest('[data-risk-page]');
  if (riskPage) { state.risk.page = Number(riskPage.dataset.riskPage); return loadRisk().catch(e => toast(e.message, 'error')); }
  const button = target.closest('[data-action]');
  if (!button || button.disabled) return;
  button.disabled = true;
  try {
    const result = await actionHandlers[button.dataset.action](button);
    if (result !== false) await render({ keepScroll: true });
  } catch (error) { toast(error.message, 'error'); }
  finally { button.disabled = false; }
});

document.addEventListener('submit', async event => {
  const form = event.target, handler = formHandlers[form.id];
  if (!handler) return;
  event.preventDefault();
  if (!validateForm(form)) return;
  const submit = form.querySelector('[type="submit"]'), label = submit?.textContent;
  if (submit) { submit.disabled = true; submit.textContent = 'Guardando…'; }
  try {
    const result = await handler(Object.fromEntries(new FormData(form)), form);
    if (result !== false) await render({ keepScroll: true });
  } catch (error) { toast(error.message, 'error'); }
  finally { if (submit?.isConnected) { submit.disabled = false; submit.textContent = label; } }
});

let riskTimer;
document.addEventListener('input', event => {
  const t = event.target;
  clearFieldError(t);
  if (t.matches('[data-coll-q]')) { const c = collections[t.closest('[data-collection]').dataset.collection]; c.q = t.value; c.page = 1; refreshCollection(t.closest('[data-collection]').dataset.collection); }
  if (t.id === 'riskSearch') {
    clearTimeout(riskTimer);
    riskTimer = setTimeout(() => {
      if (!t.isConnected) return;
      state.risk.q = t.value.trim();
      state.risk.page = 1;
      loadRisk().catch(e => toast(e.message, 'error'));
    }, 300);
  }
});

document.addEventListener('change', async event => {
  const t = event.target;
  clearFieldError(t);
  try {
    if (t.matches('[data-coll-filter]')) { const id = t.closest('[data-collection]').dataset.collection; collections[id].filters[t.dataset.collFilter] = t.value; collections[id].page = 1; refreshCollection(id); }
    else if (t.id === 'riskProgram' || t.id === 'riskAssigned') { state.risk[t.id === 'riskProgram' ? 'program' : 'assigned'] = t.value; state.risk.page = 1; await loadRisk(); }
    else if (t.matches('.risk-check')) state.risk.selected[t.checked ? 'add' : 'delete'](t.value);
    else if (t.matches('.alert-pick')) {
      t.closest('.alert-row').querySelectorAll('select, input:not([type="hidden"]):not([type="checkbox"])').forEach(field => {
        field.disabled = !t.checked;
        if (field.disabled) clearFieldError(field);
      });
    }
    else if (t.id === 'periodFilter') { state.periodId = t.value; await render({ keepScroll: true }); }
    else if (t.matches('[data-export-filter]')) {
      const params = new URLSearchParams({ monitorId: document.getElementById('exportMonitor').value, program: document.getElementById('exportProgram').value });
      document.getElementById('exportLink').href = '/api/export/final.zip?' + params;
    } else if (t.id === 'alertSubject') {
      const sheet = document.getElementById('alertSheet');
      const subjectId = t.value;
      sheet.textContent = 'Cargando estudiantes…';
      const students = await api(`/api/teacher/risk-students?subjectId=${subjectId}`);
      if (!sheet.isConnected || t.value !== subjectId) return;
      sheet.innerHTML = alertRows(students, state.data.alertCatalogs);
      markRequired(sheet);
    }
  } catch (error) { toast(error.message, 'error'); }
});

/* ---------- Inicio ---------- */
Promise.all([fetch('/api/config').then(x => x.json()).catch(() => ({})), api('/api/auth/me').catch(() => null)]).then(([config, session]) => {
  window.DEMO_MODE = config.demoMode === true;
  if (session) state.user = session.user;
  render();
});
