import io
import os
from datetime import datetime, timezone

import httpx
from PIL import Image

from app import db, today


def rows(sql, *args):
    con = db.connect()
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


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
    assert "300 / 2000" in t and "20 / 100" in t


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
