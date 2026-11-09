import httpx
from fastapi.testclient import TestClient

from app import db, mealie
from app.main import app


def test_login_ok(mock_mealie, login_as):
    c = login_as("u1")
    con = db.connect()
    assert con.execute("SELECT weekly_goal FROM users WHERE mealie_user_id='u1'").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    assert c.get("/", follow_redirects=False).status_code == 200


def test_login_bad(mock_mealie):
    mock_mealie[("POST", "/api/auth/token")] = httpx.Response(401)
    r = TestClient(app).post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Wrong username or password" in r.text


def test_login_locked(mock_mealie):
    mock_mealie[("POST", "/api/auth/token")] = httpx.Response(423)
    r = TestClient(app).post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Wrong username or password" in r.text


def test_requires_session(mock_mealie):
    r = TestClient(app).get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_mealie_down(client, mock_mealie):
    mock_mealie[("GET", "/api/households/mealplans/today")] = httpx.ConnectError("down")
    r = client.get("/")
    assert r.status_code == 502
    assert "Can't reach Mealie" in r.text


def test_token_expired(client, mock_mealie):
    mock_mealie[("GET", "/api/households/mealplans/today")] = httpx.Response(401)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert db.connect().execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_session_refreshed_after_a_day(client, mock_mealie):
    mock_mealie[("POST", "/api/auth/refresh")] = httpx.Response(200, json={"access_token": "new"})
    con = db.connect()
    con.execute("UPDATE sessions SET refreshed_at = '2000-01-01T00:00:00+00:00'")
    con.commit()
    assert client.get("/", follow_redirects=False).status_code == 200
    assert con.execute("SELECT mealie_token FROM sessions").fetchone()[0] == "new"


def test_leading_number():
    assert mealie.leading_number(None) is None
    assert mealie.leading_number("") is None
    assert mealie.leading_number("about 300 kcal") == 300
    assert mealie.leading_number("312.5") == 312
