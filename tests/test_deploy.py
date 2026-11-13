import sqlite3

from railway_start import prepare


def test_demo_bootstrap_is_repeatable(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("JWT_SECRET", raising=False)
    app = prepare()
    client = app.test_client()
    assert client.get("/api/config").json == {"demoMode": True}
    response = client.post("/api/auth/login", json={"email": "admin@ucc.edu.co", "password": "Demo1234!"})
    assert response.status_code == 200
    assert "Secure" in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]
    prepare()
    with sqlite3.connect(app.config["DB_PATH"]) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 7
    assert len(app.config["JWT_SECRET"]) >= 32
