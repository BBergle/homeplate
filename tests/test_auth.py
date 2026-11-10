import re

import httpx
from fastapi.testclient import TestClient

from app import db, mealie
from app.main import app


def test_login_ok(mock_mealie, login_as):
    c = login_as("u1")
    con = db.connect()
    assert con.execute("SELECT weekly_goal FROM users WHERE mealie_user_id='u1'").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    assert c.get("/ask", follow_redirects=False).status_code == 200


def test_login_bad(mock_mealie):
    mock_mealie[("POST", "/api/auth/token")] = httpx.Response(401)
    r = TestClient(app).post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Wrong username or password" in r.text


def test_login_locked(mock_mealie):
    mock_mealie[("POST", "/api/auth/token")] = httpx.Response(423)
    r = TestClient(app).post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Too many attempts. Try again later." in r.text
    assert "Wrong username or password" not in r.text


def test_requires_session(mock_mealie):
    r = TestClient(app).get("/ask", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_mealie_down(client, mock_mealie):
    mock_mealie[("GET", "/api/users/self")] = httpx.ConnectError("down")
    r = client.get("/invite")
    assert r.status_code == 502
    assert "Can't reach Mealie" in r.text


def test_token_expired(client, mock_mealie):
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(401)
    r = client.get("/invite", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert db.connect().execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_session_refreshed_after_a_day(client, mock_mealie):
    mock_mealie[("POST", "/api/auth/refresh")] = httpx.Response(200, json={"access_token": "new"})
    con = db.connect()
    con.execute("UPDATE sessions SET refreshed_at = '2000-01-01T00:00:00+00:00'")
    con.commit()
    assert client.get("/ask", follow_redirects=False).status_code == 200
    assert con.execute("SELECT mealie_token FROM sessions").fetchone()[0] == "new"


HX = {"HX-Request": "true"}


def test_htmx_mealie_down(client, mock_mealie):
    mock_mealie[("GET", "/api/users/self")] = httpx.ConnectError("down")
    r = client.get("/invite", headers=HX)
    assert r.status_code == 200 and "Can't reach Mealie" in r.text and "<html" not in r.text


def test_htmx_token_expired(client, mock_mealie):
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(401)
    r = client.get("/invite", headers=HX, follow_redirects=False)
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/login"
    con = db.connect()
    assert con.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    con.close()


def test_htmx_no_session(mock_mealie):
    r = TestClient(app).get("/ask/chat", headers=HX, follow_redirects=False)
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/login"


def sql(q, *args):
    con = db.connect()
    try:
        con.execute(q, args)
        con.commit()
    finally:
        con.close()


def count_sessions():
    con = db.connect()
    try:
        return con.execute("SELECT count(*) FROM sessions").fetchone()[0]
    finally:
        con.close()


def test_expired_session_redirects_and_is_deleted(client):
    sql("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    r = client.get("/ask", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert count_sessions() == 0


def _login_cookie(mock_mealie, login_as, monkeypatch, base_url):
    login_as("u1")  # sets up the Mealie mocks
    monkeypatch.setenv("BASE_URL", base_url)
    r = TestClient(app).post("/login", data={"username": "u1", "password": "pw"}, follow_redirects=False)
    return r.headers["set-cookie"].lower()


def test_cookie_attributes(mock_mealie, login_as, monkeypatch):
    c = _login_cookie(mock_mealie, login_as, monkeypatch, "https://home.example")
    assert "httponly" in c and "samesite=lax" in c and "secure" in c
    assert f"max-age={400 * 86400}" in c
    c = _login_cookie(mock_mealie, login_as, monkeypatch, "http://localhost:8000")
    assert "httponly" in c and "samesite=lax" in c and "secure" not in c


def test_logout(client):
    assert count_sessions() == 1
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert count_sessions() == 0
    assert 'sid=""' in r.headers["set-cookie"] or "max-age=0" in r.headers["set-cookie"].lower()


def test_mealie_5xx_is_cant_reach(client, mock_mealie):
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(503)
    r = client.get("/invite")
    assert r.status_code == 502 and "Can't reach Mealie" in r.text


def test_mealie_down_during_login(mock_mealie):
    mock_mealie[("POST", "/api/auth/token")] = httpx.ConnectError("down")
    r = TestClient(app, raise_server_exceptions=False).post(
        "/login", data={"username": "x", "password": "y"}, follow_redirects=False
    )
    assert r.status_code == 502 and "Can't reach Mealie" in r.text and "Traceback" not in r.text


def test_refresh_failing_keeps_session_when_mealie_down(client, mock_mealie):
    mock_mealie[("POST", "/api/auth/refresh")] = httpx.ConnectError("down")
    sql("UPDATE sessions SET refreshed_at = '2000-01-01T00:00:00+00:00'")
    assert client.get("/ask", follow_redirects=False).status_code == 200
    con = db.connect()
    try:
        row = con.execute("SELECT mealie_token, refreshed_at FROM sessions").fetchone()
    finally:
        con.close()
    assert tuple(row) == ("tok-u1", "2000-01-01T00:00:00+00:00")  # untouched, retried next request


def test_refresh_rejected_drops_session(client, mock_mealie):
    mock_mealie[("POST", "/api/auth/refresh")] = httpx.Response(401)
    sql("UPDATE sessions SET refreshed_at = '2000-01-01T00:00:00+00:00'")
    r = client.get("/ask", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert count_sessions() == 0


def test_every_route_requires_a_session(mock_mealie):
    c = TestClient(app)
    paths = 0

    def walk(routes):  # newer FastAPI wraps included routers
        for r in routes:
            if hasattr(r, "original_router"):
                yield from walk(r.original_router.routes)
            elif hasattr(r, "methods"):
                yield r

    for route in walk(app.routes):
        path = route.path
        if path in ("/login", "/healthz", "/request") or path.startswith(("/static", "/join/", "/request/")):
            continue
        method = "POST" if "POST" in route.methods else "GET"
        r = c.request(method, re.sub(r"\{[^}]+\}", "1", path), follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].split("?")[0] == "/login", (method, path, r.status_code)
        paths += 1
    assert paths >= 8


def _msgs():
    con = db.connect()
    try:
        return con.execute("SELECT * FROM chat_messages").fetchall()
    finally:
        con.close()


def _seed_chat():
    sql("INSERT INTO chat_messages (user_id, role, content, created_at) VALUES ('u1', 'user', 'hi', 'x')")


def post(client, origin=None):
    """POST /ask/new (clears the chat) over a seeded message: 303 and no messages when it ran, 403 and one when blocked."""
    _seed_chat()
    headers = {} if origin is None else {"Origin": origin}
    return client.post("/ask/new", headers=headers, follow_redirects=False)


def test_cross_origin_post_blocked(client):
    assert post(client, "https://evil.example").status_code == 403 and _msgs()


def test_same_origin_post_allowed(client):
    assert post(client, "http://TESTSERVER").status_code == 303 and not _msgs()


def test_post_without_origin_allowed(client):
    assert post(client).status_code == 303


def test_null_and_empty_origin_blocked(client):
    for origin in ("null", ""):
        assert post(client, origin).status_code == 403, origin
    assert _msgs()


def test_origin_port_mismatch_blocked(client):
    assert post(client, "http://testserver:9999").status_code == 403 and _msgs()


def test_base_url_origin_allowed(client, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://Home.example")
    assert post(client, "https://home.example").status_code == 303
    assert post(client, "https://evil.example").status_code == 403
