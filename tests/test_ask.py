import httpx
import pytest

from app import ai, db


def user_row():  # the only user in these tests
    con = db.connect()
    row = con.execute("SELECT * FROM users").fetchone()
    con.close()
    return row


def save(c, **data):
    return c.post("/settings/ai", data={"model": "", "key": ""} | data, follow_redirects=False)


@pytest.fixture
def ai_client(client, mock_ai):
    assert save(client, key="sk-or-test").status_code == 303
    return client


def test_save_key(client, mock_ai):
    r = save(client, key="  sk-or-test  ")
    assert r.status_code == 303 and r.headers["location"] == "/me"
    u = user_row()
    assert (u["ai_provider"], u["ai_model"]) == ("openrouter", "openai/gpt-5-nano")
    assert "sk-or-test" not in u["ai_key_enc"] and ai.decrypt(u["ai_key_enc"]) == "sk-or-test"
    page = client.get("/me").text
    assert "sk-or-test" not in page and "A key is saved" in page


@pytest.mark.parametrize("secret", ["", "dev", "change-me"])
def test_placeholder_secret_refuses(client, mock_ai, monkeypatch, secret):
    monkeypatch.setenv("SECRET_KEY", secret)
    r = save(client, key="sk-or-test")
    assert r.status_code == 200 and "SECRET_KEY" in r.text and user_row()["ai_key_enc"] is None


def test_rejected_key_not_saved(client, mock_ai):
    mock_ai[("GET", "/api/v1/key")] = httpx.Response(401, json={})
    r = save(client, key="sk-or-bad")
    assert "OpenRouter rejected that key." in r.text and user_row()["ai_key_enc"] is None


def test_unverifiable_key_saved(client, mock_ai):
    mock_ai[("GET", "/api/v1/key")] = httpx.Response(500)
    assert save(client, key="sk-or-test").status_code == 303
    assert ai.decrypt(user_row()["ai_key_enc"]) == "sk-or-test"


def test_unknown_model_not_saved(client, mock_ai):
    r = save(client, key="sk-or-test", model="nope/x")
    assert "OpenRouter has no model named nope/x." in r.text and user_row()["ai_key_enc"] is None


def test_limited_model_saved_with_warning(client, mock_ai):
    r = save(client, key="sk-or-test", model="text/only")
    assert "Saved. text/only can&#39;t use tools or read photos, so some features won&#39;t work." in r.text
    assert user_row()["ai_model"] == "text/only"


def test_blank_key_keeps_saved_key(ai_client):
    assert save(ai_client, model="text/only").status_code == 200  # the warning page
    u = user_row()
    assert ai.decrypt(u["ai_key_enc"]) == "sk-or-test" and u["ai_model"] == "text/only"


def test_blank_key_with_none_saved(client, mock_ai):
    assert "Enter your OpenRouter key." in save(client).text


def test_overlong_key_refused(client, mock_ai):
    assert "That doesn&#39;t look like an OpenRouter key." in save(client, key="x" * 301).text


def test_remove_key(ai_client):
    r = save(ai_client, remove="1")
    assert r.status_code == 303 and user_row()["ai_key_enc"] is None
