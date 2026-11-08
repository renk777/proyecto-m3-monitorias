/* Vistas del administrador: usuarios, asignaturas, periodos y catálogos (CRUD completo). */
'use strict';

const roleOptions = selected => optionsHtml(ROLE_LIST.map(r => [r, ROLE_NAMES[r]]), selected);
const teacherOptions = selected => optionsHtml((state.data.teachers || []).map(t => [t.id, t.name]), selected);

async function usersView() {
  const rows = await api('/api/admin/users');
  const form = formPanel('userForm',
    `<label>Nombre completo<input name="name" required maxlength="80"></label>
     <label>Correo institucional<input name="email" type="email" required></label>
     <label>Rol<select name="role" required>${roleOptions('student')}</select></label>
     <label>Contraseña inicial<input name="password" type="password" minlength="8" ${isDemo() ? '' : 'required'} placeholder="${isDemo() ? 'Vacío = Demo1234!' : 'Mínimo 8 caracteres'}" autocomplete="new-password"></label>`, 'Crear usuario');
  const list = collection('users', rows, {
    placeholder: 'Buscar por nombre o correo',
    search: u => `${u.name} ${u.email} ${ROLE_NAMES[u.role]}`,
    filters: [{ key: 'role', label: 'Rol', get: u => u.role, format: v => ROLE_NAMES[v] }, { key: 'active', label: 'Estado', get: u => u.active, options: [['1', 'Activos'], ['0', 'Inactivos']] }],
    renderBody: items => `<div class="list">${items.map(u => `<div class="list-row"><div><b>${esc(u.name)}</b><small>${esc(u.email)} · ${ROLE_NAMES[u.role]} ${u.active ? '' : '<span class="tag red">Inactivo</span>'}</small></div><div><button type="button" class="secondary small-btn" data-action="editUser" data-id="${u.id}" data-name="${esc(u.name)}" data-email="${esc(u.email)}" data-role="${esc(u.role)}">Editar</button><button type="button" class="secondary small-btn" data-action="resetUser" data-id="${u.id}">Restablecer clave</button>${u.id === state.user.id ? '<span class="tag blue">Tu cuenta</span>' : `<button type="button" class="secondary small-btn" data-action="toggleUser" data-id="${u.id}" data-value="${u.active ? 0 : 1}" data-name="${esc(u.name)}">${u.active ? 'Desactivar' : 'Activar'}</button>`}</div></div>`).join('')}</div>`
  });
  return viewFrame('Usuarios y roles', 'Administra cuentas institucionales.', `${form}${panel(list)}`);
}

async function subjectsAdminView() {
  const [rows, users] = await Promise.all([api('/api/admin/subjects'), api('/api/admin/users')]);
  state.data.teachers = users.filter(u => u.role === 'teacher' && u.active);
  const form = formPanel('subjectForm',
    `<label>Código<input name="code" required maxlength="20"></label><label>Nombre de la asignatura<input name="name" required maxlength="80"></label><label>Profesor<select name="teacherId"><option value="">Sin profesor</option>${teacherOptions('')}</select></label>`, 'Crear asignatura');
  const list = collection('subjectsAdmin', rows, {
    placeholder: 'Buscar por código, nombre o profesor', empty: 'Aún no hay asignaturas.',
    search: r => `${r.code} ${r.name} ${r.teacher || ''}`,
    filters: [{ key: 'teacher', label: 'Profesor', get: r => r.teacher || 'Sin profesor' }],
    renderBody: items => `<div class="list">${items.map(r => `<div class="list-row"><div><b>${esc(r.code)} - ${esc(r.name)}</b><small>${esc(r.teacher || 'Sin profesor')}</small></div><div><button type="button" class="secondary small-btn" data-action="editSubject" data-id="${r.id}" data-code="${esc(r.code)}" data-name="${esc(r.name)}" data-teacher="${r.teacher_id || ''}">Editar</button><button type="button" class="secondary small-btn" data-action="deleteSubject" data-id="${r.id}" data-label="${esc(r.code)}">Eliminar</button></div></div>`).join('')}</div>`
  });
  return viewFrame('Asignaturas', 'Administra código, nombre y profesor.', `${form}${panel(list)}`);
}

async function periodsView() {
  const rows = await api('/api/periods');
  const form = formPanel('periodForm', '<label>Nombre del periodo<input name="name" placeholder="2027-1" required maxlength="20"></label>', 'Crear y activar');
  const list = `<div class="list">${rows.map(r => `<div class="list-row"><b>${esc(r.name)}</b><div><span class="tag ${r.active ? 'green' : 'orange'}">${r.active ? 'Activo' : 'Inactivo'}</span>${r.active ? '' : `<button type="button" class="secondary small-btn" data-action="activatePeriod" data-id="${r.id}">Activar</button><button type="button" class="secondary small-btn" data-action="deletePeriod" data-id="${r.id}" data-label="${esc(r.name)}">Eliminar</button>`}</div></div>`).join('') || emptyState('Aún no hay periodos.')}</div>`;
  return viewFrame('Periodos académicos', 'Crea y activa un único periodo.', `${form}${panel(list)}`);
}

async function catalogsView() {
  const rows = await api('/api/catalogs?all=1');
  const form = formPanel('catalogForm',
    `<label>Catálogo<select name="catalog" required>${optionsHtml(Object.entries(CATALOG_NAMES))}</select></label><label>Valor<input name="value" required maxlength="80"></label>`, 'Agregar opción');
  const list = collection('catalogs', rows, {
    placeholder: 'Buscar opción', pageSize: 10,
    search: r => `${CATALOG_NAMES[r.catalog]} ${r.value}`,
    filters: [{ key: 'catalog', label: 'Catálogo', get: r => r.catalog, format: v => CATALOG_NAMES[v] }, { key: 'active', label: 'Estado', get: r => r.active, options: [['1', 'Activas'], ['0', 'Inactivas']] }],
    renderBody: items => `<div class="list">${items.map(r => `<div class="list-row"><div><b>${esc(r.value)}</b><small>${CATALOG_NAMES[r.catalog]} ${r.active ? '' : '<span class="tag red">Inactiva</span>'}</small></div><button type="button" class="secondary small-btn" data-action="toggleCatalog" data-id="${r.id}" data-value="${r.active ? 0 : 1}">${r.active ? 'Desactivar' : 'Activar'}</button></div>`).join('')}</div>`
  });
  return viewFrame('Catálogos', 'Agrega y desactiva opciones configurables.', `${form}${panel(list)}`);
}
