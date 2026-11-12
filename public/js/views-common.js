/* Vistas comunes: inicio de sesión, estructura de la página (menú, encabezado), resumen y cambio de contraseña. */
'use strict';

/* Menú por rol: [id de la vista, texto, icono] */
const NAV = {
  student: [['dashboard', 'Resumen', 'grid'], ['subjects', 'Buscar monitorías', 'search'], ['bookings', 'Mis reservas', 'calendar']],
  monitor: [['dashboard', 'Resumen', 'grid'], ['availability', 'Disponibilidad', 'calendar'], ['attendance', 'Asistencia', 'check'], ['hours', 'Mis horas', 'chart'], ['risk', 'Mis estudiantes', 'search'], ['followups', 'Seguimientos', 'check']],
  teacher: [['dashboard', 'Resumen', 'grid'], ['assignments', 'Asignaciones', 'check'], ['reports', 'Reportes de horas', 'calendar'], ['analytics', 'Indicadores', 'chart'], ['alerts', 'Alertas tempranas', 'search']],
  coordinator: [['dashboard', 'Resumen', 'grid'], ['imports', 'Importar DARP', 'calendar'], ['risk', 'Repartir estudiantes', 'search'], ['followups', 'Seguimientos', 'check'], ['surveys', 'Encuestas', 'chart'], ['export', 'Reporte final', 'calendar']],
  admin: [['dashboard', 'Resumen', 'grid'], ['users', 'Usuarios y roles', 'check'], ['subjectsAdmin', 'Asignaturas', 'search'], ['periods', 'Periodos', 'calendar'], ['catalogs', 'Catálogos', 'chart'], ['analytics', 'Indicadores', 'chart']]
};

function showLogin() {
  app.innerHTML = `${ICONS}<main class="login-page"><section class="login-card animate-in"><img src="/logo_ucc.png" alt="Universidad Cooperativa de Colombia"><h1>Monitorías académicas</h1><p>Ingresa con tu cuenta institucional UCC.</p><form id="loginForm" novalidate><label>Correo institucional<input name="email" type="email" required autocomplete="username" placeholder="nombre@ucc.edu.co"></label><label>Contraseña<input name="password" type="password" required minlength="8" autocomplete="current-password"></label><button class="primary" type="submit">Ingresar</button>${isDemo() ? '<small>Modo de pruebas: la contraseña de las cuentas demo es Demo1234!</small>' : ''}</form><p class="privacy">Tratamiento de datos personales conforme a la Ley 1581 de 2012.</p></section></main>`;
  markRequired(app);
}

/** Estructura general: menú lateral, barra superior y el contenido de la vista. */
function shell(content) {
  const nav = [...NAV[state.user.role], ['password', 'Cambiar contraseña', 'check']];
  const current = nav.find(x => x[0] === state.view)?.[1] || 'Resumen';
  const unread = state.data.dashboard?.unread || 0;
  app.innerHTML = `${ICONS}<a class="skip-link" href="#main">Saltar al contenido</a><div class="app"><aside class="sidebar"><div class="brand"><img src="/logo_ucc.png" alt="Logo UCC"><div><strong>Monitorías académicas</strong><small>Universidad Cooperativa de Colombia</small></div></div><nav class="nav" aria-label="Menú principal">${nav.map(([id, label, ico]) => `<button type="button" class="${state.view === id ? 'active' : ''}" data-view="${id}" aria-label="${label}" title="${label}" ${state.view === id ? 'aria-current="page"' : ''}>${icon(ico)}<span>${label}</span>${id === 'dashboard' && unread ? `<b class="badge" title="Notificaciones sin leer">${unread}</b>` : ''}</button>`).join('')}</nav><div class="sidebar-foot">Periodo activo: ${esc(state.data.dashboard?.period?.name || 'sin periodo')}<br>${isDemo() ? 'Modo de pruebas' : 'Sesión institucional segura'}</div></aside><main class="main" id="main"><header class="topbar"><div class="crumb">Inicio / <b>${esc(current)}</b></div><div class="user"><span>${esc(state.user.name)} · ${ROLE_NAMES[state.user.role]}</span><button type="button" class="link-btn" data-action="logout">Cerrar sesión</button><span class="avatar" aria-hidden="true">${esc(state.user.name.split(' ').map(x => x[0]).slice(0, 2).join(''))}</span></div></header>${content}</main></div>`;
}
/** Encabezado + cuerpo estándar de una vista. */
const viewFrame = (title, text, body) => `<section class="content">${hero(title, text)}${body}</section>`;

async function dashboardView() {
  const data = await api('/api/dashboard');
  state.data.dashboard = data;
  const ownLabel = { student: 'Reservas activas', monitor: 'Sesiones por atender', teacher: 'Mis asignaturas', coordinator: 'Estudiantes sin monitor', admin: 'Usuarios activos' }[state.user.role];
  const notes = data.notifications.map(n => `<div class="list-row ${n.is_read ? '' : 'unread'}"><div><b>${esc(n.title)}</b><small>${esc(n.body)}</small></div><small>${esc(String(n.created_at).slice(0, 16))}</small></div>`).join('');
  return `<section class="content">${hero(`Bienvenido/a, ${esc(state.user.name)}`, 'Gestiona el acompañamiento académico con trazabilidad institucional.')}<div class="stats">${stat(ownLabel, data.counts.own, 'check')}${stat('Sesiones abiertas', data.counts.sessions, 'calendar')}${stat('Asistencia promedio', `${Math.round(data.counts.attendance)}%`, 'chart')}</div>${panel(`<div class="list">${notes || emptyState('No tienes notificaciones.')}</div>`, panelHead('Notificaciones', data.unread ? '<button type="button" class="secondary small-btn" data-action="readNotifications">Marcar como leídas</button>' : ''))}</section>`;
}

async function passwordView() {
  return viewFrame('Cambiar contraseña', 'Usa una contraseña de al menos 8 caracteres.', formPanel('passwordForm',
    '<label>Contraseña actual<input name="current" type="password" required autocomplete="current-password"></label><label>Nueva contraseña<input name="password" type="password" minlength="8" required autocomplete="new-password"></label>', 'Guardar contraseña'));
}
