import json

import httpx
from fastapi.testclient import TestClient

from app.main import app

INV = ("POST", "/api/households/invitations")
REG = ("POST", "/api/users/register")
HH = ("POST", "/api/admin/households")
FORM = {"name": "Fran", "email": "f@x.io", "username": "fran", "password": "hunter2hunter2", "password_confirm": "hunter2hunter2"}


def as_user(login_as, mock_mealie, **flags):
    c = login_as("u1")
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(200, json={"id": "u1", "fullName": "U", "admin": False, **flags})
    return c


def bodies(mock_mealie, monkeypatch):
    """Record JSON bodies of requests by (method, path)."""
    from app import mealie

    seen = {}
    orig = mealie.client._transport.handler

    def spy(request):
        if request.content:
            try:
                seen.setdefault((request.method, request.url.path), []).append(json.loads(request.content))
            except ValueError:
                pass
        return orig(request)

    monkeypatch.setattr(mealie.client._transport, "handler", spy)
    return seen


def test_admin_invites_to_own_household(login_as, mock_mealie, monkeypatch):
    c = as_user(login_as, mock_mealie, admin=True)
    mock_mealie[INV] = httpx.Response(201, json={"token": "abc123"})
    seen = bodies(mock_mealie, monkeypatch)
    r = c.post("/invite", data={"where": "mine"})
    assert r.status_code == 200 and "/join/abc123" in r.text
    assert seen[INV] == [{"uses": 1}]


def test_admin_invites_to_new_household(login_as, mock_mealie, monkeypatch):
    c = as_user(login_as, mock_mealie, admin=True)
    mock_mealie[HH] = httpx.Response(201, json={"id": "hh-1"})
    mock_mealie[INV] = httpx.Response(201, json={"token": "abc123"})
    seen = bodies(mock_mealie, monkeypatch)
    r = c.post("/invite", data={"where": "new", "household_name": "  Smiths "})
    assert r.status_code == 200 and "/join/abc123" in r.text
    assert seen[HH] == [{"name": "Smiths"}]
    assert seen[INV] == [{"uses": 1, "householdId": "hh-1"}]


def test_new_household_name_rules(login_as, mock_mealie):
    c = as_user(login_as, mock_mealie, admin=True)
    for name in ("", "   ", "x" * 51):
        r = c.post("/invite", data={"where": "new", "household_name": name})
        assert r.status_code == 200 and 'class="error"' in r.text and "/join/" not in r.text


def test_base_url_used_for_link(login_as, mock_mealie, monkeypatch):
    c = as_user(login_as, mock_mealie, admin=True)
    monkeypatch.setenv("BASE_URL", "https://home.example/")
    mock_mealie[INV] = httpx.Response(201, json={"token": "abc123"})
    assert 'href="https://home.example/join/abc123"' in c.post("/invite", data={"where": "mine"}).text


def test_can_invite_user_sees_no_household_option(login_as, mock_mealie):
    c = as_user(login_as, mock_mealie, canInvite=True)
    r = c.get("/invite")
    assert r.status_code == 200 and "My household" in r.text and "Their own household" not in r.text
    r = c.post("/invite", data={"where": "new", "household_name": "Smiths"})  # no HH route mocked: a call would raise
    assert r.status_code == 403
    mock_mealie[INV] = httpx.Response(201, json={"token": "abc123"})
    assert "/join/abc123" in c.post("/invite", data={"where": "mine"}).text


def test_admin_sees_household_option(login_as, mock_mealie):
    c = as_user(login_as, mock_mealie, admin=True)
    assert "Their own household" in c.get("/invite").text


def test_plain_user_cannot_invite(login_as, mock_mealie):
    c = as_user(login_as, mock_mealie)  # only users/self is mocked: any other call raises
    for r in (c.get("/invite"), c.post("/invite", data={"where": "mine"})):
        assert r.status_code == 403 and "Ask the person who runs this server to invite people." in r.text


def test_invite_needs_session(mock_mealie):
    r = TestClient(app).get("/invite", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_me_links_to_invite(client):
    assert 'href="/invite"' in client.get("/me").text


def join_mocks(mock_mealie):
    mock_mealie[REG] = httpx.Response(201, json={})
    mock_mealie[("POST", "/api/auth/token")] = httpx.Response(200, json={"access_token": "tok-new"})
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(200, json={"id": "new1", "fullName": "Fran", "admin": False})


def test_join_creates_account_and_signs_in(mock_mealie, monkeypatch):
    join_mocks(mock_mealie)
    seen = bodies(mock_mealie, monkeypatch)
    c = TestClient(app)
    r = c.post("/join/tok9", data=FORM, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/" and "sid" in c.cookies
    assert seen[REG] == [{
        "groupToken": "tok9", "email": "f@x.io", "username": "fran", "fullName": "Fran",
        "password": FORM["password"], "passwordConfirm": FORM["password"],
    }]
    assert c.get("/").status_code == 200


def test_join_password_rules(mock_mealie):
    c = TestClient(app)  # nothing mocked: any Mealie call raises
    bad = [
        {"password": "short", "password_confirm": "short"},
        {"password": "hunter2hunter2", "password_confirm": "different-pass"},
        {"name": ""}, {"name": "x" * 101}, {"email": "nope"}, {"username": ""}, {"username": "x" * 51},
    ]
    for over in bad:
        r = c.post("/join/tok9", data=FORM | over, follow_redirects=False)
        assert r.status_code == 200 and 'class="error"' in r.text and "sid" not in c.cookies
        assert "hunter2hunter2" not in r.text and "different-pass" not in r.text
        assert 'value="fran"' in r.text or over.get("username") is not None


def test_join_rejected_by_mealie(mock_mealie):
    mock_mealie[REG] = httpx.Response(400, json={"detail": "bad"})
    c = TestClient(app)
    r = c.post("/join/tok9", data=FORM, follow_redirects=False)
    assert r.status_code == 200 and "sid" not in c.cookies
    assert "Couldn&#39;t create the account. The invite may have been used, or the username or email is taken." in r.text
    assert FORM["password"] not in r.text
    assert 'value="fran"' in r.text and 'value="Fran"' in r.text and 'value="f@x.io"' in r.text


def test_join_mealie_down(mock_mealie):
    mock_mealie[REG] = httpx.ConnectError("down")
    r = TestClient(app, raise_server_exceptions=False).post("/join/tok9", data=FORM)
    assert r.status_code == 502 and "Traceback" not in r.text


def test_join_login_failure_goes_to_login(mock_mealie):
    mock_mealie[REG] = httpx.Response(201, json={})
    mock_mealie[("POST", "/api/auth/token")] = httpx.Response(401, json={})
    c = TestClient(app)
    r = c.post("/join/tok9", data=FORM, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login" and "sid" not in c.cookies


def test_join_is_public(mock_mealie):  # no Mealie call, no cookie
    r = TestClient(app).get("/join/tok9")
    assert r.status_code == 200
    for s in ('autocomplete="name"', 'autocomplete="email"', 'autocomplete="username"', 'autocomplete="new-password"', 'action="/join/tok9"'):
        assert s in r.text
    assert 'class="tabs"' not in r.text and 'name="robots"' in r.text
    assert r.headers["x-robots-tag"] == "noindex" and r.headers["referrer-policy"] == "no-referrer"


def test_join_post_carries_public_headers(mock_mealie):
    mock_mealie[REG] = httpx.Response(400, json={})
    r = TestClient(app).post("/join/tok9", data=FORM)
    assert r.headers["x-robots-tag"] == "noindex" and r.headers["referrer-policy"] == "no-referrer"
