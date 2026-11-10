from datetime import date, datetime, timezone

from app import db, today
from app.me import sparkline


def seed(sql, *args):
    con = db.connect()
    con.execute(sql, args)
    con.commit()
    con.close()


def freeze(monkeypatch):
    monkeypatch.setattr(today, "_now", lambda: datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc))  # a Wednesday


def entry(kind, day="2026-11-10"):
    seed(
        "INSERT INTO entries (user_id, day, created_at, kind) VALUES ('u1', ?, 'x', ?)", day, kind
    )


def test_me_empty(client, monkeypatch):
    freeze(monkeypatch)
    r = client.get("/me")
    assert r.status_code == 200
    assert "0 of 3" in r.text and "Streak: 0 weeks" in r.text


def test_me_counts(client, monkeypatch):
    freeze(monkeypatch)
    for _ in range(3):
        entry("cooked")
    entry("other")
    r = client.get("/me")
    assert "3 of 3" in r.text and "Streak: 1 week" in r.text and "$57" in r.text
    assert "First cook (earned)" in r.text and "10 meals (locked)" in r.text


def test_settings_validation(client):
    for bad in ("0", "abc", "22", "nan"):
        r = client.post("/settings", data={"weekly_goal": bad, "delivery_cost": "30"})
        assert r.status_code == 200 and "role=\"alert\"" in r.text
    con = db.connect()
    assert tuple(con.execute("SELECT weekly_goal, delivery_cost FROM users").fetchone()) == (3, 25)
    con.close()


def test_settings_save(client):
    r = client.post(
        "/settings",
        data={"weekly_goal": "5", "cal_target": "2000", "protein_target": "", "weight_goal": "170",
              "delivery_cost": "30", "home_meal_cost": "7"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/me"
    con = db.connect()
    row = tuple(con.execute("SELECT weekly_goal, cal_target, protein_target, weight_goal, delivery_cost FROM users").fetchone())
    con.close()
    assert row == (5, 2000, None, 170, 30)


def test_weight_trend_and_soon(client, monkeypatch):
    freeze(monkeypatch)
    seed("INSERT INTO weights VALUES ('u1', '2026-11-01', 180)")
    assert "<polyline" not in client.get("/me").text and "180" in client.get("/me").text
    seed("INSERT INTO weights VALUES ('u1', '2026-11-10', 178.5)")
    assert "<polyline" in client.get("/me").text
    assert "Grocery ordering is on the way" in client.get("/order").text
    assert "The food assistant is on the way" in client.get("/ask").text


def test_manifest_and_login_head(client):
    assert client.get("/static/manifest.json").json()["short_name"] == "Homeplate"
    assert client.get("/static/icon-192.png").status_code == 200


def test_sparkline():
    assert sparkline([(date(2026, 11, 1), 180)]) == ""
    pts = sparkline([(date(2026, 11, 1), 180), (date(2026, 11, 8), 178)]).split()
    assert len(pts) == 2
    for p in pts:
        x, y = map(float, p.split(","))
        assert 0 <= x <= 320 and 0 <= y <= 80


def test_me_with_only_future_entries(client, monkeypatch):
    freeze(monkeypatch)
    entry("cooked", "2026-12-01")
    assert client.get("/me").status_code == 200


def test_users_do_not_see_each_others_data(client, login_as, monkeypatch):
    freeze(monkeypatch)
    client.post("/entries", data={"kind": "other", "description": "secret-u1-meal", "calories": "777"})
    client.post("/weight", data={"lbs": "123.4"})
    entry("cooked")
    entry("cooked")
    assert "secret-u1-meal" in client.get("/").text and "2 of 3" in client.get("/me").text
    c2 = login_as("u2")
    t = c2.get("/").text
    assert "secret-u1-meal" not in t and "777" not in t and "123.4" not in t
    assert "0 of 3" in c2.get("/me").text
