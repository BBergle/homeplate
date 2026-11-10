import inspect
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from conftest import CHAT, cite, err, reply

from app import ai, ask, auth, db, settings


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
    assert r.status_code == 303 and r.headers["location"] == "/settings"
    u = user_row()
    assert (u["ai_provider"], u["ai_model"]) == ("openrouter", "openai/gpt-5-nano")
    assert "sk-or-test" not in u["ai_key_enc"] and ai.decrypt(u["ai_key_enc"]) == "sk-or-test"
    page = client.get("/settings").text
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
    assert not inspect.iscoroutinefunction(settings.save_ai)  # it calls OpenRouter synchronously, so it must run in the threadpool


def test_non_ascii_key_refused(client, mock_ai):
    r = save(client, key="sk-or-\u200btest")
    assert r.status_code == 200 and "That doesn&#39;t look like an OpenRouter key." in r.text and user_row()["ai_key_enc"] is None


def test_overlong_model_refused(ai_client):
    assert "That doesn&#39;t look like a model name." in save(ai_client, model="m" * 101).text
    assert save(ai_client, model="m" * 100).status_code == 200  # 100 is allowed (unknown model refusal, not length)
    assert 'maxlength="100"' in ai_client.get("/settings").text


def test_unreadable_key_is_not_saved_state(ai_client, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a-different-secret")
    page = ai_client.get("/settings").text
    assert "A key is saved" not in page and "Remove key" not in page
    assert "Enter your OpenRouter key." in save(ai_client).text


def test_settings_ai_section_always_visible(client, mock_ai):
    page = client.get("/settings").text
    assert '<section class="card" id="ai">' in page and "<details" not in page


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
    assert r.status_code == 200 and "Add your AI key" in r.text and 'href="/settings#ai"' in r.text and "<textarea" not in r.text
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
    assert sys["role"] == "system" and auth.local_today().strftime("%A, %B %-d, %Y") in sys["content"]
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


def call(name, args, id="c1"):
    msg = {"role": "assistant", "content": None, "tool_calls": [{"id": id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
    return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": msg}]})


@pytest.fixture
def fake_web(monkeypatch):
    from app import webimg

    monkeypatch.setattr(webimg, "public_https", lambda u: u if ".example/" in u else None)
    monkeypatch.setattr(webimg, "thumbnail", lambda u: b"jpg" if "a.example" in u else None)


def proposals():
    con = db.connect()
    out = con.execute("SELECT * FROM proposals ORDER BY id").fetchall()
    con.close()
    return out


def sequence(mock_ai, *replies):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return replies[min(len(bodies), len(replies)) - 1]

    mock_ai[CHAT] = handler
    return bodies


PROPOSE = call("propose_recipes", {"intro": "Here are two.", "recipes": [
    {"name": "NameA", "url": "https://a.example/r", "why": "wa"},
    {"name": "NameB", "url": "https://b.example/r", "why": "wb"},
]})


@pytest.fixture
def scrape_ok(mock_mealie):
    mock_mealie[("POST", "/api/recipes/test-scrape-url")] = lambda r: httpx.Response(200, json={"image": "https://a.example/i.jpg" if "a.example" in r.content.decode() else None, "recipeIngredient": ["x"]})


def test_lookup_round_then_answer(ai_client, mock_ai, mock_mealie):
    mock_mealie[("GET", "/api/recipes")] = httpx.Response(200, json={"items": [{"id": "i1", "name": "Rolls", "slug": "rolls"}]})
    bodies = sequence(mock_ai, call("search_my_recipes", {"query": "rolls"}), reply("You have one."))
    ai_client.post("/ask", data={"message": "rolls?"}, headers=HX)
    assert len(bodies) == 2
    tail = bodies[1]["messages"][-2:]
    assert tail[0]["tool_calls"][0]["id"] == "c1"
    assert tail[1] == {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"recipes": [{"id": "i1", "name": "Rolls"}]})}
    assert rows()[-1]["content"] == "You have one." and proposals() == []


def test_propose_makes_cards_and_ends_turn(ai_client, mock_ai, scrape_ok, fake_web, data_dir):
    bodies = sequence(mock_ai, PROPOSE)
    ai_client.post("/ask", data={"message": "find"}, headers=HX)
    assert len(bodies) == 1
    answer = rows()[-1]
    assert answer["content"] == "Here are two." and answer["error"] == 0
    a, b = proposals()
    for p in (a, b):
        assert (p["kind"], p["status"], p["message_id"], p["user_id"]) == ("recipe", "open", answer["id"], "u1")
        assert set(json.loads(p["payload"])) == {"name", "url", "host", "why", "importable", "photo"}
    assert json.loads(a["payload"])["photo"] is True and json.loads(b["payload"])["photo"] is False
    assert (data_dir / "cards" / f"{a['id']}.jpg").read_bytes() == b"jpg" and not (data_dir / "cards" / f"{b['id']}.jpg").exists()


def test_propose_with_no_usable_recipe(ai_client, mock_ai, mock_mealie, fake_web):
    sequence(mock_ai, call("propose_recipes", {"intro": "x", "recipes": [{"name": "P", "url": "https://10.0.0.1/r", "why": "w"}]}))
    ai_client.post("/ask", data={"message": "find"}, headers=HX)
    last = rows()[-1]
    assert last["content"] == "I found recipes but couldn't read their pages. Ask again." and last["error"] == 1 and proposals() == []


def test_six_rounds_then_stop(ai_client, mock_ai, mock_mealie):
    mock_mealie[("GET", "/api/recipes")] = httpx.Response(200, json={"items": []})
    bodies = sequence(mock_ai, call("search_my_recipes", {"query": "x"}))
    ai_client.post("/ask", data={"message": "go"}, headers=HX)
    assert len(bodies) == ask.ROUNDS == 6
    last = rows()[-1]
    assert last["content"] == "That took too many steps. Ask again more simply." and last["error"] == 1


def test_tools_use_the_askers_token(ai_client, mock_ai, mock_mealie):
    seen = []

    def search(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"items": []})

    mock_mealie[("GET", "/api/recipes")] = search
    sequence(mock_ai, call("search_my_recipes", {"query": "x"}), reply("ok"))
    ai_client.post("/ask", data={"message": "go"}, headers=HX)
    assert seen == ["Bearer tok-u1"]


def test_next_turn_tells_the_model_what_it_showed(ai_client, mock_ai, scrape_ok, fake_web):
    bodies = sequence(mock_ai, PROPOSE, reply("ok"))
    ai_client.post("/ask", data={"message": "find"}, headers=HX)
    ai_client.post("/ask", data={"message": "thanks"}, headers=HX)
    assert bodies[1]["messages"][2] == {"role": "assistant", "content": "Here are two.\n[Shown as cards: 1. NameA (https://a.example/r); 2. NameB (https://b.example/r)]"}


def test_system_prompt_mentions_cards(ai_client, mock_ai):
    bodies = sequence(mock_ai, reply("ok"))
    ai_client.post("/ask", data={"message": "hi"}, headers=HX)
    assert "propose_recipes" in bodies[0]["messages"][0]["content"]


def test_proposal_wins_over_lookup_in_same_reply(ai_client, mock_ai, scrape_ok, fake_web):
    calls = json.loads(PROPOSE.content)["choices"][0]["message"]["tool_calls"] + [
        {"id": "c2", "type": "function", "function": {"name": "search_my_recipes", "arguments": '{"query": "x"}'}}]
    msg = {"role": "assistant", "content": None, "tool_calls": calls[1:] + calls[:1]}  # look-up listed first
    bodies = sequence(mock_ai, httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": msg}]}))
    ai_client.post("/ask", data={"message": "find"}, headers=HX)
    assert len(bodies) == 1 and rows()[-1]["content"] == "Here are two." and len(proposals()) == 2


def test_private_image_is_never_fetched(ai_client, mock_ai, mock_mealie, fake_web, monkeypatch):
    from app import webimg

    fetched = []
    monkeypatch.setattr(webimg, "thumbnail", lambda u: fetched.append(u))
    mock_mealie[("POST", "/api/recipes/test-scrape-url")] = httpx.Response(200, json={"image": "https://10.0.0.1/i.jpg", "recipeIngredient": ["x"]})
    sequence(mock_ai, PROPOSE)
    ai_client.post("/ask", data={"message": "find"}, headers=HX)
    assert fetched == [] and json.loads(proposals()[0]["payload"])["photo"] is False


def test_no_database_write_while_fetching_photos(ai_client, mock_ai, scrape_ok, fake_web, monkeypatch):
    from app import webimg

    def thumb(url):
        con = db.connect()  # a second writer must not be blocked by an open transaction
        con.execute("PRAGMA busy_timeout = 0")
        con.execute("INSERT INTO chat_messages (user_id, role, content, created_at) VALUES ('u1', 'user', 'x', 'now')")
        con.commit()
        con.close()
        return b"jpg"

    monkeypatch.setattr(webimg, "thumbnail", thumb)
    sequence(mock_ai, PROPOSE)
    ai_client.post("/ask", data={"message": "find"}, headers=HX)
    assert len(proposals()) == 2


def test_photo_write_failure_clears_photo_flag(ai_client, mock_ai, scrape_ok, fake_web, data_dir):
    (data_dir / "cards").write_text("in the way")  # the folder cannot be made
    sequence(mock_ai, PROPOSE)
    ai_client.post("/ask", data={"message": "find"}, headers=HX)
    a, b = proposals()
    assert rows()[-1]["content"] == "Here are two." and json.loads(a["payload"])["photo"] is False


@pytest.mark.parametrize("out", [httpx.ConnectError("down"), httpx.Response(401, json={})])
def test_mealie_down_while_building_cards(ai_client, mock_ai, mock_mealie, fake_web, out):
    mock_mealie[("POST", "/api/recipes/test-scrape-url")] = out
    sequence(mock_ai, PROPOSE)
    ai_client.post("/ask", data={"message": "find"}, headers=HX)
    last = rows()[-1]
    assert last["content"] == "Can't reach your recipe library to check those recipes. Try again." and last["error"] == 1 and proposals() == []


def test_new_chat_deletes_proposals_and_photos(ai_client, mock_ai, scrape_ok, fake_web, data_dir):
    sequence(mock_ai, PROPOSE)
    ai_client.post("/ask", data={"message": "find"}, headers=HX)
    pid = proposals()[0]["id"]
    assert (data_dir / "cards" / f"{pid}.jpg").exists()
    ai_client.post("/ask/new", follow_redirects=False)
    assert proposals() == [] and not (data_dir / "cards" / f"{pid}.jpg").exists()


def test_new_chat_keeps_other_persons_cards(ai_client, login_as, data_dir):
    other = login_as("u2")
    add_card(user_id="u2", photo=True)
    (data_dir / "cards").mkdir()
    (data_dir / "cards" / "1.jpg").write_bytes(b"x")
    ai_client.post("/ask/new", follow_redirects=False)
    assert len(proposals()) == 1 and (data_dir / "cards" / "1.jpg").exists()


def test_shown_notes_are_per_person(ai_client, mock_ai, scrape_ok, fake_web):
    bodies = sequence(mock_ai, reply("A1"), reply("A2"))
    ai_client.post("/ask", data={"message": "Q1"}, headers=HX)
    mid = rows()[-1]["id"]
    con = db.connect()
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("INSERT INTO proposals (user_id, message_id, kind, payload, created_at) VALUES ('u2', ?, 'recipe', ?, 'now')",
                (mid, json.dumps({"name": "Other", "url": "https://o.example/r"})))
    con.commit()
    con.close()
    ai_client.post("/ask", data={"message": "Q2"}, headers=HX)
    assert bodies[1]["messages"][2] == {"role": "assistant", "content": "A1"}


def add_card(status="open", hours_ago=0, importable=True, photo=False, user_id="u1", result=None, **payload):
    at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    body = {"name": "Soup", "url": "https://r.example/soup", "host": "r.example", "why": "Easy.", "importable": importable, "photo": photo} | payload
    con = db.connect()
    mid = con.execute("INSERT INTO chat_messages (user_id, role, content, created_at) VALUES (?, 'assistant', 'Here.', ?)", (user_id, at)).lastrowid
    cid = con.execute("INSERT INTO proposals (user_id, message_id, kind, payload, status, result, created_at) VALUES (?, ?, 'recipe', ?, ?, ?, ?)",
                      (user_id, mid, json.dumps(body), status, result, at)).lastrowid
    con.commit()
    con.close()
    return cid


def card_row(cid):
    con = db.connect()
    r = con.execute("SELECT * FROM proposals WHERE id = ?", (cid,)).fetchone()
    con.close()
    return r


@pytest.fixture
def imports(mock_mealie):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json="the-slug")

    mock_mealie[("POST", "/api/recipes/create/url")] = handler
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(200, json={"id": "u1", "fullName": "U", "groupSlug": "home"})
    return calls


@pytest.fixture
def mealie_url(monkeypatch):
    monkeypatch.setitem(auth.templates.env.globals, "mealie_url", "https://cook.example")


def test_cards_render_under_their_answer(ai_client, mealie_url):
    a = add_card(photo=True)
    html = ai_client.get("/ask/chat").text
    assert "Soup" in html and "r.example" in html and "Easy." in html
    assert f'hx-post="/ask/cards/{a}"' in html and f'hx-target="#rcard-{a}"' in html and 'hx-swap="outerHTML"' in html and ">Add</button>" in html
    assert 'hx-disabled-elt="find button"' in html
    assert '<a class="rcard-link" href="https://r.example/soup" target="_blank" rel="noopener noreferrer">Open page</a>' in html
    assert f'<img class="rcard-photo" src="/ask/cards/{a}/photo" alt="" loading="lazy">' in html
    add_card(importable=False)
    add_card(hours_ago=25)
    add_card(status="done", result="g/home/r/the-slug")
    add_card(status="working")
    add_card(status="failed", result="Mealie couldn't read that page.")
    html = ai_client.get("/ask/chat").text
    for s in ("Mealie can't import this page.", "Expired, ask again.", "Added to your recipes.", 'href="https://cook.example/g/home/r/the-slug" target="_blank" rel="noopener noreferrer">Open in Mealie</a>',
              "Still adding. Check your recipes in a minute.", "Mealie couldn&#39;t read that page."):
        assert s in html
    assert html.count("<img") == 1


def test_card_without_photo_or_form_when_not_open(ai_client):
    add_card(importable=False)
    add_card(hours_ago=25)
    add_card(status="done", result="s")
    html = ai_client.get("/ask/chat").text
    assert "<img" not in html and 'hx-post="/ask/cards/' not in html


def test_card_text_is_escaped(ai_client):
    add_card(name="<script>x</script>")
    html = ai_client.get("/ask/chat").text
    assert "&lt;script&gt;" in html and "<script>x" not in html


def test_add_imports_once(ai_client, imports, mealie_url):
    a = add_card()
    r = ai_client.post(f"/ask/cards/{a}", headers=HX)
    assert r.status_code == 200 and "Added to your recipes." in r.text and r.text.lstrip().startswith("<li")
    assert imports == [{"url": "https://r.example/soup", "includeTags": False}]
    ai_client.post(f"/ask/cards/{a}", headers=HX)
    assert len(imports) == 1 and card_row(a)["status"] == "done" and card_row(a)["result"] == "g/home/r/the-slug"
    assert 'href="https://cook.example/g/home/r/the-slug"' in ai_client.get("/ask/chat").text


def test_added_card_has_no_link_without_mealie_url(ai_client, imports, monkeypatch):
    monkeypatch.setitem(auth.templates.env.globals, "mealie_url", "")
    a = add_card()
    r = ai_client.post(f"/ask/cards/{a}", headers=HX)
    assert "Added to your recipes." in r.text and "Open in Mealie" not in r.text and "<a " not in r.text.split("Added to your recipes.")[1].split("</p>")[0]


def test_group_lookup_failure_keeps_the_import(ai_client, imports, mock_mealie, mealie_url):
    mock_mealie[("GET", "/api/users/self")] = httpx.Response(500)
    a = add_card()
    r = ai_client.post(f"/ask/cards/{a}", headers=HX)
    assert "Added to your recipes." in r.text and "Open in Mealie" not in r.text
    assert len(imports) == 1 and card_row(a)["status"] == "done" and not card_row(a)["result"]
    ai_client.post(f"/ask/cards/{a}", headers=HX)
    assert len(imports) == 1


def test_add_ignores_posted_address(ai_client, imports):
    a = add_card()
    ai_client.post(f"/ask/cards/{a}", data={"url": "https://evil.example"}, headers=HX)
    assert imports == [{"url": "https://r.example/soup", "includeTags": False}]


def test_add_refused_page(ai_client, mock_mealie):
    calls = []
    mock_mealie[("POST", "/api/recipes/create/url")] = lambda req: calls.append(1) or httpx.Response(400, json={})
    a = add_card()
    r = ai_client.post(f"/ask/cards/{a}", headers=HX)
    assert card_row(a)["status"] == "failed" and "Mealie couldn&#39;t read that page." in r.text
    ai_client.post(f"/ask/cards/{a}", headers=HX)
    assert len(calls) == 1


def test_add_mealie_down(ai_client, mock_mealie):
    mock_mealie[("POST", "/api/recipes/create/url")] = httpx.ConnectError("down")
    a = add_card()
    r = ai_client.post(f"/ask/cards/{a}", headers=HX)
    assert card_row(a)["status"] == "open" and "Can&#39;t reach Mealie. Try again." in r.text and "Add</button>" in r.text
    assert "Can&#39;t reach Mealie" not in ai_client.get("/ask/chat").text


def test_add_expired_or_not_importable(ai_client, imports):
    a, b = add_card(hours_ago=25), add_card(importable=False)
    for cid in (a, b):
        r = ai_client.post(f"/ask/cards/{cid}", headers=HX)
        assert r.status_code == 200 and card_row(cid)["status"] == "open"
    assert imports == []  # the mock records every import call: none was made
    assert "Expired, ask again." in ai_client.post(f"/ask/cards/{a}", headers=HX).text


def test_add_session_expired(ai_client, mock_mealie):
    mock_mealie[("POST", "/api/recipes/create/url")] = httpx.Response(401, json={})
    a = add_card()
    r = ai_client.post(f"/ask/cards/{a}", headers=HX, follow_redirects=False)
    assert card_row(a)["status"] == "open" and r.status_code in (303, 200) and "/login" in (r.headers.get("location", "") + r.headers.get("hx-redirect", ""))


def test_other_persons_card(ai_client, login_as, imports):
    login_as("u2")
    a = add_card(user_id="u2", photo=True)
    assert ai_client.post(f"/ask/cards/{a}", headers=HX).status_code == 404
    assert ai_client.get(f"/ask/cards/{a}/photo").status_code == 404
    assert ai_client.post("/ask/cards/999").status_code == 404
    assert imports == [] and card_row(a)["status"] == "open"


def test_photo_route(ai_client, data_dir):
    a = add_card(photo=True)
    assert ai_client.get(f"/ask/cards/{a}/photo").status_code == 404
    (data_dir / "cards").mkdir()
    (data_dir / "cards" / f"{a}.jpg").write_bytes(b"\xff\xd8jpg")
    r = ai_client.get(f"/ask/cards/{a}/photo")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.headers["cache-control"] == "private, max-age=86400"


def test_plain_post_redirects_to_ask(ai_client, imports):
    a = add_card()
    r = ai_client.post(f"/ask/cards/{a}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ask" and card_row(a)["status"] == "done"
