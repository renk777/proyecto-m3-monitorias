# Guia de puesta en ejecucion

## 1. Preparar Python

Instala Python 3.10 o superior y abre PowerShell dentro de la carpeta que contiene `app.py`.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

La dependencia `tzdata` es necesaria en Windows para que Python pueda usar la zona horaria `America/Bogota`. No la omitas al instalar los requisitos.

## 2. Crear y configurar `.env`

Copia la plantilla y edita el archivo creado:

```powershell
Copy-Item .env.example .env
notepad .env
```

El archivo debe llamarse exactamente `.env` y estar junto a `app.py`. Reemplaza el valor de `JWT_SECRET` por una clave propia de 32 caracteres o mas, sin espacios ni comillas. No dejes el texto de plantilla, no uses el nombre `.env.txt` y no ejecutes la aplicacion con `.env.example`.

Para trabajar en `http://127.0.0.1:3000`, deja:

```env
COOKIE_SECURE=false
```

Solo usa `COOKIE_SECURE=true` cuando el sitio este publicado con HTTPS; de lo contrario la cookie no viajara y el login parecera fallar.

## 3. Cargar datos demo

```powershell
python seed.py
```

## 4. Iniciar el sistema

```powershell
python app.py
```

Visita <http://127.0.0.1:3000>. Para detenerlo presiona `Ctrl+C`.
Al iniciar, el sistema completa automaticamente las sesiones de las proximas cuatro semanas sin duplicarlas.

## 5. Usuarios demo

Todos usan `Demo1234!`:

| Correo | Rol |
|---|---|
| maria.perez@ucc.edu.co | Estudiante |
| laura.gomez@ucc.edu.co | Monitor |
| andres.ruiz@ucc.edu.co | Profesor |
| camila.torres@ucc.edu.co | Coordinador |
| admin@ucc.edu.co | Administrador |

## 6. Reiniciar datos

Deten el servidor y ejecuta:

```powershell
python reset.py
python seed.py
```

## 7. Validar antes de entregar

```powershell
python -m py_compile app.py seed.py reset.py
python -m pytest
```

La aplicacion crea `data/` y `uploads/` automaticamente. No compartas `.env`, la base local ni las evidencias reales.

La interfaz carga Bootstrap 5.3.3 desde `public/vendor/`, sin depender de CDN. Tambien incluye animaciones suaves, soporte para `prefers-reduced-motion` y consumo dinamico de la API mediante Fetch.
