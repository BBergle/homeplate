import httpx
from fastapi.testclient import TestClient

from app.main import app
from tests.test_gallery import upload
from tests.test_today import jpeg, rows

TOKEN = "11111111-1111-1111-1111-111111111111"
RECIPE = {
    "id": "uuid-1", "slug": "chili", "name": "Chili", "description": "Warm", "image": "abc",
    "recipeServings": 4, "totalTime": "1 hour",
    "recipeIngredient": [{"display": "2 beans", "title": "Base"}, {"display": "1 onion"}],
    "recipeInstructions": [{"text": "Stir\nwell", "title": None}],
    "nutrition": {"calories": "300 kcal", "proteinContent": "20 g"},
}


def setup(mock_mealie):
    mock_mealie[("GET", "/api/recipes/uuid-1")] = httpx.Response(200, json={"id": "uuid-1", "slug": "chili", "name": "Chili"})
    mock_mealie[("POST", "/api/shared/recipes")] = httpx.Response(201, json={"id": TOKEN})
    mock_mealie[("DELETE", f"/api/shared/recipes/{TOKEN}")] = httpx.Response(200, json={})
    mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.Response(200, json=RECIPE)
    mock_mealie[("GET", "/api/media/recipes/uuid-1/images/min-original.webp")] = httpx.Response(200, content=b"webp")


def shared(login_as, mock_mealie):
    u1, u2 = login_as("u1"), login_as("u2")
    setup(mock_mealie)
    a, b = upload(u1), upload(u2)
    assert u1.post("/r/uuid-1/share", follow_redirects=False).status_code == 303
    return u1, a, b


def test_share_page_needs_no_session(login_as, mock_mealie):
    _, a, b = shared(login_as, mock_mealie)
    r = TestClient(app).get(f"/s/{TOKEN}")
    assert r.status_code == 200
    for s in ("Chili", "1 onion", "Base", "Stir", f"/s/{TOKEN}/photo/{a}", f"/s/{TOKEN}/photo/{b}", f"/s/{TOKEN}/image", "300", "20"):
        assert s in r.text
    assert 'href="/me"' not in r.text and 'class="tabs"' not in r.text
    assert TestClient(app).get(f"/s/{TOKEN}/photo/{a}").status_code == 200
    assert TestClient(app).get(f"/s/{TOKEN}/image").content == b"webp"


def test_share_page_names_no_user(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    t = TestClient(app).get(f"/s/{TOKEN}").text
    assert "User u1" not in t and "User u2" not in t and "u1" not in t and "u2" not in t


def test_private_photo_not_on_share(login_as, mock_mealie):
    u1, _, _ = shared(login_as, mock_mealie)
    p = upload(u1, show=False)
    c = TestClient(app)
    assert f"/photo/{p}" not in c.get(f"/s/{TOKEN}").text
    assert c.get(f"/s/{TOKEN}/photo/{p}").status_code == 404


def test_photo_of_other_recipe_404(login_as, mock_mealie):
    u1, _, _ = shared(login_as, mock_mealie)
    mock_mealie[("GET", "/api/recipes/uuid-2")] = httpx.Response(200, json={"id": "uuid-2", "slug": "x", "name": "X"})
    u1.post("/entries", data={"kind": "cooked", "recipe_id": "uuid-2", "show_photo": "on"},
            files={"photo": ("a.jpg", jpeg((50, 50)), "image/jpeg")})
    other = rows("SELECT id FROM photos WHERE recipe_id = 'uuid-2'")[0][0]
    assert TestClient(app).get(f"/s/{TOKEN}/photo/{other}").status_code == 404


def test_unshare_makes_everything_404(login_as, mock_mealie):
    u1, a, _ = shared(login_as, mock_mealie)
    r = u1.post("/r/uuid-1/unshare", follow_redirects=False)
    assert r.status_code == 303 and rows("SELECT * FROM shares") == []
    c = TestClient(app)
    for path in ("", f"/photo/{a}", "/image"):
        assert c.get(f"/s/{TOKEN}{path}").status_code == 404, path


def test_share_is_reused(login_as, mock_mealie):
    u1, _, _ = shared(login_as, mock_mealie)
    mock_mealie[("POST", "/api/shared/recipes")] = RuntimeError("must not be called")
    u1.post("/r/uuid-1/share")
    assert len(rows("SELECT * FROM shares")) == 1
    assert TOKEN in u1.get("/r/uuid-1").text


def test_share_headers(login_as, mock_mealie):
    _, a, _ = shared(login_as, mock_mealie)
    c = TestClient(app)
    for path in (f"/s/{TOKEN}", f"/s/{TOKEN}/photo/{a}", f"/s/{TOKEN}/image", "/s/nope"):
        r = c.get(path)
        assert r.headers["x-robots-tag"] == "noindex" and r.headers["referrer-policy"] == "no-referrer", path
    assert 'name="robots"' in c.get(f"/s/{TOKEN}").text
    assert "no longer available" in c.get("/s/nope").text


def test_share_mealie_down(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.ConnectError("boom")
    r = TestClient(app).get(f"/s/{TOKEN}")
    assert r.status_code == 502 and "Can't reach Mealie" in r.text and "Traceback" not in r.text
    assert r.headers["x-robots-tag"] == "noindex"


def test_share_gone_in_mealie_is_404_not_login(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    for code in (404, 401):
        mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.Response(code)
        r = TestClient(app).get(f"/s/{TOKEN}", follow_redirects=False)
        assert r.status_code == 404 and "no longer available" in r.text


def test_share_requires_session_to_create(mock_mealie):
    c = TestClient(app)
    for p in ("share", "unshare"):
        r = c.post(f"/r/uuid-1/{p}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
    assert rows("SELECT * FROM shares") == []
