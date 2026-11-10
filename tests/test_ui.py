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


def test_head_tags(client):
    html = client.get("/ask").text
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
    assert "content-security-policy" not in client.get("/ask").headers


def test_css_colours_only_in_tokens():
    css = (Path(__file__).parent.parent / "app" / "static" / "app.css").read_text()
    css = re.sub(r":root\s*\{[^}]*\}", "", css)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?)\(", css)


def test_no_second_footer_bar(client):
    assert 'class="links"' not in client.get("/ask").text


def test_hint_only_hidden_when_empty():
    css = (Path(__file__).parent.parent / "app" / "static" / "app.css").read_text()
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if ".hint" in sel and re.search(r"display:\s*none", body):
            assert all(s.strip().endswith(".hint:empty") for s in sel.split(",")), sel
