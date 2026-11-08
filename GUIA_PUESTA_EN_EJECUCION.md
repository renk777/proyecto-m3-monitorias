# Guía de puesta en ejecución

## 1. Preparar Python
Instala Python 3.10 o superior y abre PowerShell dentro de la carpeta que contiene `app.py`.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```
`tzdata` es necesaria en Windows para la zona horaria `America/Bogota`; no la omitas.

## 2. Crear y configurar `.env`
```powershell
Copy-Item .env.example .env
notepad .env
```
El archivo debe llamarse exactamente `.env` y estar junto a `app.py`. Reemplaza `JWT_SECRET` por una clave propia de 32 caracteres o más, sin espacios ni comillas. Para trabajar en `http://127.0.0.1:3000` deja `COOKIE_SECURE=false`. Deja `DEMO_MODE=true` mientras pruebas o presentas (desactiva las reglas de fecha); pon `false` para usar las reglas reales.

## 3. Cargar datos de demostración e iniciar
```powershell
python seed.py
python app.py
```
Visita <http://127.0.0.1:3000>. Para detenerlo presiona `Ctrl+C`. Si ya tenías datos de una versión anterior, ejecuta antes `python reset.py` (con el servidor detenido).

## 4. Guion sugerido para la sustentación (10 minutos)
**Parte 1 · Diapositivas (máx. 3 min):** problema, objetivos y arquitectura (usa los diagramas del README: arquitectura MVC y modelo relacional).

**Parte 2 · Demostración en vivo (máx. 7 min):**
1. *Estudiante* (María): buscar monitorías, usar búsqueda y filtros, reservar.
2. *Monitor* (Laura): publicar un bloque con una hora inválida (se ve la validación), corregirlo, marcar asistencia y cerrar la sesión.
3. *Estudiante*: calificar la sesión.
4. *Profesor* (Andrés): aprobar el reporte de horas y registrar una alerta temprana.
5. *Coordinador* (Camila): paginación de 30 estudiantes, búsqueda, repartir entre monitores, registrar una encuesta.
6. *Administrador*: crear, editar y desactivar un usuario (persistencia: registrar, modificar y eliminar en vivo).
Menciona el diseño responsive (reduce la ventana) y que la información viene de la base de datos.

## 5. Validar antes de entregar
```powershell
python -m pyflakes monitorias app.py seed.py reset.py
python -m pytest
```
No compartas `.env`, la base local ni evidencias reales.
