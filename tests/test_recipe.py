import re

import httpx
from fastapi.testclient import TestClient

from app.main import app
from tests.test_gallery import upload
from tests.test_today import jpeg, rows

RECIPE = {
    "id": "uuid-1", "slug": "chili", "name": "Chili", "description": "Warm", "image": "abc",
    "recipeServings": 4, "totalTime": "1 hour",
    "recipeIngredient": [{"display": "2 beans", "title": "Base"}, {"display": "1 onion"}],
    "recipeInstructions": [{"text": "Stir\nwell", "title": None}],
    "nutrition": {"calories": "300 kcal", "proteinContent": "20 g"},
    # what real Mealie also returns, and the page must never show
    "userId": "UID-secret-1", "groupId": "GID-secret-2", "householdId": "HID-secret-3",
    "comments": [{"text": "yum", "user": {"username": "uname-secret", "fullName": "Full Name-secret", "admin": True}}],
}


def setup(mock_mealie, recipe=RECIPE):
    mock_mealie[("GET", "/api/recipes/uuid-1")] = httpx.Response(200, json=recipe)
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(200, json={"id": "x", "groupSlug": "home"})
    mock_mealie[("GET", "/api/media/recipes/uuid-1/images/min-original.webp")] = httpx.Response(200, content=b"webp")


def test_recipe_page_shows_recipe_and_photos(login_as, mock_mealie):
    u1, u2 = login_as("u1"), login_as("u2")
    setup(mock_mealie)
    a, b = upload(u1), upload(u2)
    r = u1.get("/r/uuid-1")
    assert r.status_code == 200
    for s in ("Chili", "1 onion", "Base", "Stir", "Warm", "300 kcal", "20 g protein", f'/photos/{a}"', f'/photos/{b}"',
              'src="/r/uuid-1/image"', 'class="tabs"'):
        assert s in r.text, s
    assert 'alt="Photo of Chili"' in r.text and 'role="list"' in r.text
    marks = ['fetchpriority="high"', "<h1", 'class="chip"', ">Warm<", ">Ingredients<", ">Method<", ">Photos<", "Link to this recipe"]
    pos = [r.text.index(m) for m in marks]
    assert pos == sorted(pos)
    setup(mock_mealie, RECIPE | {"image": None})
    assert "fetchpriority" not in u1.get("/r/uuid-1").text


def test_page_names_no_user(login_as, mock_mealie):
    u1 = login_as("u1")
    setup(mock_mealie)
    upload(u1)
    t = u1.get("/r/uuid-1").text
    assert "User u1" not in t
    for secret in ("secret", "UID", "GID", "HID", "uname", "Full Name", "yum"):
        assert secret not in t, secret


def test_private_photo_only_for_owner(login_as, mock_mealie):
    u1, u2 = login_as("u1"), login_as("u2")
    setup(mock_mealie)
    p = upload(u2, show=False)
    assert f"/photos/{p}" not in u1.get("/r/uuid-1").text and u1.get(f"/photos/{p}").status_code == 404
    assert f"/photos/{p}" in u2.get("/r/uuid-1").text and u2.get(f"/photos/{p}").status_code == 200
    assert TestClient(app).get(f"/photos/{p}", follow_redirects=False).status_code == 303


def test_photo_of_other_recipe_not_on_page(login_as, mock_mealie):
    u1 = login_as("u1")
    setup(mock_mealie)
    mock_mealie[("GET", "/api/recipes/uuid-2")] = httpx.Response(200, json={"id": "uuid-2", "slug": "x", "name": "X"})
    u1.post("/entries", data={"kind": "cooked", "recipe_id": "uuid-2", "show_photo": "on"},
            files={"photo": ("a.jpg", jpeg((50, 50)), "image/jpeg")})
    other = rows("SELECT id FROM photos WHERE recipe_id = 'uuid-2'")[0][0]
    assert f"/photos/{other}" not in u1.get("/r/uuid-1").text


def test_recipe_image_requires_session(client, mock_mealie):
    setup(mock_mealie)
    r = client.get("/r/uuid-1/image")
    assert r.status_code == 200 and r.content == b"webp" and r.headers["content-type"] == "image/webp"
    r = TestClient(app).get("/r/uuid-1/image", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    mock_mealie[("GET", "/api/media/recipes/uuid-1/images/min-original.webp")] = httpx.Response(404)
    assert client.get("/r/uuid-1/image").status_code == 404
    mock_mealie[("GET", "/api/recipes/nope")] = httpx.Response(404)
    assert client.get("/r/nope/image").status_code == 404


def test_old_public_addresses_gone(client, mock_mealie):
    for c in (TestClient(app), client):
        for path in ("/s/x", "/s/x/photo/1", "/s/x/image"):
            r = c.get(path, follow_redirects=False)
            assert r.status_code in (303, 404) and (r.status_code == 404 or r.headers["location"] == "/login"), path


def test_no_share_routes(client, mock_mealie):
    setup(mock_mealie)
    for p in ("share", "unshare"):
        assert client.post(f"/r/uuid-1/{p}", follow_redirects=False).status_code in (404, 405)
    assert 'action="/r/uuid-1/share' not in client.get("/r/uuid-1").text


def test_link_card(client, mock_mealie, monkeypatch):
    setup(mock_mealie)
    monkeypatch.setenv("BASE_URL", "https://home.example/")
    t = client.get("/r/uuid-1").text
    assert re.search(r'<input[^>]*value="https://home.example/r/uuid-1"[^>]*readonly|<input[^>]*readonly[^>]*value="https://home.example/r/uuid-1"', t)
    assert '<a href="https://home.example/r/uuid-1">' in t
    assert "Link to this recipe" in t and "Only people with an account can open this." in t
    assert "Public" not in t and "Stop sharing" not in t


def test_serves_prints_whole_numbers(client, mock_mealie):
    for servings, want, not_want in ((4.0, ">Serves 4<", "4.0"), (2.5, ">Serves 2.5<", None), (4, ">Serves 4<", "4.0")):
        setup(mock_mealie, RECIPE | {"recipeServings": servings})
        t = client.get("/r/uuid-1").text
        assert want in t and (not_want is None or not_want not in t)


def test_login_next(mock_mealie, login_as):
    login_as("u1")  # primes the login mocks
    for nxt, want in (("/r/abc", "/r/abc"), ("https://evil.example", "/"), ("//evil.example", "/"), ("/me", "/"), ("/r/../../x", "/"), ("", "/")):
        c = TestClient(app)
        r = c.post("/login", data={"username": "u1", "password": "pw", "next": nxt}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == want, nxt
    r = TestClient(app).post("/login", data={"username": "u1", "password": "pw"}, follow_redirects=False)
    assert r.headers["location"] == "/"
    f = TestClient(app).get("/login?next=/r/abc").text
    assert '<input type="hidden" name="next" value="/r/abc">' in f
    for bad in ("/me", "//evil.example", "https://evil.example", "/r/../x"):
        assert 'name="next"' not in TestClient(app).get("/login", params={"next": bad}).text


def test_unauthenticated_recipe_redirects_with_next(mock_mealie):
    c = TestClient(app)
    r = c.get("/r/uuid-1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/r/uuid-1"
    assert "Chili" not in r.text
    r = c.get("/r/uuid-1", headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.headers["hx-redirect"] == "/login"
    assert c.get("/me", follow_redirects=False).headers["location"] == "/login"
    assert c.post("/r/uuid-1/x", follow_redirects=False).status_code in (404, 405)
    assert c.get("/r/a.b", follow_redirects=False).headers["location"] == "/login"
    assert c.get("/r/" + "a" * 65, follow_redirects=False).headers["location"] == "/login"


def test_route_walk_public_list(mock_mealie):
    for route in app.routes:
        assert not getattr(route, "path", "").startswith("/s/")
