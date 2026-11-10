import re
from io import BytesIO
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app

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


def test_active_tab(client):
    for path, tab in (("/", "/"), ("/me", "/me"), ("/order", "/order"), ("/ask", "/ask"), ("/invite", "/me")):
        html = client.get(path).text
        assert html.count('aria-current="page"') == 1, path
        assert marked(html) == [tab], path


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
    assert c.get("/s/nope").headers["content-security-policy"] == CSP
    assert "content-security-policy" not in c.get("/login").headers


def test_no_second_footer_bar(client):
    assert 'class="links"' not in client.get("/").text
