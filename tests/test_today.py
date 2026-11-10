import io
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from PIL import Image

from app import auth, db, today


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


def hero(html):
    return re.search(r'<section class="card hero".*?</section>', html, re.S).group(0)


def details_tag(html, needle):
    """Opening tag of the <details> that encloses `needle`."""
    i = html.index(needle)
    start = html.rindex("<details", 0, i)
    assert "</details>" not in html[start:i], needle
    return html[start : html.index(">", start) + 1]


def jpeg(size=(2400, 1200), gps=False) -> bytes:
    img = Image.new("RGB", size, "red")
    exif = Image.Exif()
    if gps:
        exif[0x8825] = {1: "N"}
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_add_other(client):
    r = client.post("/entries", data={"kind": "other", "description": "2 eggs and toast", "calories": "320"})
    assert r.status_code == 200 and r.history[0].status_code == 303
    assert "2 eggs and toast" in r.text and "320" in r.text
    assert rows("SELECT calories FROM entries")[0][0] == 320


def test_cooked_prefills_nutrition(client, mock_mealie):
    mock_mealie[("GET", "/api/recipes/r1")] = httpx.Response(
        200, json={"id": "r1", "name": "Chili", "nutrition": {"calories": "450 kcal", "proteinContent": "32"}}
    )
    client.post("/entries", data={"kind": "cooked", "recipe_id": "r1", "recipe_name": "ignored"})
    e = rows("SELECT recipe_name, calories, protein_g FROM entries")[0]
    assert tuple(e) == ("Chili", 450, 32)


def test_recipe_gone(client, mock_mealie):
    mock_mealie[("GET", "/api/recipes/r1")] = httpx.Response(404)
    r = client.post("/entries", data={"kind": "cooked", "recipe_id": "r1"})
    assert "That recipe no longer exists" in r.text
    assert not rows("SELECT * FROM entries")


def test_leftovers_checkbox(client, mock_mealie):
    client.post("/entries", data={"kind": "cooked", "leftovers": "on", "description": "soup"})
    assert rows("SELECT kind FROM entries")[0][0] == "leftovers"


def test_validation(client):
    for data in [
        {"kind": "bogus", "description": "x"},
        {"kind": "other"},
        {"kind": "other", "description": "x", "calories": "-5"},
        {"kind": "other", "description": "x", "protein_g": "abc"},
    ]:
        assert client.post("/entries", data=data).status_code == 200
    assert not rows("SELECT * FROM entries")
    assert client.post("/weight", data={"lbs": "5"}).status_code == 200
    assert not rows("SELECT * FROM weights")


def test_photo_saved_and_stripped(client, data_dir):
    client.post(
        "/entries",
        data={"kind": "other", "description": "pic", "recipe_id": ""},
        files={"photo": ("a.jpg", jpeg(gps=True), "image/jpeg")},
    )
    p = rows("SELECT id, path, private FROM photos")[0]
    assert p["private"] == 1  # show_photo unticked
    img = Image.open(data_dir / "photos" / p["path"])
    assert len(img.getexif()) == 0 and max(img.size) <= 1600
    assert client.get(f"/photos/{p['id']}").status_code == 200


def test_show_photo_ticked(client, mock_mealie):
    mock_mealie[("GET", "/api/recipes/r1")] = httpx.Response(200, json={"id": "r1", "name": "Chili"})
    client.post(
        "/entries", data={"kind": "cooked", "recipe_id": "r1", "show_photo": "on"},
        files={"photo": ("a.jpg", jpeg((50, 50)), "image/jpeg")},
    )
    p = rows("SELECT private, recipe_id FROM photos")[0]
    assert tuple(p) == (0, "r1")


def test_bad_photo(client, data_dir):
    r = client.post(
        "/entries", data={"kind": "other", "description": "x"}, files={"photo": ("a.jpg", b"not an image")}
    )
    assert r.status_code == 200 and "That file isn&#39;t an image" in r.text or "That file isn't an image" in r.text
    assert len(rows("SELECT * FROM entries")) == 1
    assert not rows("SELECT * FROM photos")
    assert not list((data_dir / "photos").glob("*")) if (data_dir / "photos").exists() else True


def test_big_photo(client):
    r = client.post(
        "/entries", data={"kind": "other", "description": "x"},
        files={"photo": ("a.jpg", b"0" * (16 * 1024 * 1024))},
    )
    assert "too large" in r.text
    assert len(rows("SELECT * FROM entries")) == 1 and not rows("SELECT * FROM photos")


def test_delete_removes_photo(client, data_dir):
    client.post("/entries", data={"kind": "other", "description": "x"}, files={"photo": ("a.jpg", jpeg((50, 50)))})
    eid = rows("SELECT id FROM entries")[0][0]
    client.post(f"/entries/{eid}/delete")
    assert not rows("SELECT * FROM entries") and not rows("SELECT * FROM photos")
    assert not list((data_dir / "photos").glob("*"))


def test_other_users_entry_is_404(client, login_as):
    client.post("/entries", data={"kind": "other", "description": "x"}, files={"photo": ("a.jpg", jpeg((50, 50)))})
    eid = rows("SELECT id FROM entries")[0][0]
    pid = rows("SELECT id FROM photos")[0][0]
    c2 = login_as("u2")
    assert c2.post(f"/entries/{eid}/delete").status_code == 404
    assert c2.get(f"/photos/{pid}").status_code == 404
    assert client.get("/photos/9999").status_code == 404
    assert len(rows("SELECT * FROM entries")) == 1


def test_weight_upsert(client):
    client.post("/weight", data={"lbs": "180.5"})
    client.post("/weight", data={"lbs": "179"})
    assert [tuple(r) for r in rows("SELECT lbs FROM weights")] == [(179.0,)]
    assert 'value="179' in client.get("/").text


def test_totals_with_targets(client):
    con = db.connect()
    con.execute("UPDATE users SET cal_target = 2000, protein_target = 100")
    con.commit()
    con.close()
    client.post("/entries", data={"kind": "other", "description": "x", "calories": "300", "protein_g": "20"})
    t = client.get("/").text
    assert "1,700 left" in t and "20 of 100 g protein" in t


def test_hero_no_target(client):
    client.post("/entries", data={"kind": "other", "description": "x", "calories": "500", "protein_g": "20"})
    h = hero(client.get("/").text)
    assert '<svg class="ring"' not in h and "left" not in h and "over" not in h
    assert "500" in h and "20 g protein" in h and "<progress" not in h


def test_hero_under_target(client):
    run("UPDATE users SET cal_target = 2000")
    client.post("/entries", data={"kind": "other", "description": "x", "calories": "500"})
    h = hero(client.get("/").text)
    assert '<svg class="ring"' in h and 'stroke-dasharray="25 100"' in h and "1,500 left" in h and "over" not in h


def test_hero_empty_ring_has_no_progress_arc(client):
    run("UPDATE users SET cal_target = 2000")
    h = hero(client.get("/").text)
    assert '<svg class="ring"' in h and "stroke-dasharray" not in h and "2,000 left" in h


def test_hero_over_target(client):
    run("UPDATE users SET cal_target = 2000, protein_target = 100")
    client.post("/entries", data={"kind": "other", "description": "x", "calories": "2120", "protein_g": "130"})
    h = hero(client.get("/").text)
    assert 'stroke-dasharray="100 100"' in h and "120 over" in h and "left" not in h
    assert "danger" not in h and "warning" not in h
    assert '<progress' in h and "130 of 100 g protein" in h


def test_week_dots(client):
    last_week = (today.local_today() - timedelta(days=7)).isoformat()
    run("INSERT INTO entries (user_id, day, created_at, kind) VALUES ('u1', ?, ?, 'cooked')", last_week, last_week)
    client.post("/entries", data={"kind": "cooked", "description": "soup"})
    client.post("/entries", data={"kind": "cooked", "description": "soup", "leftovers": "on"})
    client.post("/entries", data={"kind": "other", "description": "snack"})
    h = hero(client.get("/").text)
    assert "2 of 3" in h and 'href="/me"' in h
    assert h.count('class="dot on"') == 2 and h.count('class="dot"') == 1 and "week-extra" not in h
    for _ in range(3):
        client.post("/entries", data={"kind": "cooked", "description": "soup"})
    h = hero(client.get("/").text)
    assert h.count('class="dot on"') == 3 and h.count('class="dot"') == 0 and "+2" in h


def test_optional_fields_collapsed(client):
    photo, add_food = 'name="photo"', 'value="other"'
    t = client.get("/").text
    assert " open" not in details_tag(t, photo) and " open" not in details_tag(t, add_food)
    t = client.post("/entries", data={"kind": "cooked"}).text
    assert "Add a description or pick a recipe" in t
    assert details_tag(t, photo).endswith(" open>") and " open" not in details_tag(t, add_food)
    t = client.post("/entries", data={"kind": "other"}).text
    assert details_tag(t, add_food).endswith(" open>") and " open" not in details_tag(t, photo)
    t = client.post("/entries", data={"kind": "cooked", "description": "x"}, files={"photo": ("a.jpg", b"not an image")}).text
    assert "That file isn" in t and details_tag(t, photo).endswith(" open>")


def test_remove_is_disclosed(client):
    client.post("/entries", data={"kind": "other", "description": "x"})
    eid = rows("SELECT id FROM entries")[0][0]
    t = client.get("/").text
    form = f'action="/entries/{eid}/delete"'
    assert " open" not in details_tag(t, form)
    assert 'aria-label="More"' in t[t.rindex("<details", 0, t.index(form)) : t.index(form)]


def test_entry_time_uses_tz(client, monkeypatch):
    monkeypatch.setenv("TZ", "America/Indiana/Indianapolis")
    monkeypatch.setattr(today, "_now", lambda: datetime(2026, 11, 9, 23, 40, tzinfo=timezone.utc))
    client.post("/entries", data={"kind": "other", "description": "x"})
    t = client.get("/").text
    assert "6:40 PM" in t and "Monday 9 Nov" in t


def test_date_label_uses_tz(client, monkeypatch):
    monkeypatch.setenv("TZ", "America/Indiana/Indianapolis")
    monkeypatch.setattr(today, "_now", lambda: datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc))
    assert "Monday 9 Nov" in client.get("/").text


def test_kitchen_links(client, monkeypatch):
    assert "Kitchen" not in client.get("/").text
    monkeypatch.setitem(auth.templates.env.globals, "mealie_url", "http://mealie.test")
    t = client.get("/").text
    for label in ("Recipes", "Meal plan", "Shopping list"):
        assert f'<a href="http://mealie.test">{label}' in t


def test_recipe_search(client, mock_mealie):
    mock_mealie[("GET", "/api/recipes")] = httpx.Response(200, json={"items": [{"id": "r1", "name": "Chili"}]})
    t = client.get("/recipes/search?q=chi").text
    assert 'name="recipe_id"' in t and "Chili" in t
    mock_mealie[("GET", "/api/households/mealplans/today")] = httpx.Response(
        200, json=[{"recipe": {"id": "r2", "name": "Tacos"}}]
    )
    assert "Tacos" in client.get("/recipes/search").text


def test_today_uses_tz(client, monkeypatch):
    monkeypatch.setenv("TZ", "America/Indiana/Indianapolis")
    monkeypatch.setattr(today, "_now", lambda: datetime(2026, 11, 10, 1, 30, tzinfo=timezone.utc))
    client.post("/entries", data={"kind": "other", "description": "x"})
    assert rows("SELECT day FROM entries")[0][0] == "2026-11-09"


def test_huge_calories_rejected(client):
    r = client.post("/entries", data={"kind": "other", "description": "x", "calories": "1e300"})
    assert r.status_code == 200 and "Calories must be a number" in r.text
    assert not rows("SELECT * FROM entries")


def test_posted_slug_stores_mealie_id(client, mock_mealie):
    mock_mealie[("GET", "/api/recipes/chili")] = httpx.Response(200, json={"id": "uuid-1", "name": "Chili"})
    client.post(
        "/entries", data={"kind": "cooked", "recipe_id": "chili", "show_photo": "on"},
        files={"photo": ("a.jpg", jpeg((50, 50)), "image/jpeg")},
    )
    assert rows("SELECT recipe_id FROM entries")[0][0] == "uuid-1"
    assert rows("SELECT recipe_id FROM photos")[0][0] == "uuid-1"


def test_recipe_id_is_quoted_in_mealie_path(client, mock_mealie):
    # httpx reports the decoded path; an unquoted id would have become /api/users/self (200, saved)
    mock_mealie[("GET", "/api/recipes/../users/self")] = httpx.Response(404)
    mock_mealie[("GET", "/api/recipes/x?perPage=1")] = httpx.Response(404)
    for rid in ("../users/self", "x?perPage=1"):
        r = client.post("/entries", data={"kind": "cooked", "recipe_id": rid})
        assert "That recipe no longer exists" in r.text
    assert not rows("SELECT * FROM entries")


def test_oversized_body_is_413(client):
    big = b"0" * (21 * 1024 * 1024)
    assert client.post("/entries", content=big, headers={"content-type": "application/octet-stream"}).status_code == 413
    # chunked: no Content-Length, so the byte counter has to catch it
    head = b'--x\r\nContent-Disposition: form-data; name="photo"; filename="a.jpg"\r\n\r\n'
    body = head + big + b"\r\n--x--\r\n"
    r = client.post(
        "/entries", content=(body[i : i + 1024 * 1024] for i in range(0, len(body), 1024 * 1024)),
        headers={"content-type": "multipart/form-data; boundary=x"},
    )
    assert r.status_code == 413
    assert not rows("SELECT * FROM entries")


def test_oversized_body_rejected_before_auth(mock_mealie):
    from fastapi.testclient import TestClient
    from app.main import app

    r = TestClient(app).post("/entries", content=b"0" * (21 * 1024 * 1024), follow_redirects=False)
    assert r.status_code == 413


def test_normal_upload_still_works(client):
    client.post("/entries", data={"kind": "other", "description": "x"}, files={"photo": ("a.jpg", b"1" * 100)})
    assert len(rows("SELECT * FROM entries")) == 1


def test_docs_are_not_public(mock_mealie):
    from fastapi.testclient import TestClient
    from app.main import app

    c = TestClient(app)
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p, follow_redirects=False).status_code in (303, 404)


def test_non_image_formats_rejected(client):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "GIF")
    r = client.post("/entries", data={"kind": "other", "description": "x"}, files={"photo": ("a.gif", buf.getvalue())})
    assert "That file isn" in r.text and not rows("SELECT * FROM photos")


def test_search_box_is_outside_the_form(client):
    t = client.get("/").text
    form = t[t.index('action="/entries"'):]
    assert 'name="q"' not in form[: form.index("</form>")]
    assert 'name="q"' in t


def test_ids_are_not_reused(client):
    client.post("/entries", data={"kind": "other", "description": "a"})
    first = rows("SELECT id FROM entries")[0][0]
    client.post(f"/entries/{first}/delete")
    client.post("/entries", data={"kind": "other", "description": "b"})
    assert rows("SELECT id FROM entries")[0][0] > first


def test_heic_upload_becomes_jpeg(client, data_dir):
    import pillow_heif  # imported only to build the HEIC; the app must register the opener itself

    buf = io.BytesIO()
    Image.new("RGB", (64, 48)).save(buf, format="HEIF")
    client.post("/entries", data={"kind": "other", "description": "x"}, files={"photo": ("a.heic", buf.getvalue())})
    p = rows("SELECT path FROM photos")[0]
    assert Image.open(data_dir / "photos" / p["path"]).format == "JPEG"


def test_fake_heic_rejected(client, data_dir):
    r = client.post("/entries", data={"kind": "other", "description": "x"}, files={"photo": ("x.heic", b"not an image")})
    assert "That file isn" in r.text and not rows("SELECT * FROM photos")
    assert not (data_dir / "photos").exists() or not list((data_dir / "photos").glob("*"))


def test_diary_photo_without_recipe_is_private(client, login_as):
    c2 = login_as("u2")
    c2.post("/entries", data={"kind": "other", "description": "x", "show_photo": "on"}, files={"photo": ("a.jpg", jpeg((50, 50)))})
    p = rows("SELECT id, private FROM photos")[0]
    assert p["private"] == 1
    assert client.get(f"/photos/{p['id']}").status_code == 404
    assert c2.get(f"/photos/{p['id']}").status_code == 200
    assert c2.post(f"/photos/{p['id']}/private", follow_redirects=False).status_code == 404
    assert rows("SELECT private FROM photos")[0][0] == 1


def test_huge_photo_id_is_404(client):
    big = "99999999999999999999999999999"
    assert client.get(f"/photos/{big}").status_code == 404
    assert client.post(f"/photos/{big}/private").status_code == 404


def test_icc_profile_kept_exif_dropped(client, data_dir):
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x8825] = {1: "N"}
    Image.new("RGB", (50, 50), "red").save(buf, "JPEG", exif=exif, icc_profile=b"fake-icc-profile")
    client.post("/entries", data={"kind": "other", "description": "x"}, files={"photo": ("a.jpg", buf.getvalue())})
    img = Image.open(data_dir / "photos" / rows("SELECT path FROM photos")[0][0])
    assert img.info.get("icc_profile") == b"fake-icc-profile" and not img.getexif()


def test_decompression_bomb_is_not_an_image(client, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1800)  # 2500 pixels: inside Pillow's warn-only band (1x-2x), must still be refused
    r = client.post("/entries", data={"kind": "other", "description": "x"}, files={"photo": ("a.jpg", jpeg((50, 50)))})
    assert "That file isn&#39;t an image" in r.text or "That file isn't an image" in r.text
    assert not rows("SELECT * FROM photos")


def burn(calories, eaten=None):
    run(
        "INSERT INTO workouts (user_id, day, activity, minutes, intensity, calories, source, created_at) "
        "VALUES ('u1', ?, 'cycling', 60, 'moderate', ?, 'entered', 'x')",
        today.local_today().isoformat(), calories,
    )
    if eaten:
        run(
            "INSERT INTO entries (user_id, day, created_at, kind, description, calories) VALUES ('u1', ?, ?, 'other', 'x', ?)",
            today.local_today().isoformat(), datetime.now(timezone.utc).isoformat(), eaten,
        )


def test_hero_net_under(client):
    run("UPDATE users SET cal_target = 2000")
    burn(600, 1840)
    h = hero(client.get("/").text)
    assert 'stroke-dasharray="62 100"' in h and ">1,240<" in h and "760 left" in h
    assert ">1,840 eaten ·</span> <span" in h and ">600 burned</span>" in h and "counted" not in h and "(est.)" not in h
    assert '1,240 net of 2,000 calories: 1,840 eaten, 600 burned"' in h
    assert ">net kcal<" in h


def test_hero_net_negative(client):
    run("UPDATE users SET cal_target = 2000")
    burn(900, 500)
    h = hero(client.get("/").text)
    assert "stroke-dasharray" not in h and "2,400 left" in h
    assert "danger" not in h and "warning" not in h and ">900 burned</span>" in h and ">net kcal<" in h


def test_hero_net_over_is_neutral(client):
    run("UPDATE users SET cal_target = 2000")
    burn(300, 2500)
    h = hero(client.get("/").text)
    assert "200 over" in h and 'stroke-dasharray="100 100"' in h and "danger" not in h and "warning" not in h


def test_hero_no_burn_unchanged(client):
    run("UPDATE users SET cal_target = 2000")
    client.post("/entries", data={"kind": "other", "description": "x", "calories": "500"})
    h = hero(client.get("/").text)
    assert "burned" not in h and "eaten" not in h and "500 of 2,000 calories" in h


def test_hero_pct(client):
    run("UPDATE users SET cal_target = 2000, workout_pct = 75")
    burn(800, 1840)
    h = hero(client.get("/").text)
    assert ">800 burned,</span> <span class=\"nw\">600 counted</span>" in h and "760 left" in h
    assert '1,240 net of 2,000 calories: 1,840 eaten, 800 burned, 600 counted"' in h


def test_hero_pct_zero(client):
    run("UPDATE users SET cal_target = 2000, workout_pct = 0")
    burn(800, 1000)
    h = hero(client.get("/").text)
    assert ">800 burned,</span> <span class=\"nw\">0 counted</span>" in h and "1,000 left" in h


def test_hero_no_target_with_burn(client):
    burn(600, 1840)
    h = hero(client.get("/").text)
    assert '<svg class="ring"' not in h and ">1,240<" in h and ">600 burned</span>" in h and "1,240</span> <span class=\"muted\">net kcal" in h


def test_delete_entry_huge_id_is_404(client):
    assert client.post(f"/entries/{2**63}/delete").status_code == 404


def test_hero_estimated_marker(client):
    run("UPDATE users SET cal_target = 2000, workout_pct = 75")
    run(
        "INSERT INTO workouts (user_id, day, activity, minutes, intensity, calories, source, created_at) "
        "VALUES ('u1', ?, 'cycling', 60, 'moderate', 800, 'estimated', 'x')",
        today.local_today().isoformat(),
    )
    assert ">800 burned,</span> <span class=\"nw\">600 counted (est.)</span>" in hero(client.get("/").text)
    run("UPDATE workouts SET source = 'entered'")
    assert "(est.)" not in hero(client.get("/").text)
