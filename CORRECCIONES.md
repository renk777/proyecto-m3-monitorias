# Registro de cambios

## Versión 3 · Adecuación a los lineamientos y la rúbrica
- **Arquitectura MVC:** el `app.py` monolítico pasó a un paquete `monitorias/` (fábrica de aplicación, blueprints por rol, modelo, servicios y configuración).
- **Frontend modular:** `public/app.js` se reemplazó por `public/js/` (núcleo, componentes, vistas por rol y arranque) con comentarios y delegación de eventos.
- **Modo de pruebas (`DEMO_MODE=true`):** todas las opciones de cada cuenta quedan disponibles sin importar la fecha.
- **Ortografía:** toda la interfaz, los mensajes del servidor, los datos demo y los encabezados de Excel se revisaron (tildes, roles y estados en español).
- **Campos obligatorios:** asterisco rojo `*` en todos los formularios (incluidos los modales) y leyenda explicativa.
- **Validación y feedback:** validación en cliente con mensajes bajo cada campo, toasts de éxito/error y modales de confirmación propios; errores del servidor siempre en JSON (sin Traceback).
- **Paginación y filtros:** búsqueda sin tildes, filtros y paginación en todos los listados; estudiantes en riesgo paginados en el servidor.
- **CRUD completo:** se agregó edición de disponibilidad y seguimientos, historial/eliminación de alertas y encuestas, reactivación de catálogos y periodos.
- **Notificaciones:** nuevas reservas, cancelaciones, reportes revisados, asignaciones y sesiones cerradas.
- **Base de datos:** restricciones `CHECK`, llaves foráneas faltantes e índices.
- **Error corregido:** los botones de asistencia del monitor enviaban un id inexistente y no marcaban nada.
- **Pruebas:** 28 pruebas de backend (`python -m pytest`).

## Versión 2 · Corrección de errores
Reportes de horas vacíos, días de la semana desfasados, rol que se pisaba al editar usuarios, "Seguimientos" roto, horas duplicadas, `seed.py` que dejaba el periodo inactivo, falsos 401, calificar dos veces, reasignación de monitores, CSV con `;`, validaciones de horarios y duplicados que respondían 500.
