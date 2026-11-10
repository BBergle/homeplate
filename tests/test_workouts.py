from datetime import date

from fastapi.testclient import TestClient

from app import db, today, workouts
from app.main import app


def rows(sql, *args):
    con = db.connect()
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def run(sql, *args):
    con = db.connect()
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def add_workout(user="u1", calories=600, source="estimated", note=None, activity="cycling"):
    run(
        "INSERT INTO workouts (user_id, day, activity, minutes, intensity, calories, source, note, created_at) "
        "VALUES (?, ?, ?, 90, 'moderate', ?, ?, ?, 'x')",
        user, today.local_today().isoformat(), activity, calories, source, note,
    )


def post(client, **over):
    data = {"activity": "cycling", "intensity": "moderate", "minutes": "60", "calories": "", "note": ""}
    return client.post("/workouts", data=data | over)


def test_estimate_formula():
    assert workouts.estimate("cycling", "moderate", 60, 180.0) == round(7.0 * 180 * 0.45359237) == 572
    assert workouts.estimate("walking", "easy", 30, 150.0) == 68
    assert workouts.estimate("cycling", "hard", 90, None) == 1041


def test_log_with_own_number(client):
    r = post(client, calories="650")
    assert r.status_code == 200 and r.history[0].status_code == 303
    w = rows("SELECT * FROM workouts")[0]
    assert (w["calories"], w["source"], w["minutes"], w["day"]) == (650, "entered", 60, today.local_today().isoformat())


def test_log_blank_estimates(client):
    run("INSERT INTO weights (user_id, date, lbs) VALUES ('u1', '2020-01-01', 150), ('u1', '2020-02-01', 180)")
    post(client)
    w = rows("SELECT * FROM workouts")[0]
    assert (w["calories"], w["source"]) == (workouts.estimate("cycling", "moderate", 60, 180.0), "estimated")
    assert w["calories"] == 572


def test_no_weight_hint(client):
    hint = "Log your weight for a better estimate."
    assert hint in client.get("/").text
    run("INSERT INTO weights (user_id, date, lbs) VALUES ('u1', '2020-01-01', 150)")
    assert hint not in client.get("/").text


def test_estimate_fragment(client):
    r = client.post(
        "/workouts/estimate",
        data={"activity": "cycling", "intensity": "moderate", "minutes": "60"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200 and "<html" not in r.text
    assert 'value="' + str(workouts.estimate("cycling", "moderate", 60, None)) + '"' in r.text
    assert "60 minutes at moderate effort and 170 lb" in r.text
    r = client.post("/workouts/estimate", data={"activity": "cycling", "intensity": "moderate", "minutes": "abc"})
    assert r.status_code == 200 and "<html" not in r.text and "value=" not in r.text and "Minutes" in r.text


def test_validation(client):
    bad = [{"minutes": m} for m in ("", "0", "-5", "abc", "1441", "1e300", "nan", "inf")]
    bad += [{"calories": c} for c in ("-1", "abc", "20001", "1e300", "nan", "inf")]
    bad += [{"activity": "flying"}, {"intensity": "brutal"}, {"note": "x" * 201}]
    for over in bad:
        r = post(client, **over)
        assert r.status_code == 200 and "msg-error" in r.text, over
        assert 'add-workout" open' in r.text, over
    assert not rows("SELECT * FROM workouts")


def test_listed_today(client):
    add_workout(calories=600, source="estimated")
    add_workout(calories=450, source="entered")
    add_workout(calories=300, source="entered", activity="other", note="Rowing machine")
    html = client.get("/").text
    assert "Cycling" in html and "90 min" in html and "600 kcal burned" in html and "Workout" in html
    assert "Rowing machine" in html
    assert html.count("estimated") == 1  # only the estimated row


def test_other_users_workout_404(client, login_as):
    add_workout()
    wid = rows("SELECT id FROM workouts")[0][0]
    other = login_as("u2")
    assert other.post(f"/workouts/{wid}/delete").status_code == 404
    assert rows("SELECT id FROM workouts")
    assert "90 min" not in other.get("/").text
    assert client.post(f"/workouts/{wid}/delete").status_code == 200
    assert not rows("SELECT id FROM workouts")


def test_requires_session(mock_mealie):
    c = TestClient(app)
    for path in ("/workouts", "/workouts/estimate", "/workouts/1/delete"):
        r = c.post(path, data={}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login", path


def test_zero_calories_is_entered(client):
    post(client, calories="0")
    w = rows("SELECT * FROM workouts")[0]
    assert (w["calories"], w["source"]) == (0, "entered")


def test_huge_workout_id_is_404(client):
    assert client.post(f"/workouts/{2**63}/delete").status_code == 404


def test_one_minute_hint(client):
    r = client.post("/workouts/estimate", data={"activity": "cycling", "intensity": "moderate", "minutes": "1"})
    assert "1 minute at" in r.text and "1 minutes" not in r.text
