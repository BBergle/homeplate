import re
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from app import db
from app.main import app
from tests.test_invite import HH, INV, bodies

CSP = "default-src 'self'; img-src 'self'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
FORM = {"name": "Fran", "email": "fran@x.io", "note": "hi"}
SELF = ("GET", "/api/users/self")


def as_user(login_as, mock_mealie, uid="u1", **flags):
    login_as(uid)  # sets the token route
    mock_mealie[SELF] = httpx.Response(200, json={"id": uid, "fullName": uid, "admin": False, "groupId": "g-1", **flags})
    c = TestClient(app)  # sign in again so the stored is_admin follows the flags
    assert c.post("/login", data={"username": uid, "password": "pw"}, follow_redirects=False).status_code == 303
    return c


def rows(sql="SELECT * FROM requests"):
    con = db.connect()
    try:
        return [dict(r) for r in con.execute(sql)]
    finally:
        con.close()


def open_signups(c, on=True):
    r = c.post("/admin/signups", data={"open": "1" if on else "0"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"


def admin(login_as, mock_mealie, **kw):
    return as_user(login_as, mock_mealie, admin=True, **kw)


def submit(data=None):
    return TestClient(app).post("/request", data=data or FORM, follow_redirects=False)


def test_closed_by_default(mock_mealie):
    anon = TestClient(app)
    assert "Create account" not in anon.get("/login").text
    assert anon.get("/request").status_code == 404
    assert anon.post("/request", data=FORM).status_code == 404 and rows() == []


def test_admin_opens_signups(login_as, mock_mealie):
    c = admin(login_as, mock_mealie)
    open_signups(c)
    anon = TestClient(app)
    t = anon.get("/login").text
    assert re.search(r'<a class="btn btn-secondary" href="/request">Create account</a>', t)
    assert anon.get("/request").status_code == 200


def test_request_flow(login_as, mock_mealie):
    open_signups(admin(login_as, mock_mealie))
    anon = TestClient(app)
    form = anon.get("/request").text
    assert 'type="password"' not in form and 'name="password' not in form
    r = anon.post("/request", data=FORM | {"name": " Fran ", "email": " fran@x.io "}, follow_redirects=False)
    assert r.status_code == 303
    (row,) = rows()
    assert row["status"] == "pending" and row["name"] == "Fran" and row["email"] == "fran@x.io" and row["note"] == "hi"
    assert r.headers["location"] == f"/request/{row['secret']}" and len(row["secret"]) == 65
    page = anon.get(r.headers["location"])
    assert "Request sent" in page.text and "Fran" not in page.text and "fran@x.io" not in page.text


def test_request_validation(login_as, mock_mealie):
    open_signups(admin(login_as, mock_mealie))
    anon = TestClient(app)
    bad = [{"name": ""}, {"name": "   "}, {"name": "x" * 101}, {"email": "nope"}, {"email": "a" * 250 + "@x.io"}, {"note": "n" * 201}]
    for over in bad:
        r = anon.post("/request", data=FORM | over, follow_redirects=False)
        assert r.status_code == 200 and "msg-error" in r.text, over
    assert rows() == []


DECOY = r"^/request/[A-Za-z0-9_-]{65}$"


def test_request_limits(login_as, mock_mealie):
    open_signups(admin(login_as, mock_mealie))
    anon = TestClient(app)
    first = submit()
    real = anon.get(first.headers["location"])
    assert real.status_code == 200 and "Request sent" in real.text
    r = submit(FORM | {"email": " FRAN@x.io "})
    assert r.status_code == 303 and re.match(DECOY, r.headers["location"]) and len(rows()) == 1
    assert r.headers["location"] != first.headers["location"]
    page = anon.get(r.headers["location"])
    assert page.status_code == 200 and page.content == real.content
    for i in range(19):
        assert submit(FORM | {"email": f"p{i}@x.io"}).status_code == 303
    assert len(rows()) == 20
    r = submit(FORM | {"email": "late@x.io"})
    assert r.status_code == 303 and re.match(DECOY, r.headers["location"]) and len(rows()) == 20
    assert anon.get(r.headers["location"]).content == real.content


def test_bad_signature_is_404(login_as, mock_mealie, monkeypatch):
    open_signups(admin(login_as, mock_mealie))
    anon = TestClient(app)
    loc = submit(FORM | {"email": "FRAN@x.io"}).headers["location"]  # a decoy once a row exists
    submit()
    decoy = submit().headers["location"]
    assert anon.get(decoy).status_code == 200
    assert anon.get(decoy[:-1] + ("A" if decoy[-1] != "A" else "B")).status_code == 404
    monkeypatch.setenv("SECRET_KEY", "another")
    assert anon.get(decoy).status_code == 404
    assert anon.get("/request/sent").status_code == 404


def test_status_page_states(login_as, mock_mealie):
    open_signups(admin(login_as, mock_mealie))
    anon = TestClient(app)
    loc = submit().headers["location"]
    assert "Request sent. Keep this page: it will change when your request is answered." in anon.get(loc).text
    con = db.connect()
    con.execute("UPDATE requests SET status='approved', invite_token='tok1'")
    con.commit()
    t = anon.get(loc).text
    assert "You're approved" in t and 'class="btn btn-primary" href="/join/tok1"' in t
    con.execute("UPDATE requests SET status='declined', invite_token=NULL")
    con.commit()
    assert "This request wasn't approved." in anon.get(loc).text
    assert anon.get("/request/" + "x" * 43).status_code == 404


def test_non_admin_blocked(login_as, mock_mealie, monkeypatch):
    open_signups(admin(login_as, mock_mealie))
    submit()
    for flags in ({}, {"canInvite": True}):
        c = as_user(login_as, mock_mealie, "u2", **flags)  # only users/self is mocked: any other call raises
        calls = [c.get("/admin"), c.post("/admin/signups", data={"open": "0"}),
                 c.post("/admin/requests/1/approve", data={"where": "mine"}), c.post("/admin/requests/1/decline")]
        assert [r.status_code for r in calls] == [403] * 4
    assert rows()[0]["status"] == "pending"
    assert TestClient(app).get("/login").text.count("Create account") == 1  # still open


def test_admin_needs_session(mock_mealie):
    r = TestClient(app).get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_approve_creates_one_invite(login_as, mock_mealie, monkeypatch):
    c = admin(login_as, mock_mealie)
    open_signups(c)
    submit()
    mock_mealie[INV] = httpx.Response(201, json={"token": "inv1"})
    seen = bodies(mock_mealie, monkeypatch)
    r = c.post("/admin/requests/1/approve", data={"where": "mine"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    (row,) = rows()
    assert row["status"] == "approved" and row["invite_token"] == "inv1" and row["decided_at"] and row["decided_by"] == "u1"
    assert seen[INV] == [{"uses": 1}]
    page = c.get("/admin").text
    assert re.search(r'<input[^>]*readonly[^>]*value="[^"]*/join/inv1"', page)
    del mock_mealie[INV]  # a second approve must not call Mealie (it would raise)
    assert c.post("/admin/requests/1/approve", data={"where": "mine"}, follow_redirects=False).status_code == 303
    assert rows()[0]["invite_token"] == "inv1"


def test_approve_new_household(login_as, mock_mealie, monkeypatch):
    c = admin(login_as, mock_mealie)
    open_signups(c)
    submit()
    mock_mealie[HH] = httpx.Response(201, json={"id": "hh-1"})
    mock_mealie[INV] = httpx.Response(201, json={"token": "inv1"})
    seen = bodies(mock_mealie, monkeypatch)
    c.post("/admin/requests/1/approve", data={"where": "new", "household_name": " Smiths "})
    assert seen[HH] == [{"name": "Smiths", "groupId": "g-1"}] and seen[INV] == [{"uses": 1, "householdId": "hh-1"}]
    assert rows()[0]["status"] == "approved"


def test_approve_new_household_needs_name(login_as, mock_mealie):
    c = admin(login_as, mock_mealie)
    open_signups(c)
    submit()
    for name in ("", "  ", "x" * 51):
        r = c.post("/admin/requests/1/approve", data={"where": "new", "household_name": name}, follow_redirects=False)
        assert r.status_code == 200 and "msg-error" in r.text
    assert rows()[0]["status"] == "pending"


def test_approve_mealie_down(login_as, mock_mealie):
    c = admin(login_as, mock_mealie)
    open_signups(c)
    submit()
    mock_mealie[INV] = httpx.ConnectError("down")
    r = TestClient(app, raise_server_exceptions=False, cookies=c.cookies).post("/admin/requests/1/approve", data={"where": "mine"})
    assert r.status_code == 502 and "Can't reach Mealie" in r.text
    (row,) = rows()
    assert row["status"] == "pending" and row["invite_token"] is None and row["decided_at"] is None and row["decided_by"] is None
    mock_mealie[INV] = httpx.Response(201, json={"token": "inv2"})  # and it can be approved again
    c.post("/admin/requests/1/approve", data={"where": "mine"})
    assert rows()[0]["invite_token"] == "inv2"


def test_decline(login_as, mock_mealie):
    c = admin(login_as, mock_mealie)
    open_signups(c)
    submit()
    r = c.post("/admin/requests/1/decline", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    row = rows()[0]
    assert row["status"] == "declined" and row["decided_by"] == "u1"
    c.post("/admin/requests/1/approve", data={"where": "mine"})  # INV not mocked: a call would raise
    assert rows()[0]["status"] == "declined"
    assert c.post("/admin/requests/99/decline").status_code == 404
    assert c.post("/admin/requests/99/approve", data={"where": "mine"}).status_code == 404


def test_admin_page_escapes_and_empty_states(login_as, mock_mealie):
    c = admin(login_as, mock_mealie)
    t = c.get("/admin").text
    assert "Account requests" in t and "Recent" in t and "Turn on" in t and ">Off<" in t.replace(" ", "")
    open_signups(c)
    submit(FORM | {"name": "<b>Bo</b>", "note": "<script>x</script>"})
    t = c.get("/admin").text
    assert "&lt;b&gt;Bo&lt;/b&gt;" in t and "<script>x" not in t and "Turn off" in t and "btn-danger" in t


def test_closing_keeps_pending(login_as, mock_mealie):
    c = admin(login_as, mock_mealie)
    open_signups(c)
    submit()
    open_signups(c, False)
    assert len(rows()) == 1 and TestClient(app).get("/request").status_code == 404
    assert submit().status_code == 404


def test_public_headers_on_request(login_as, mock_mealie):
    open_signups(admin(login_as, mock_mealie))
    anon = TestClient(app)
    loc = submit().headers["location"]
    for r in (anon.get("/request"), anon.post("/request", data=FORM | {"name": ""}), anon.get(loc)):
        assert r.headers["referrer-policy"] == "same-origin" and r.headers["x-robots-tag"] == "noindex"
        assert r.headers["content-security-policy"] == CSP
    assert "x-robots-tag" not in anon.get("/requestx").headers


def test_me_admin_link(login_as, mock_mealie):
    a = admin(login_as, mock_mealie)
    assert 'href="/admin"' in a.get("/me").text and "Admin · " not in a.get("/me").text
    open_signups(a)
    submit()
    assert "Admin · 1 request<" in a.get("/me").text
    submit(FORM | {"email": "b@x.io"})
    assert "Admin · 2 requests<" in a.get("/me").text
    p = as_user(login_as, mock_mealie, "u2")
    assert 'href="/admin"' not in p.get("/me").text


def test_is_admin_migration(data_dir):
    con = sqlite3.connect(data_dir / "homeplate.db")
    con.execute("CREATE TABLE users (mealie_user_id TEXT PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    con = db.connect()
    assert "is_admin" in [r["name"] for r in con.execute("PRAGMA table_info(users)")]


def test_orphaned_approval_resets_on_admin_load(login_as, mock_mealie):
    c = admin(login_as, mock_mealie)
    open_signups(c)
    submit()
    submit(FORM | {"email": "b@x.io"})
    con = db.connect()
    con.execute("UPDATE requests SET status='approved', decided_by='u1', decided_at=? WHERE id=1",
                ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),))
    con.execute("UPDATE requests SET status='approved', decided_by='u1', decided_at=? WHERE id=2",
                (datetime.now(timezone.utc).isoformat(),))
    con.commit()
    loc = "/request/" + rows()[0]["secret"]
    assert "Request sent" in TestClient(app).get(loc).text  # approved without a token reads as pending
    c.get("/admin")
    got = {r["id"]: r for r in rows()}
    assert got[1]["status"] == "pending" and got[1]["decided_at"] is None and got[1]["decided_by"] is None
    assert got[2]["status"] == "approved"


def test_admin_dates_in_local_time(login_as, mock_mealie, monkeypatch):
    monkeypatch.setenv("TZ", "America/Indiana/Indianapolis")
    c = admin(login_as, mock_mealie)
    open_signups(c)
    submit()
    con = db.connect()
    con.execute("UPDATE requests SET created_at='2026-11-10T02:00:00+00:00'")
    con.commit()
    t = c.get("/admin").text
    assert "9 Nov" in t and "10 Nov" not in t
