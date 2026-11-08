/* Núcleo de la interfaz: estado global, llamadas a la API, formatos y textos en español.
   Todos los scripts comparten el ámbito global (se cargan en orden desde index.html). */
'use strict';

const app = document.getElementById('app');
const state = { user: null, view: 'dashboard', data: {}, risk: { page: 1, q: '', program: '', assigned: '' } };

/* ---------- Textos visibles (los valores internos de la BD están en inglés) ---------- */
const ROLE_NAMES = { student: 'Estudiante', monitor: 'Monitor', teacher: 'Profesor', coordinator: 'Coordinador', admin: 'Administrador' };
const ROLE_LIST = Object.keys(ROLE_NAMES);
const STATUS_NAMES = { pending: 'Pendiente', approved: 'Aprobado', rejected: 'Rechazado', confirmed: 'Confirmada', cancelled: 'Cancelada', open: 'Abierta', closed: 'Cerrada' };
const STATUS_COLORS = { pending: 'orange', approved: 'green', rejected: 'red', confirmed: 'green', cancelled: 'red', open: 'blue', closed: 'green' };
const CATALOG_NAMES = { alert_type: 'Tipo de alerta', action: 'Acción', survey_reason: 'Motivo de encuesta' };
const WEEKDAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];

/* ---------- Utilidades ---------- */
/** Escapa texto antes de insertarlo como HTML (previene XSS). */
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
/** Minúsculas y sin tildes, para búsquedas tolerantes ("calculo" encuentra "Cálculo"). */
const plain = value => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
const todayBogota = () => new Date().toLocaleDateString('en-CA', { timeZone: 'America/Bogota' });
const isDemo = () => window.DEMO_MODE === true;

/** "2026-11-09" -> "lun, 9 nov 2026" (sin desfase de zona horaria). */
function fmtDate(iso) {
  const [y, m, d] = String(iso || '').split('-').map(Number);
  if (!y) return esc(iso || '');
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('es-CO', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}
/** "2026-11" -> "noviembre de 2026". */
function fmtMonth(ym) {
  const [y, m] = String(ym || '').split('-').map(Number);
  return y ? new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString('es-CO', { month: 'long', year: 'numeric', timeZone: 'UTC' }) : esc(ym);
}
const fmtHours = n => `${Number(n || 0).toLocaleString('es-CO', { maximumFractionDigits: 1 })} h`;
const statusTag = status => `<span class="tag ${STATUS_COLORS[status] || 'blue'}">${esc(STATUS_NAMES[status] || status)}</span>`;

/* ---------- Avisos (toasts) ---------- */
let toastTimer;
/** Muestra un aviso visual temporal. type: 'success' | 'error' | 'info'. */
function toast(message, type = 'info') {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), type === 'error' ? 4200 : 2800);
}

/* ---------- Cliente de la API ---------- */
/** Llama a la API; lanza Error con un mensaje legible en español si algo falla. */
async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { credentials: 'same-origin', headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }, ...options });
  } catch {
    throw new Error('No se pudo conectar con el servidor. Verifica que esté en ejecución.');
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && state.user && !url.startsWith('/api/auth/login')) {
    state.user = null; state.view = 'dashboard'; state.data = {};
    setTimeout(showLogin, 0);
    throw new Error('Tu sesión expiró. Ingresa de nuevo.');
  }
  if (!response.ok) throw new Error(data.error || 'No se pudo completar la operación.');
  return data;
}
const post = (url, body) => api(url, { method: 'POST', body: JSON.stringify(body ?? {}) });
const patch = (url, body) => api(url, { method: 'PATCH', body: JSON.stringify(body ?? {}) });
const del = url => api(url, { method: 'DELETE' });
