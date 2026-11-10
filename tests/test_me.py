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
    assert "0 of 3" in r.text and "Streak" not in r.text and "Fresh start" not in r.text


def test_me_counts(client, monkeypatch):
    freeze(monkeypatch)
    for _ in range(3):
        entry("cooked")
    entry("other")
    r = client.get("/me")
    assert "3 of 3" in r.text and "Streak 1 week" in r.text and "$57" in r.text
    assert "First cook" in r.text and "10 meals" in r.text


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


def test_manifest_and_login_head(client):
    assert client.get("/static/manifest.json").json()["short_name"] == "Homeplate"
    assert client.get("/static/icon-192.png").status_code == 200


def test_sparkline():
    assert sparkline([(date(2026, 11, 1), 180)]) == {}
    two = [(date(2026, 11, 1), 180), (date(2026, 11, 8), 178)]
    sp = sparkline(two)
    pts = [tuple(map(float, p.split(","))) for p in sp["line"].split()]
    assert len(pts) == 2 and sp["last"] == pts[-1] and sp["goal_y"] is None
    for x, y in pts:
        assert 0 <= x <= 320 and 0 <= y <= 80
    assert 0 <= sparkline(two, goal=179)["goal_y"] <= 80
    assert sparkline(two, goal=170)["goal_y"] is None and sparkline(two, goal=190)["goal_y"] is None


def test_streak_copy(client, monkeypatch):
    freeze(monkeypatch)
    entry("cooked", "2026-11-02")  # only an earlier week: streak 0
    t = client.get("/me").text
    assert "Fresh start this week" in t and "0 weeks" not in t and "Streak" not in t
    for _ in range(3):
        entry("cooked", "2026-11-03")
        entry("cooked")
    t = client.get("/me").text
    assert "Streak 2 weeks" in t and "Fresh start" not in t


def test_fresh_start_needs_earlier_week(client, monkeypatch):
    freeze(monkeypatch)
    entry("cooked")  # this week only
    t = client.get("/me").text
    assert "Fresh start" not in t and "Streak" not in t


def test_savings_never_negative(client, monkeypatch):
    freeze(monkeypatch)
    seed("UPDATE users SET delivery_cost = 5, home_meal_cost = 20")
    entry("cooked")
    t = client.get("/me").text
    assert "$0" in t and "$-" not in t and "-$" not in t


def test_badges(client, monkeypatch):
    freeze(monkeypatch)
    entry("cooked")
    t = client.get("/me").text
    assert t.count('class="badge') == 5
    assert t.count("Earned") == 1 and t.count("icon-lock") == 4 and t.count("icon-check") == 1
    for c in ("Cook 10 meals", "Cook 50 meals", "Hit your goal 4 weeks running", "Cook 5 different recipes"):
        assert c in t
    assert "Log your first cook" not in t


def test_numbers_trimmed(client, monkeypatch):
    freeze(monkeypatch)
    seed("INSERT INTO weights VALUES ('u1', '2026-11-10', 180.0)")
    t = client.get("/me").text
    assert ">180<" in t and "180.0" not in t
    seed("UPDATE weights SET lbs = 180.5")
    assert "180.5" in client.get("/me").text
    seed("UPDATE users SET delivery_cost = 25.0, weight_goal = 170.0")
    t = client.get("/me").text
    assert 'value="25"' in t and 'value="25.0"' not in t and 'value="170"' in t


def test_settings_open_on_error(client):
    assert "<details class=\"card more\" open" not in client.get("/me").text
    r = client.post("/settings", data={"weekly_goal": "0", "delivery_cost": "30"})
    assert 'role="alert"' in r.text and "<details class=\"card more\" open" in r.text


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


def pct():
    con = db.connect()
    try:
        return con.execute("SELECT workout_pct FROM users").fetchone()[0]
    finally:
        con.close()


SIX = {"weekly_goal": "3", "cal_target": "2000", "protein_target": "", "weight_goal": "", "delivery_cost": "25", "home_meal_cost": "6"}


def test_workout_pct_setting(client):
    assert pct() == 100
    assert client.post("/settings", data=SIX).status_code == 200 and pct() == 100  # missing keeps the stored value
    assert client.post("/settings", data=SIX | {"workout_pct": "75"}).status_code == 200 and pct() == 75
    for bad in ("-1", "101", "abc", "", "7.5"):
        r = client.post("/settings", data=SIX | {"workout_pct": bad, "weekly_goal": "5"})
        assert 'role="alert"' in r.text and pct() == 75, bad
    assert client.post("/settings", data=SIX).status_code == 200 and pct() == 75
    assert 'name="workout_pct"' in client.get("/me").text


def test_workout_pct_migration(data_dir):
    import sqlite3

    con = sqlite3.connect(data_dir / "homeplate.db")
    con.execute("CREATE TABLE users (mealie_user_id TEXT PRIMARY KEY, name TEXT)")
    con.execute("INSERT INTO users (mealie_user_id) VALUES ('old')")
    con.commit()
    con.close()
    con = db.connect()
    try:
        assert con.execute("SELECT workout_pct FROM users").fetchone()[0] == 100
    finally:
        con.close()
