"""Arranque demo: datos de ejemplo en una base vacía y servidor WSGI."""
import os
import secrets
import sqlite3


def prepare():
    demo = os.getenv("DEMO_MODE", "").lower() == "true"
    if demo and not os.getenv("JWT_SECRET"):
        os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
    from monitorias import create_app
    app = create_app()
    with sqlite3.connect(app.config["DB_PATH"]) as db:
        empty = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    if demo and empty:
        from seed import seed
        seed()
    return app


if __name__ == "__main__":
    prepare()
    port = str(int(os.getenv("PORT", "8080")))
    os.execvp("gunicorn", ["gunicorn", "--bind", "0.0.0.0:" + port,
                         "--workers", "1", "--threads", "4", "--timeout", "120",
                         "--access-logfile", "-", "app:app"])
