/* Componentes reutilizables: iconos, modales, tablas con búsqueda/filtros/paginación y validación de formularios. */
'use strict';

/* ---------- Iconos (sprite SVG en línea) ---------- */
const ICONS = `<svg hidden><symbol id="icon-grid" viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><rect x="14" y="14" width="6" height="6"/></symbol><symbol id="icon-search" viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></symbol><symbol id="icon-calendar" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/></symbol><symbol id="icon-check" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></symbol><symbol id="icon-chart" viewBox="0 0 24 24"><path d="M5 19V9M12 19V5M19 19v-7M3 19h18"/></symbol></svg>`;
const icon = name => `<svg aria-hidden="true" viewBox="0 0 24 24"><use href="#icon-${name}"></use></svg>`;

/* ---------- Fragmentos de HTML ---------- */
const hero = (title, text, extra = '') => `<div class="hero"><div><h1>${title}</h1><p>${text}</p></div>${extra}</div>`;
const panelHead = (title, extra = '') => `<div class="panel-head"><h2>${title}</h2>${extra}</div>`;
const panel = (inner, head = '') => `<div class="panel">${head}${inner}</div>`;
const emptyState = text => `<p class="empty">${text}</p>`;
const stat = (label, value, ico) => `<div class="stat"><div><span>${label}</span><b>${value}</b></div>${icon(ico)}</div>`;
const tableHtml = (headers, rowsHtml) => `<div class="table-wrap"><table><thead><tr>${headers.map(h => `<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rowsHtml}</tbody></table></div>`;
/** Panel con un formulario en línea; `fields` son <label> y la validación del cliente usa `novalidate`. */
const formPanel = (id, fields, submitText, attrs = '') => `<div class="form-panel"><form id="${id}" class="inline-form" novalidate ${attrs}>${fields}<button class="primary" type="submit">${submitText}</button></form></div>`;
const optionsHtml = (items, selected = '') => items.map(([value, label]) => `<option value="${esc(value)}" ${String(value) === String(selected) ? 'selected' : ''}>${esc(label)}</option>`).join('');

/* ---------- Modales (reemplazan a alert/confirm/prompt nativos) ---------- */
/** Abre un modal con formulario. Resuelve true si se guardó y false si se canceló. */
function openModal({ title, body, submitText = 'Guardar', onSubmit, danger = false }) {
  return new Promise(resolve => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `<form class="rating-modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle" novalidate><button type="button" class="modal-close" aria-label="Cerrar">×</button><h2 id="modalTitle">${title}</h2>${body}<div class="modal-actions"><button type="button" class="secondary" data-cancel>Cancelar</button><button class="${danger ? 'danger' : 'primary'}" type="submit">${submitText}</button></div></form>`;
    document.body.appendChild(backdrop);
    markRequired(backdrop);
    const form = backdrop.querySelector('form');
    const onKey = e => { if (e.key === 'Escape') close(false); };
    const close = result => { document.removeEventListener('keydown', onKey); backdrop.remove(); resolve(result); };
    document.addEventListener('keydown', onKey);
    backdrop.querySelector('.modal-close').addEventListener('click', () => close(false));
    form.querySelector('[data-cancel]').addEventListener('click', () => close(false));
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!validateForm(form)) return;
      const button = form.querySelector('[type="submit"]');
      button.disabled = true;
      try { await onSubmit?.(Object.fromEntries(new FormData(form)), form); close(true); }
      catch (error) { toast(error.message, 'error'); button.disabled = false; }
    });
    (form.querySelector('input:not([type="hidden"]),select,textarea') || form.querySelector('[type="submit"]')).focus();
  });
}
/** Confirmación con modal propio; resuelve true/false. */
const confirmDialog = ({ title = 'Confirmar acción', message, confirmText = 'Confirmar', danger = true }) =>
  openModal({ title, body: `<p class="modal-text">${message}</p>`, submitText: confirmText, danger });

/* ---------- Tablas/listas con búsqueda, filtros y paginación ---------- */
const collections = {};

/** Ventana de páginas: 1 … 4 5 6 … 12. */
function pageWindow(page, pages) {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const set = new Set([1, pages, page - 1, page, page + 1]);
  const list = [...set].filter(n => n >= 1 && n <= pages).sort((a, b) => a - b);
  return list.flatMap((n, i) => (i && n - list[i - 1] > 1 ? ['…', n] : [n]));
}
/** Controles de paginación; `attr` es el atributo data que lleva el número de página. */
function pagerHtml({ page, pages, total, size }, attr) {
  if (!total) return '';
  const from = (page - 1) * size + 1, to = Math.min(total, page * size);
  const buttons = pages <= 1 ? '' : `<div class="pager-buttons"><button type="button" class="secondary small-btn" ${attr}="${page - 1}" ${page <= 1 ? 'disabled' : ''}>Anterior</button>${pageWindow(page, pages).map(n => n === '…' ? '<span class="gap" aria-hidden="true">…</span>' : `<button type="button" class="${n === page ? 'primary' : 'secondary'} small-btn" ${attr}="${n}" ${n === page ? 'aria-current="page"' : ''}>${n}</button>`).join('')}<button type="button" class="secondary small-btn" ${attr}="${page + 1}" ${page >= pages ? 'disabled' : ''}>Siguiente</button></div>`;
  return `<small>Mostrando ${from}–${to} de ${total}</small>${buttons}`;
}
/**
 * Registra una colección y devuelve su contenedor HTML (se rellena en mountCollections).
 * opts: { search(row)->texto, filters:[{key,label,get(row),format?,options?}], pageSize, renderBody(filas)->html, placeholder, empty }
 */
function collection(id, rows, opts) {
  const filters = (opts.filters || []).map(f => ({
    ...f,
    options: f.options || [...new Set(rows.map(f.get))].filter(v => v !== '' && v != null).sort().map(v => [String(v), f.format ? f.format(v) : v])
  }));
  collections[id] = { rows, opts: { pageSize: 8, ...opts, filters }, q: '', filters: {}, page: 1 };
  const filterHtml = filters.map(f => `<label class="filter"><span class="sr-only">${f.label}</span><select data-coll-filter="${f.key}" aria-label="${f.label}"><option value="">${f.label}: todos</option>${optionsHtml(f.options)}</select></label>`).join('');
  const placeholder = esc(opts.placeholder || 'Buscar…');
  return `<div class="collection" data-collection="${id}"><div class="toolbar"><div class="search-box">${icon('search')}<input type="search" data-coll-q placeholder="${placeholder}" aria-label="${placeholder}"></div>${filterHtml}<span class="count" data-coll-count aria-live="polite"></span></div><div data-coll-body></div><nav class="pager" data-coll-pager aria-label="Paginación"></nav></div>`;
}
function visibleRows(c) {
  const query = plain(c.q).trim();
  return c.rows.filter(row => (!query || plain(c.opts.search(row)).includes(query)) &&
    c.opts.filters.every(f => !c.filters[f.key] || String(f.get(row)) === c.filters[f.key]));
}
/** Redibuja solo el cuerpo y el paginador (la barra de búsqueda conserva el foco). */
function refreshCollection(id) {
  const c = collections[id], el = document.querySelector(`[data-collection="${id}"]`);
  if (!c || !el) return;
  const rows = visibleRows(c), size = c.opts.pageSize, pages = Math.max(1, Math.ceil(rows.length / size));
  c.page = Math.min(Math.max(1, c.page), pages);
  const slice = rows.slice((c.page - 1) * size, c.page * size);
  el.querySelector('[data-coll-body]').innerHTML = slice.length ? c.opts.renderBody(slice) : emptyState(c.rows.length ? 'No hay resultados para tu búsqueda o filtros.' : (c.opts.empty || 'No hay registros.'));
  el.querySelector('[data-coll-count]').textContent = `${rows.length} ${rows.length === 1 ? 'registro' : 'registros'}`;
  el.querySelector('[data-coll-pager]').innerHTML = pagerHtml({ page: c.page, pages, total: rows.length, size }, 'data-coll-page');
}
const mountCollections = () => document.querySelectorAll('[data-collection]').forEach(el => refreshCollection(el.dataset.collection));

/* ---------- Validación de formularios en el cliente ---------- */
/** Marca con un asterisco rojo (*) cada campo obligatorio y agrega la leyenda del formulario. */
function markRequired(root = document) {
  root.querySelectorAll('label').forEach(label => {
    const field = label.querySelector('input,select,textarea');
    if (!field || !field.required || label.querySelector('.required-mark')) return;
    const textNode = [...label.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
    const span = document.createElement('span');
    span.className = 'label-text';
    if (textNode) { span.textContent = textNode.textContent.trim(); label.replaceChild(span, textNode); } else label.prepend(span);
    span.insertAdjacentHTML('beforeend', ' <b class="required-mark" aria-hidden="true" title="Campo obligatorio">*</b>');
  });
  root.querySelectorAll('form').forEach(form => {
    if (form.querySelector('[required]') && !form.querySelector('.required-note'))
      form.insertAdjacentHTML('afterbegin', '<p class="required-note">Los campos marcados con <b class="required-mark">*</b> son obligatorios.</p>');
  });
}
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const MAX_FILE_BYTES = 5 * 1024 * 1024;
/** Devuelve el mensaje de error de un campo o '' si es válido. */
function fieldMessage(field, form) {
  const value = (field.value || '').trim();
  if (field.type === 'file') {
    const file = field.files?.[0];
    if (field.required && !file) return 'Selecciona un archivo.';
    if (file && file.size > MAX_FILE_BYTES) return 'El archivo supera el límite de 5 MB.';
    const allowed = (field.accept || '').split(',').map(x => x.trim().toLowerCase()).filter(Boolean);
    if (file && allowed.length && !allowed.some(ext => file.name.toLowerCase().endsWith(ext))) return `Formato no permitido. Usa: ${allowed.join(', ')}.`;
    return '';
  }
  if (field.required && !value) return 'Este campo es obligatorio.';
  if (!value) return '';
  if (field.type === 'email' && !EMAIL_RE.test(value)) return 'Ingresa un correo válido, por ejemplo nombre@ucc.edu.co.';
  if (field.minLength > 0 && value.length < field.minLength) return `Debe tener al menos ${field.minLength} caracteres.`;
  if (field.type === 'number') {
    const n = Number(value);
    if (Number.isNaN(n) || (field.min !== '' && n < Number(field.min)) || (field.max !== '' && n > Number(field.max))) return `Ingresa un número entre ${field.min} y ${field.max}.`;
  }
  if (field.dataset.after) {
    const other = form.elements[field.dataset.after];
    if (other?.value && value <= other.value) return 'La hora final debe ser posterior a la inicial.';
  }
  return '';
}
function clearFieldError(field) {
  field.removeAttribute?.('aria-invalid');
  field.closest?.('label')?.querySelector('.field-error')?.remove();
}
/** Valida todo el formulario; muestra errores bajo cada campo y un aviso general. */
function validateForm(form) {
  form.querySelectorAll('.field-error').forEach(el => el.remove());
  let first = null;
  form.querySelectorAll('input,select,textarea').forEach(field => {
    if (field.type === 'hidden' || field.disabled) return;
    const message = fieldMessage(field, form);
    if (!message) return clearFieldError(field);
    field.setAttribute('aria-invalid', 'true');
    (field.closest('label') || field.parentElement).insertAdjacentHTML('beforeend', `<small class="field-error" role="alert">${esc(message)}</small>`);
    first = first || field;
  });
  if (first) { first.focus(); toast('Revisa los campos marcados en rojo.', 'error'); return false; }
  return true;
}
