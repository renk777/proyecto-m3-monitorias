/* Vistas del estudiante: oferta de monitorías y reservas. */
'use strict';

async function subjectsView() {
  const rows = await api('/api/subjects');
  const body = items => `<div class="cards">${items.map(s => `<article class="session-card"><div><span class="tag blue">${esc(s.code)}</span><h3>${esc(s.name)}</h3><p>Monitor: <b>${esc(s.monitor)}</b> · ★ ${Number(s.rating).toFixed(1)}</p><p>${fmtDate(s.session_date)} · ${esc(s.start_time)}-${esc(s.end_time)} · ${esc(s.place)}</p></div><div><span class="availability">${s.seats} cupos</span>${s.mine ? '<span class="tag green">Reservada</span>' : s.seats <= 0 ? '<span class="tag orange">Sin cupos</span>' : `<button type="button" class="primary small-btn" data-action="book" data-id="${s.session_id}">Agendar</button>`}</div></article>`).join('')}</div>`;
  const list = collection('offer', rows, {
    placeholder: 'Buscar por asignatura, código o monitor', pageSize: 6, empty: 'Todavía no hay sesiones abiertas.',
    search: s => `${s.code} ${s.name} ${s.monitor} ${s.place}`,
    filters: [{ key: 'subject', label: 'Asignatura', get: s => `${s.code} - ${s.name}` }, { key: 'monitor', label: 'Monitor', get: s => s.monitor }],
    renderBody: body
  });
  return viewFrame('Buscar monitorías', 'Consulta asignaturas, horarios y cupos disponibles.', panel(list, panelHead('Oferta disponible')));
}

async function bookingsView() {
  const rows = await api('/api/bookings');
  const attendanceText = r => r.attended === null || r.attended === undefined ? 'Asistencia pendiente' : r.attended ? 'Asistió' : 'No asistió';
  const body = items => `<div class="list">${items.map(r => {
    const canCancel = r.status === 'confirmed' && r.session_status === 'open' && (isDemo() || r.session_date >= todayBogota());
    return `<div class="list-row"><div><b>${esc(r.subject)}</b><small>${fmtDate(r.session_date)} · ${esc(r.start_time)}-${esc(r.end_time)} · ${esc(r.place)}</small><small>${statusTag(r.status)} ${r.status === 'confirmed' ? esc(attendanceText(r)) : ''} ${r.rating_score ? `· Tu calificación: ${'★'.repeat(r.rating_score)}` : ''}</small></div><div>${canCancel ? `<button type="button" class="secondary small-btn" data-action="cancel" data-id="${r.id}">Cancelar</button>` : ''}${r.attended === 1 && !r.rating_score ? `<button type="button" class="primary small-btn" data-action="rate" data-id="${r.id}">Calificar</button>` : ''}</div></div>`;
  }).join('')}</div>`;
  const list = collection('bookings', rows, {
    placeholder: 'Buscar por asignatura o lugar', empty: 'Aún no tienes reservas.',
    search: r => `${r.subject} ${r.place} ${r.session_date}`,
    filters: [{ key: 'status', label: 'Estado', get: r => r.status, format: v => STATUS_NAMES[v] }, { key: 'subject', label: 'Asignatura', get: r => r.subject }],
    renderBody: body
  });
  return viewFrame('Mis reservas', 'Consulta estados, asistencia y calificaciones.', panel(list));
}

/** Modal con estrellas para calificar una sesión a la que asistió el estudiante. */
function ratingModal(bookingId) {
  return openModal({
    title: 'Califica tu sesión', submitText: 'Enviar calificación',
    body: '<fieldset><legend>Calificación <b class="required-mark" aria-hidden="true">*</b><span class="sr-only"> (obligatoria)</span></legend><div class="stars">' +
      [1, 2, 3, 4, 5].map(n => `<button type="button" data-score="${n}" aria-label="${n} de 5 estrellas" aria-pressed="false">★</button>`).join('') +
      '</div><small class="field-error" data-score-error role="alert"></small></fieldset><input type="hidden" name="score"><label>Comentario (opcional)<textarea name="comment" maxlength="500"></textarea></label>',
    onSubmit: async (data, form) => {
      if (!data.score) {
        const message = 'Selecciona de 1 a 5 estrellas.';
        form.querySelector('[data-score-error]').textContent = message;
        form.querySelector('[data-score]').focus();
        throw new Error(message);
      }
      await post('/api/ratings', { bookingId, score: Number(data.score), comment: data.comment });
      toast('Calificación guardada. ¡Gracias!', 'success');
    }
  });
}
