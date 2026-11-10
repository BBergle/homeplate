import re
from io import BytesIO
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from tests.test_gallery import setup

TEMPLATES = Path(__file__).parent.parent / "app" / "templates"
CSP = "default-src 'self'; img-src 'self'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"


def test_no_inline_script_or_style():
    for f in TEMPLATES.glob("*.html"):
        t = f.read_text()
        assert not re.search(r"<script(?![^>]*\ssrc=)", t), f.name
        assert 'style="' not in t, f.name


def marked(html: str) -> list[str]:
    """hrefs of the tab-bar links carrying aria-current="page"."""
    nav = re.search(r'<nav class="tabs".*?</nav>', html, re.S).group(0)
    return re.findall(r'<a href="([^"]*)" aria-current="page"', nav)


def test_active_tab(client, mock_mealie):
    setup(mock_mealie)
    for path, tab in (("/", "/"), ("/me", "/me"), ("/order", "/order"), ("/ask", "/ask"), ("/invite", "/me"), ("/r/uuid-1", "/me")):
        html = client.get(path).text
        assert html.count('aria-current="page"') == 1, path
        assert marked(html) == [tab], path
    # re-rendered validation errors keep a tab marked
    for path, data, tab in (("/weight", {"lbs": "5"}, "/"), ("/entries", {"kind": "other"}, "/"), ("/settings", {"weekly_goal": "0"}, "/me")):
        r = client.post(path, data=data)
        assert r.status_code == 200 and marked(r.text) == [tab], path


def test_head_tags(client):
    html = client.get("/").text
    assert re.search(r'<meta name="viewport" content="[^"]*viewport-fit=cover', html)
    assert len(re.findall(r'<meta name="theme-color" content="#[0-9a-f]{6}" media="\(prefers-color-scheme: (light|dark)\)">', html)) == 2
    assert '<meta name="color-scheme" content="light dark">' in html
    assert '<link rel="apple-touch-icon" href="/static/icon-180.png">' in html
    r = client.get("/static/icon-180.png")
    assert r.status_code == 200 and Image.open(BytesIO(r.content)).size == (180, 180)


def test_login_autofill(mock_mealie):
    c = TestClient(app)
    html = c.get("/login").text
    user = re.search(r'<input[^>]*name="username"[^>]*>', html).group(0)
    for a in ('autocomplete="username"', 'autocapitalize="none"', 'autocorrect="off"', 'spellcheck="false"'):
        assert a in user
    assert 'autocomplete="current-password"' in re.search(r'<input[^>]*name="password"[^>]*>', html).group(0)
    mock_mealie[("POST", "/api/auth/token")] = httpx.Response(401, json={})
    r = c.post("/login", data={"username": "u", "password": "bad"})
    assert r.status_code == 401 and 'class="msg msg-error" role="alert"' in r.text


def test_public_csp(mock_mealie):
    c = TestClient(app)
    assert c.get("/join/x").headers["content-security-policy"] == CSP
    assert "content-security-policy" not in c.get("/login").headers


def test_no_csp_when_signed_in(client):
    assert "content-security-policy" not in client.get("/").headers


def test_long_text_classes(client):
    word = "w" * 60
    client.post("/entries", data={"kind": "other", "description": word})
    html = client.get("/").text
    i = html.index(word)
    start = html.rindex('<div class="entry-text">', 0, i)
    assert "</div>" not in html[start:i]
    css = (Path(__file__).parent.parent / "app" / "static" / "app.css").read_text()
    assert re.search(r"\.entry-text\s*\{[^}]*overflow-wrap:\s*anywhere", css)
    assert re.search(r"\.wrap-any\s*\{[^}]*overflow-wrap:\s*anywhere", css)


def test_wrap_any_on_me_row_and_picker(client, mock_mealie):
    word = "w" * 60
    mock_mealie[("GET", "/api/recipes")] = httpx.Response(200, json={"items": [{"id": "r1", "name": word}]})
    setup(mock_mealie)
    assert f'<label class="check wrap-any"><input type="radio" name="recipe_id" value="r1"> {word}' in client.get("/recipes/search?q=w").text
    client.post("/entries", data={"kind": "cooked", "recipe_id": "uuid-1"})
    assert '<span class="wrap-any">' in client.get("/me").text


def test_css_colours_only_in_tokens():
    css = (Path(__file__).parent.parent / "app" / "static" / "app.css").read_text()
    css = re.sub(r":root\s*\{[^}]*\}", "", css)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?)\(", css)


def test_no_second_footer_bar(client):
    assert 'class="links"' not in client.get("/").text


def test_recipe_image_class_does_not_leak_to_today_hero(client, mock_mealie):
    import httpx

    mock_mealie[("GET", "/api/recipes/uuid-1")] = httpx.Response(200, json={"id": "uuid-1", "slug": "c", "name": "C", "image": "x"})
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(200, json={"id": "x", "groupSlug": "home"})
    assert 'class="recipe-hero"' in client.get("/r/uuid-1").text
    css = open("app/static/app.css").read()
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"@media[^{]*\{", "", css)):
        if "aspect-ratio" in body:
            assert not any(s.strip() == ".hero" or s.strip().endswith(" .hero") for s in sel.split(",")), sel
