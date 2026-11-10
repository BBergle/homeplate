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
    # what real Mealie also returns, and the public page must never show
    "userId": "UID-secret-1", "groupId": "GID-secret-2", "householdId": "HID-secret-3",
    "comments": [{"text": "yum", "user": {"username": "uname-secret", "fullName": "Full Name-secret", "admin": True}}],
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
    for secret in ("secret", "UID", "GID", "HID", "uname", "Full Name", "yum"):
        assert secret not in t, secret


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


def test_private_toggle_of_shared_photo_hides_it(login_as, mock_mealie):
    u1, a, _ = shared(login_as, mock_mealie)
    c = TestClient(app)
    assert c.get(f"/s/{TOKEN}/photo/{a}").status_code == 200
    # photo a belongs to u1 (the first upload)
    assert u1.post(f"/photos/{a}/private", follow_redirects=False).status_code == 303
    assert c.get(f"/s/{TOKEN}/photo/{a}").status_code == 404


def test_dead_share_page_removes_local_row(login_as, mock_mealie):
    _, a, _ = shared(login_as, mock_mealie)
    mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.Response(404)
    c = TestClient(app)
    assert c.get(f"/s/{TOKEN}").status_code == 404
    assert rows("SELECT * FROM shares") == []
    assert c.get(f"/s/{TOKEN}/photo/{a}").status_code == 404
    assert c.get(f"/s/{TOKEN}/image").status_code == 404


def test_mealie_down_keeps_share_row(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.ConnectError("boom")
    TestClient(app).get(f"/s/{TOKEN}")
    assert len(rows("SELECT * FROM shares")) == 1


def test_unshare_when_recipe_gone_in_mealie(login_as, mock_mealie):
    u1, _, _ = shared(login_as, mock_mealie)
    mock_mealie[("GET", "/api/recipes/uuid-1")] = httpx.Response(404)
    mock_mealie[("DELETE", f"/api/shared/recipes/{TOKEN}")] = httpx.Response(404)
    r = u1.post("/r/uuid-1/unshare", follow_redirects=False)
    assert r.status_code == 303 and rows("SELECT * FROM shares") == []


def test_share_is_reused(login_as, mock_mealie):
    u1, _, _ = shared(login_as, mock_mealie)
    mock_mealie[("POST", "/api/shared/recipes")] = RuntimeError("must not be called")
    u1.post("/r/uuid-1/share")
    assert len(rows("SELECT * FROM shares")) == 1
    assert TOKEN in u1.get("/r/uuid-1").text


def test_serves_prints_whole_numbers(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    for servings, want, not_want in ((4.0, ">Serves 4<", "4.0"), (2.5, ">Serves 2.5<", None), (4, ">Serves 4<", "4.0")):
        mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.Response(200, json=RECIPE | {"recipeServings": servings})
        t = TestClient(app).get(f"/s/{TOKEN}").text
        assert want in t and (not_want is None or not_want not in t)


def test_huge_photo_id_is_404(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    assert TestClient(app).get(f"/s/{TOKEN}/photo/99999999999999999999999999999").status_code == 404


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


def test_share_mealie_down_signed_in_shows_no_nav(login_as, mock_mealie):
    u1, _, _ = shared(login_as, mock_mealie)
    mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.ConnectError("boom")
    r = u1.get(f"/s/{TOKEN}")
    assert r.status_code == 502 and "Can't reach Mealie" in r.text
    assert 'href="/me"' not in r.text and 'class="tabs"' not in r.text and "htmx" not in r.text


def test_expired_share_token_rejected_by_mealie_is_public_404(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.Response(400, json={})
    assert TestClient(app).get(f"/s/{TOKEN}").status_code == 404


def test_share_og_tags(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    t = TestClient(app).get(f"/s/{TOKEN}").text
    assert '<meta property="og:title" content="Chili">' in t
    assert '<meta property="og:description" content="Warm">' in t
    assert f'<meta property="og:image" content="http://testserver/s/{TOKEN}/image">' in t
    long = '"><b>' + "x" * 300
    mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.Response(200, json=RECIPE | {"image": None, "description": long})
    t = TestClient(app).get(f"/s/{TOKEN}").text
    assert "og:image" not in t and 'og:title" content="Chili"' in t
    assert 'content="&#34;&gt;&lt;b&gt;' + "x" * 195 + '">' in t.split("</head>")[0] and "x" * 196 not in t.split("</head>")[0]
    mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.Response(200, json=RECIPE | {"description": ""})
    assert "og:description" not in TestClient(app).get(f"/s/{TOKEN}").text


def test_share_order(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    t = TestClient(app).get(f"/s/{TOKEN}").text
    marks = ['fetchpriority="high"', "<h1", 'class="chip"', ">Warm<", ">Ingredients<", ">Method<", ">Photos<", "<footer"]
    pos = [t.index(m) for m in marks]
    assert pos == sorted(pos)
    assert 'alt=""' in t[t.index("fetchpriority") - 200 : t.index("fetchpriority") + 100]
    mock_mealie[("GET", f"/api/recipes/shared/{TOKEN}")] = httpx.Response(200, json=RECIPE | {"image": None})
    t = TestClient(app).get(f"/s/{TOKEN}").text
    assert "fetchpriority" not in t and 'class="hero' not in t


def test_share_no_app_chrome(login_as, mock_mealie):
    shared(login_as, mock_mealie)
    t = TestClient(app).get(f"/s/{TOKEN}").text
    for bad in ('class="tabs"', "htmx", "manifest", "<script", ' style="', "<style"):
        assert bad not in t, bad
