import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.main import app
from tests.test_access import as_user, open_signups, submit


def marked(html: str) -> list[str]:
    nav = re.search(r'<nav class="tabs".*?</nav>', html, re.S).group(0)
    return re.findall(r'<a href="([^"]*)" aria-current="page"', nav)


def test_home_is_the_chat(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ask"


def test_signed_out_goes_to_login(mock_mealie):
    c = TestClient(app)
    for path in ("/ask", "/settings"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login", path


@pytest.mark.parametrize("path", ["/me", "/order", "/r/x", "/weight", "/recipes/search", "/photos/1"])
def test_removed_pages_are_404(client, path):
    assert client.get(path).status_code == 404


def test_tab_bar_has_two_tabs(client, mock_mealie):
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(200, json={"id": "u1", "fullName": "U", "admin": True})
    for path, tab in (("/ask", "/ask"), ("/settings", "/settings"), ("/invite", "/settings"), ("/admin", "/settings")):
        html = client.get(path).text
        nav = re.search(r'<nav class="tabs".*?</nav>', html, re.S).group(0)
        assert re.findall(r'<a href="([^"]*)"', nav) == ["/ask", "/settings"], path
        assert "Ask</span>" in nav and "Settings</span>" in nav
        assert marked(html) == [tab], path


def test_settings_page(client, mock_mealie):
    html = client.get("/settings").text
    assert "<h1>Settings</h1>" in html and '<section class="card" id="ai">' in html and "<details" not in html
    assert 'name="key"' in html and 'action="/settings/ai"' in html
    assert 'href="/invite"' in html and 'action="/logout"' in html and "Sign out" in html
    assert 'href="/admin"' not in html


def test_settings_admin_button_with_pending_count(login_as, mock_mealie):
    a = as_user(login_as, mock_mealie, admin=True)
    assert 'href="/admin"' in a.get("/settings").text and "Admin · " not in a.get("/settings").text
    open_signups(a)
    submit()
    assert "Admin · 1 request<" in a.get("/settings").text


def test_sign_in_lands_on_chat_and_ignores_next(mock_mealie, login_as):
    login_as("u1")
    mock_mealie[("POST", "/api/auth/token")] = httpx.Response(200, json={"access_token": "t"})
    c = TestClient(app)
    r = c.post("/login", data={"username": "u1", "password": "pw", "next": "/r/some-recipe"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert c.get("/", follow_redirects=False).headers["location"] == "/ask"
    assert c.get("/ask").status_code == 200
    assert 'name="next"' not in TestClient(app).get("/login?next=/r/x").text


def test_signed_out_get_does_not_carry_next(mock_mealie):
    r = TestClient(app).get("/ask", follow_redirects=False)
    assert r.headers["location"] == "/login"


def test_old_database_is_left_alone(login_as):
    con = db.connect()
    con.execute("INSERT INTO users (mealie_user_id, name) VALUES ('u1', 'User u1')")
    con.execute("INSERT INTO entries (user_id, day, created_at, kind, description, calories) VALUES ('u1', '2026-01-01', 'x', 'other', 'toast', 200)")
    con.execute("INSERT INTO weights (user_id, date, lbs) VALUES ('u1', '2026-01-01', 180.5)")
    con.execute("INSERT INTO workouts (user_id, day, activity, minutes, intensity, calories, source, created_at) VALUES ('u1', '2026-01-01', 'run', 30, 'easy', 300, 'entered', 'x')")
    con.execute("INSERT INTO photos (user_id, path, created_at) VALUES ('u1', 'p.jpg', 'x')")
    con.commit()
    con.close()
    c = login_as("u1")
    assert c.get("/", follow_redirects=True).status_code == 200 and c.get("/settings").status_code == 200
    con = db.connect()
    got = [con.execute(q).fetchone()[0] for q in (
        "SELECT description FROM entries", "SELECT lbs FROM weights", "SELECT activity FROM workouts", "SELECT path FROM photos")]
    assert got == ["toast", 180.5, "run", "p.jpg"]
    con.close()


def test_local_helpers(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert str(auth.local_tz()) == "Asia/Tokyo"
    assert auth.local_today().isoformat() == auth._now().astimezone(auth.local_tz()).date().isoformat()
