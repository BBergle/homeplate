import httpx

from app import db
from tests.test_today import jpeg, rows


def setup(mock_mealie):
    mock_mealie[("GET", "/api/recipes/uuid-1")] = httpx.Response(200, json={"id": "uuid-1", "slug": "chili", "name": "Chili"})
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(200, json={"id": "x", "groupSlug": "home"})


def upload(c, show=True):
    data = {"kind": "cooked", "recipe_id": "uuid-1"} | ({"show_photo": "on"} if show else {})
    c.post("/entries", data=data, files={"photo": ("a.jpg", jpeg((50, 50)), "image/jpeg")})
    return rows("SELECT id FROM photos ORDER BY id DESC")[0][0]


def test_gallery_shows_everyones_public_photos(login_as, mock_mealie):
    u1, u2 = login_as("u1"), login_as("u2")
    setup(mock_mealie)
    a, b = upload(u1), upload(u2)
    r = u1.get("/r/uuid-1")
    assert r.status_code == 200 and "Chili" in r.text
    for i in (a, b):
        assert f'/photos/{i}"' in r.text
        assert u1.get(f"/photos/{i}").status_code == 200


def test_private_photo_hidden_from_others(login_as, mock_mealie):
    u1, u2 = login_as("u1"), login_as("u2")
    setup(mock_mealie)
    p = upload(u2, show=False)
    assert f"/photos/{p}" not in u1.get("/r/uuid-1").text
    assert u1.get(f"/photos/{p}").status_code == 404
    mine = u2.get("/r/uuid-1").text
    assert f"/photos/{p}" in mine and "Private" in mine


def test_toggle_private(login_as, mock_mealie):
    u1, u2 = login_as("u1"), login_as("u2")
    setup(mock_mealie)
    p = upload(u2)
    assert f"/photos/{p}" in u1.get("/r/uuid-1").text
    assert u1.post(f"/photos/{p}/private").status_code == 404
    assert rows("SELECT private FROM photos")[0][0] == 0
    r = u2.post(f"/photos/{p}/private", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/r/uuid-1"
    assert f"/photos/{p}" not in u1.get("/r/uuid-1").text
    u2.post(f"/photos/{p}/private")
    assert f"/photos/{p}" in u1.get("/r/uuid-1").text


def test_unknown_recipe_404(client, mock_mealie):
    mock_mealie[("GET", "/api/recipes/nope")] = httpx.Response(404)
    assert client.get("/r/nope").status_code == 404


def test_me_lists_cooked_recipes(client, mock_mealie):
    setup(mock_mealie)
    for _ in range(2):
        client.post("/entries", data={"kind": "cooked", "recipe_id": "uuid-1"})
    r = client.get("/me")
    assert r.text.count('href="/r/uuid-1"') == 1 and "Recipes you've cooked" in r.text.replace("&#39;", "'")
    assert ">2<" in r.text


def test_gallery_count_and_private_chip(login_as, mock_mealie):
    u1, u2 = login_as("u1"), login_as("u2")
    setup(mock_mealie)
    upload(u1)
    assert "1 photo<" in u1.get("/r/uuid-1").text
    p = upload(u2, show=False)
    upload(u2)
    mine = u2.get("/r/uuid-1").text
    assert "3 photos<" in mine and mine.count('class="chip"') == 1 and mine.count('<details class="more"') == 2
    assert 'aria-label="Photo options"' in mine or "Photo options" in mine
    other = u1.get("/r/uuid-1").text
    assert "2 photos<" in other and 'class="chip"' not in other and f"/photos/{p}/private" not in other
    assert "/private" in other  # u1's own photo still has its toggle
