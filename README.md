# Monitorias academicas UCC

Aplicacion web full stack para gestionar monitorias, reservas, asistencia y acompanamiento de estudiantes en riesgo. El backend usa Python y Flask, el frontend usa HTML5, CSS3 y JavaScript, y la persistencia se realiza en SQLite.

## Tecnologias

- Python 3.10 o superior
- Flask
- SQLite
- HTML5, CSS3 y JavaScript con Fetch API
- Bootstrap 5.3.3 servido localmente
- PyJWT para la sesion en cookie httpOnly
- OpenPyXL para exportar reportes
- tzdata para las zonas horarias en Windows

## Instalacion

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env` y reemplaza `JWT_SECRET` por una cadena aleatoria de al menos 32 caracteres. El texto de plantilla no permite iniciar el servidor. En desarrollo local conserva `COOKIE_SECURE=false`.

Carga los datos demo y ejecuta:

```powershell
python seed.py
python app.py
```

Abre <http://127.0.0.1:3000>.

## Usuarios demo

La contrasena de todos es `Demo1234!`.

| Correo | Rol |
|---|---|
| maria.perez@ucc.edu.co | Estudiante |
| laura.gomez@ucc.edu.co | Monitor |
| andres.ruiz@ucc.edu.co | Profesor |
| camila.torres@ucc.edu.co | Coordinador |
| admin@ucc.edu.co | Administrador |

## Funcionalidades

- Login, cierre de sesion, cambio de contrasena y permisos por rol.
- CRUD de usuarios, asignaturas, periodos y catalogos.
- Asignacion de monitores, disponibilidad semanal y sesiones recurrentes.
- Las sesiones se generan para cuatro semanas usando la zona horaria America/Bogota y se sincronizan de forma idempotente al iniciar.
- Reservas reactivables, cancelacion futura, asistencia, cierre y horas.
- Alertas tempranas, importacion CSV/XLSX con vista previa y reparto balanceado.
- Seguimientos con evidencias, encuestas, filtros, paginacion y exportacion ZIP.
- Dashboard por rol e indicadores de participacion, asistencia, satisfaccion y horas.
- Validacion visual de campos obligatorios con `***`, toasts, modal de edicion y mensajes de error.
- Filtros, paginacion, grafico de participacion, transiciones y animaciones respetando `prefers-reduced-motion`.

## Pruebas y limpieza

```powershell
python -m py_compile app.py seed.py reset.py
python -m pytest
python reset.py
python seed.py
```

La base se guarda en `data/`, las evidencias en `uploads/` y no se debe subir `.env`.
