import inspect
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from conftest import CHAT, cite, err, reply

from app import ai, ask, db, today


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


def test_save_ai_does_not_block_the_event_loop():
    assert not inspect.iscoroutinefunction(ask.save_ai)  # it calls OpenRouter synchronously, so it must run in the threadpool


def test_non_ascii_key_refused(client, mock_ai):
    r = save(client, key="sk-or-\u200btest")
    assert r.status_code == 200 and "That doesn&#39;t look like an OpenRouter key." in r.text and user_row()["ai_key_enc"] is None


def test_overlong_model_refused(ai_client):
    assert "That doesn&#39;t look like a model name." in save(ai_client, model="m" * 101).text
    assert save(ai_client, model="m" * 100).status_code == 200  # 100 is allowed (unknown model refusal, not length)
    assert 'maxlength="100"' in ai_client.get("/me").text


def test_unreadable_key_is_not_saved_state(ai_client, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a-different-secret")
    page = ai_client.get("/me").text
    assert "A key is saved" not in page and "Remove key" not in page
    assert "Enter your OpenRouter key." in save(ai_client).text


def test_me_ai_section_open_on_query(client, mock_ai):
    assert re.search(r'<details[^>]*id="ai"[^>]*\sopen', client.get("/me?ai=1").text)
    assert not re.search(r'<details[^>]*id="ai"[^>]*\sopen', client.get("/me").text)


def test_refused_save_keeps_typed_model(client, mock_ai):
    r = save(client, key="sk-or-test", model="nope/x")
    assert 'name="model" value="nope/x"' in r.text and user_row()["ai_model"] is None


def test_remove_key(ai_client):
    r = save(ai_client, remove="1")
    assert r.status_code == 303 and user_row()["ai_key_enc"] is None


HX = {"HX-Request": "true"}


def rows():
    con = db.connect()
    out = con.execute("SELECT * FROM chat_messages ORDER BY id").fetchall()
    con.close()
    return out


def add_row(role, content, minutes_ago=0, error=0, user_id="u1"):
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    con = db.connect()
    con.execute("INSERT INTO chat_messages (user_id, role, content, error, created_at) VALUES (?, ?, ?, ?, ?)", (user_id, role, content, error, at))
    con.commit()
    con.close()


def test_no_key_page(client, mock_ai):
    r = client.get("/ask")
    assert r.status_code == 200 and "Add your AI key" in r.text and 'href="/me?ai=1#ai"' in r.text and "<textarea" not in r.text
    assert client.post("/ask", data={"message": "hi"}, follow_redirects=False).status_code == 303 and rows() == []
    assert client.get("/ask/chat", follow_redirects=False).status_code == 303


def test_no_key_htmx_gets_hx_redirect(client, mock_ai):
    for r in (client.get("/ask/chat", headers=HX, follow_redirects=False), client.post("/ask", data={"message": "hi"}, headers=HX, follow_redirects=False)):
        assert r.status_code == 200 and r.headers["HX-Redirect"] == "/ask" and "<html" not in r.text
    assert rows() == []


def test_key_unreadable_after_secret_change(ai_client, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a-different-secret")
    r = ai_client.get("/ask")
    assert r.status_code == 200 and "Add your AI key" in r.text


def test_ask_and_answer(ai_client, mock_ai):
    mock_ai[CHAT] = reply("Use bread flour.", [cite("https://k.com/r", "King Arthur")])
    r = ai_client.post("/ask", data={"message": "Best flour for rolls?"}, headers=HX)
    assert r.status_code == 200 and "Best flour for rolls?" in r.text and "Thinking" in r.text
    assert 'hx-trigger="every 3s"' in r.text and "disabled" in r.text
    done = ai_client.get("/ask/chat").text  # TestClient runs the background task before returning
    assert "Use bread flour." in done and "Thinking" not in done and "every 3s" not in done and "disabled" not in done
    assert '<a href="https://k.com/r" target="_blank" rel="noopener noreferrer">King Arthur</a>' in done
    full = ai_client.get("/ask").text
    assert "Use bread flour." in full and 'action="/ask/new"' in done


def test_messages_sent_to_model(ai_client, mock_ai):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return reply("A1")

    mock_ai[CHAT] = handler
    ai_client.post("/ask", data={"message": "Q1"}, headers=HX)
    add_row("assistant", "Your OpenRouter account is out of credit.", error=1)
    ai_client.post("/ask", data={"message": "Q2"}, headers=HX)
    sys = bodies[0]["messages"][0]
    assert sys["role"] == "system" and today.local_today().strftime("%A, %B %-d, %Y") in sys["content"]
    assert bodies[0]["messages"][1:] == [{"role": "user", "content": "Q1"}]
    assert bodies[1]["messages"][1:] == [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"}, {"role": "user", "content": "Q2"}]
    assert bodies[1]["model"] == "openai/gpt-5-nano"


def test_history_capped(ai_client, mock_ai):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return reply("ok")

    mock_ai[CHAT] = handler
    for i in range(30):
        add_row("user" if i % 2 == 0 else "assistant", f"old{i}", minutes_ago=100 - i)
    ai_client.post("/ask", data={"message": "new"}, headers=HX)
    msgs = bodies[0]["messages"]
    assert len(msgs) == 1 + ask.HISTORY and msgs[-1] == {"role": "user", "content": "new"}
    assert msgs[1]["content"] == "old11"


def test_provider_error_shown(ai_client, mock_ai):
    mock_ai[CHAT] = err(402)
    ai_client.post("/ask", data={"message": "Q"}, headers=HX)
    t = ai_client.get("/ask/chat").text
    assert "out of credit" in t and "chat-error" in t and rows()[-1]["error"] == 1


def test_unexpected_failure_does_not_hang(ai_client, monkeypatch):
    def boom(*a):
        raise RuntimeError("nope")

    monkeypatch.setattr(ai, "chat", boom)
    ai_client.post("/ask", data={"message": "Q"}, headers=HX)
    t = ai_client.get("/ask/chat").text
    assert "The AI service didn&#39;t answer. Try again." in t and "every 3s" not in t and rows()[-1]["error"] == 1


def test_answer_is_escaped(ai_client, mock_ai):
    mock_ai[CHAT] = reply("<script>alert(1)</script>")
    ai_client.post("/ask", data={"message": "Q"}, headers=HX)
    t = ai_client.get("/ask/chat").text
    assert "&lt;script&gt;" in t and "<script>alert" not in t


def test_second_message_while_waiting_is_ignored(ai_client, mock_ai):
    add_row("user", "Q1")
    add_row("assistant", None)
    ai_client.post("/ask", data={"message": "Q2"}, headers=HX)
    assert [r["content"] for r in rows()] == ["Q1", None]


def test_stale_wait_becomes_error(ai_client, mock_ai):
    add_row("user", "Q1", minutes_ago=10)
    add_row("assistant", None, minutes_ago=10)
    t = ai_client.get("/ask/chat").text
    assert "That took too long. Ask again." in t and "every 3s" not in t and "disabled" not in t
    mock_ai[CHAT] = reply("ok")
    ai_client.post("/ask", data={"message": "Q2"}, headers=HX)  # the form works again
    assert [r["content"] for r in rows()][-2:] == ["Q2", "ok"]


def test_blank_and_long_messages(ai_client, mock_ai):
    mock_ai[CHAT] = reply("ok")
    ai_client.post("/ask", data={"message": "   "}, headers=HX)
    assert rows() == []
    ai_client.post("/ask", data={"message": "x" * 5000}, headers=HX)
    assert rows()[0]["content"] == "x" * 4000


def test_plain_post_redirects(ai_client, mock_ai):
    mock_ai[CHAT] = reply("ok")
    r = ai_client.post("/ask", data={"message": "Q"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ask" and len(rows()) == 2


def test_conversations_are_private(ai_client, login_as, mock_ai):
    add_row("user", "secret question")
    other = login_as("u2")
    assert save(other, key="sk-or-two").status_code == 303
    assert "secret question" not in other.get("/ask/chat").text
    assert "secret question" in ai_client.get("/ask/chat").text


def test_new_chat(ai_client, login_as, mock_ai):
    add_row("user", "mine")
    other = login_as("u2")
    assert save(other, key="sk-or-two").status_code == 303
    add_row("user", "theirs", user_id="u2")
    r = ai_client.post("/ask/new", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ask"
    assert [(r["user_id"], r["content"]) for r in rows()] == [("u2", "theirs")]


def test_concurrent_second_message_is_ignored(ai_client, mock_ai, monkeypatch):
    # the race: the second request read "not waiting" before the first one's rows landed
    add_row("user", "Q1")
    add_row("assistant", None)
    monkeypatch.setattr(ask, "_conversation", lambda uid: [])
    ai_client.post("/ask", data={"message": "Q2"}, headers=HX)
    assert [r["content"] for r in rows()] == ["Q1", None]
