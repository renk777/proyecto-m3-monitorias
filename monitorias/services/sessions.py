"""Generación de sesiones recurrentes a partir de la disponibilidad semanal."""
from datetime import timedelta

from ..utils import bogota_today

WEEKS_AHEAD = 4


def generate_sessions(connection, availability_id, weekday, capacity):
    """Crea (sin duplicar) las sesiones de las próximas semanas para un bloque."""
    today = bogota_today()
    first = today + timedelta(days=(weekday - today.weekday()) % 7)
    for week in range(WEEKS_AHEAD):
        session_date = first + timedelta(days=week * 7)
        connection.execute("INSERT OR IGNORE INTO sessions(availability_id,session_date,capacity) VALUES(?,?,?)",
                           (availability_id, session_date.isoformat(), capacity))


def generate_upcoming_sessions(connection):
    """Completa las sesiones de todos los bloques activos del periodo activo."""
    rows = connection.execute("""SELECT a.id,a.weekday,a.capacity FROM availability a
        JOIN monitor_assignments ma ON ma.id=a.assignment_id JOIN periods p ON p.id=ma.period_id
        WHERE a.active=1 AND ma.active=1 AND p.active=1""").fetchall()
    for row in rows:
        generate_sessions(connection, row["id"], row["weekday"], row["capacity"])
