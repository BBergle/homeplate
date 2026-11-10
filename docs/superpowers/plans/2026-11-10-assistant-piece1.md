# Assistant piece 1 (key, settings, plain questions with search) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person saves their own OpenRouter key in Settings and asks questions on the Ask tab, getting an answer with web sources.

**Architecture:** One new module talks to OpenRouter (`app/ai.py`), one holds the Ask tab and the AI settings route (`app/ask.py`). The answer is fetched in a FastAPI background task and the page polls for it, because an answer takes 5 to 20 seconds with the settings below, far longer with other models a person may pick, and later pieces add several look-up rounds; a phone or a reverse proxy will drop a request held that long. No tools, proposals or photos yet: those are pieces 2 and 3.

**Tech Stack:** FastAPI, Jinja2, htmx 2 (vendored), sqlite3, httpx, cryptography (Fernet). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-09-assistant.md` (read "Live test results" first). Request formats: `docs/research/2026-11-09-ai-providers.md` section 1.

## Global Constraints

- Each person uses their own key. Without one, the Ask tab shows an "add your key in Settings" page and everything else works.
- The app refuses to save a key while `SECRET_KEY` is unset or is `dev` or `change-me`, and says why.
- The key is never shown again after saving, and never written to a log or a template.
- Default model: `openai/gpt-5-nano`.
- Weight is never sent to the model. In this piece nothing but the system prompt and the conversation is sent.
- The model is told today's date in the app's timezone (`today.local_today()`).
- Every OpenRouter chat request sends `"max_tokens": 4000`, `"reasoning": {"effort": "low"}` and the tool `{"type":"openrouter:web_search","parameters":{"engine":"parallel","mode":"turbo","max_results":5}}` (measured: 5 to 9 seconds and about 0.13 cents a question, against 20 to 105 seconds and 1 to 4 cents with the default engine).
- Chat calls get a 180 second time limit. Other OpenRouter calls keep 10 seconds.
- New page elements get their own CSS class names. Do not restyle `.card`, `.msg`, `.hint`, `.hero` or other shared classes.
- Work on branch `assistant`. `.venv/bin/pytest -q` must pass at every commit (193 tests before this plan).

## Review Focus

1. `SECRET_KEY` changed after a key was saved: the Ask tab shows the add-key page, not an error. (Task 3 test)
2. A source address that is not http or https (for example `javascript:`): dropped, never rendered as a link. (Task 1 test)
3. A second message sent while the first is still being answered (double tap): ignored, one question stored. (Task 3 test)
4. The server restarts mid-answer: the waiting bubble becomes "That took too long. Ask again." after 5 minutes and the form works again. (Task 3 test)
5. OpenRouter answers 200 with an `error` body, or with empty text: a plain sentence, never a blank bubble. (Task 1 test)

---

### Task 1: OpenRouter client and key encryption

**Files:**
- Create: `app/ai.py`
- Modify: `tests/conftest.py` (add `mock_ai`)
- Test: `tests/test_ai.py`

**Interfaces:**
- Produces, all in `app/ai.py`:
  - `DEFAULT_MODEL = "openai/gpt-5-nano"`
  - `client = httpx.Client(base_url="https://openrouter.ai/api/v1", timeout=10)` (module global, so tests can replace it, as `mealie.client` is)
  - `class AIError(Exception)`: `str(e)` is a sentence fit to show the person
  - `secret_ok() -> bool`
  - `encrypt(text: str) -> str`, `decrypt(token: str | None) -> str | None` (None when missing or not readable with the current `SECRET_KEY`)
  - `check_key(key: str) -> bool | None` (True accepted, False rejected, None could not tell)
  - `model_check(model: str) -> tuple[bool, str | None]` (known, warning)
  - `chat(key: str, model: str, messages: list[dict]) -> dict` returning `{"text": str, "sources": [{"url": str, "title": str}]}`; raises `AIError`
- Produces in `tests/conftest.py`: fixture `mock_ai`, a dict of `(method, path) -> httpx.Response | Exception | callable(request) -> httpx.Response`, installed on `ai.client` with `httpx.MockTransport`. It sets `SECRET_KEY=test-secret-key` and starts with:
  - `("GET", "/api/v1/key")`: 200 `{"data": {}}`
  - `("GET", "/api/v1/models")`: 200 `{"data": [{"id": "openai/gpt-5-nano", "architecture": {"input_modalities": ["text", "image"]}, "supported_parameters": ["tools"]}, {"id": "text/only", "architecture": {"input_modalities": ["text"]}, "supported_parameters": []}]}`

- [ ] **Step 1: Add `mock_ai` to `tests/conftest.py`** as described above.

- [ ] **Step 2: Write the failing tests in `tests/test_ai.py`**

```python
def reply(content="Hi", annotations=None, finish="stop"):
    msg = {"role": "assistant", "content": content} | ({"annotations": annotations} if annotations else {})
    return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": msg}]})

def cite(url, title=None):
    return {"type": "url_citation", "url_citation": {"url": url} | ({"title": title} if title else {})}

CHAT = ("POST", "/api/v1/chat/completions")

def test_encrypt_round_trip_and_changed_secret(mock_ai, monkeypatch):
    tok = ai.encrypt("sk-or-abc")
    assert "sk-or-abc" not in tok and ai.decrypt(tok) == "sk-or-abc"
    assert ai.decrypt(None) is None and ai.decrypt("garbage") is None
    monkeypatch.setenv("SECRET_KEY", "a-different-secret")
    assert ai.decrypt(tok) is None

@pytest.mark.parametrize("value,ok", [(None, False), ("", False), ("dev", False), ("change-me", False), ("x" * 32, True)])
def test_secret_ok(monkeypatch, value, ok): ...  # set or delete SECRET_KEY, assert ai.secret_ok() is ok

def test_chat_request_and_result(mock_ai):
    seen = {}
    def handler(request):
        seen["auth"], seen["body"] = request.headers["authorization"], json.loads(request.content)
        return reply("Hello", [cite("https://k.com/r", "King Arthur")])
    mock_ai[CHAT] = handler
    msgs = [{"role": "user", "content": "hi"}]
    assert ai.chat("sk-or-abc", "openai/gpt-5-nano", msgs) == {"text": "Hello", "sources": [{"url": "https://k.com/r", "title": "King Arthur"}]}
    assert seen["auth"] == "Bearer sk-or-abc"
    assert seen["body"] == {"model": "openai/gpt-5-nano", "max_tokens": 4000, "reasoning": {"effort": "low"}, "messages": msgs,
                            "tools": [{"type": "openrouter:web_search", "parameters": {"engine": "parallel", "mode": "turbo", "max_results": 5}}]}

def test_chat_cleans_text_and_sources(mock_ai):
    mock_ai[CHAT] = reply(
        "Try this ([k.com](https://k.com/r?utm_source=openai)). See [King Arthur](https://k.com/r).",
        [cite("https://k.com/r?utm_source=openai&x=1"), cite("https://k.com/r?x=1", "dup"),
         cite("javascript:alert(1)", "bad"), cite("ftp://k.com/f", "bad")] + [cite(f"https://s{i}.com/") for i in range(10)])
    out = ai.chat("k", "m", [])
    assert out["text"] == "Try this. See King Arthur."
    assert out["sources"][0] == {"url": "https://k.com/r?x=1", "title": "k.com"}
    assert len(out["sources"]) == 8 and all(s["url"].startswith("https://") for s in out["sources"])

def err(status, **meta): return httpx.Response(status, json={"error": {"code": status, "message": "x", "metadata": meta}})

@pytest.mark.parametrize("response,text", [
    (err(401), "OpenRouter rejected your key. Check it in Settings."),
    (err(402), "Your OpenRouter account is out of credit."),
    (err(402, reason="in_flight_budget_exhausted"), "OpenRouter is still settling your last requests. Try again in a couple of minutes."),
    (err(429), "The AI service is busy. Try again in a minute."),
    (err(404), "OpenRouter couldn't use the model m. Check it in Settings."),
    (err(500), "The AI service didn't answer. Try again."),
    (httpx.ConnectError("down"), "The AI service didn't answer. Try again."),
    (httpx.Response(200, json={"error": {"code": 402, "message": "x"}}), "Your OpenRouter account is out of credit."),
    (httpx.Response(200, text="not json"), "The AI service didn't answer. Try again."),
    (reply("", finish="length"), "The answer was cut off. Ask again, or ask for something shorter."),
    (reply(None), "The AI service didn't answer. Try again."),
])
def test_chat_errors(mock_ai, response, text):
    mock_ai[CHAT] = response
    with pytest.raises(ai.AIError) as e:
        ai.chat("k", "m", [])
    assert str(e.value) == text

def test_check_key(mock_ai):
    assert ai.check_key("k") is True
    mock_ai[("GET", "/api/v1/key")] = err(401);  assert ai.check_key("k") is False
    mock_ai[("GET", "/api/v1/key")] = httpx.ConnectError("down");  assert ai.check_key("k") is None

def test_model_check(mock_ai):
    assert ai.model_check("openai/gpt-5-nano") == (True, None)
    assert ai.model_check("text/only") == (True, "can't use tools or read photos")
    assert ai.model_check("nope/x") == (False, None)
    mock_ai[("GET", "/api/v1/models")] = httpx.ConnectError("down")
    assert ai.model_check("nope/x") == (True, None)
```

- [ ] **Step 3: Run** `.venv/bin/pytest tests/test_ai.py -q`. Expected: fails, `app.ai` does not exist.

- [ ] **Step 4: Implement `app/ai.py`.** Decisions the tests do not fix:
  - Fernet key: `base64.urlsafe_b64encode(hashlib.sha256(b"ai-key:" + SECRET_KEY.encode()).digest())`, read from the environment on each call.
  - `chat` passes `timeout=180` on the request. The error is chosen from the code in the body's `error` when there is one, otherwise the HTTP status.
  - Text cleaning, in this order: remove a parenthesised citation with the space before it (`\s*\(\[[^\]]*\]\([^)]*\)\)`), then replace `[label](http…)` with `label`, then strip.
  - Sources: only `http` and `https`; drop the `utm_source` query parameter; drop duplicates after that; title falls back to the host name; keep the first 8.
  - `model_check` warning is one of `can't use tools`, `can't read photos`, `can't use tools or read photos`, from `supported_parameters` lacking `tools` and `architecture.input_modalities` lacking `image`.

- [ ] **Step 5: Run** `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 6: Commit** `git add app/ai.py tests/conftest.py tests/test_ai.py && git commit -m "feat: OpenRouter client and AI key encryption"`

---

### Task 2: AI settings on the Me page

**Files:**
- Create: `app/ask.py` (router; this task adds only `POST /settings/ai`)
- Modify: `app/db.py` (column), `app/main.py` (include `ask.router`), `app/me.py` (`_page` gains `ai_msg`), `app/templates/me.html`, `app/static/app.css`, `docker-compose.yml`, `README.md`
- Test: `tests/test_ask.py`

**Interfaces:**
- Consumes: `ai.secret_ok`, `ai.encrypt`, `ai.decrypt`, `ai.check_key`, `ai.model_check`, `ai.DEFAULT_MODEL`, fixture `mock_ai`.
- Produces:
  - `users.ai_model TEXT` via `add_column_if_missing(con, "users", "ai_model", "TEXT")`. `ai_provider` is set to `"openrouter"` on save.
  - `me._page(request, user, error=None, ai_msg=None)`; `me.html` shows `ai_msg` inside the AI section and opens it.
  - `POST /settings/ai` with form fields `model`, `key`, and `remove` (present only when the Remove button was pressed).
  - `me.html`: `<details class="card more" id="ai">` titled "AI assistant", after the Settings section.
  - Fixture `ai_client` in `tests/test_ask.py`: the `client` after a successful `POST /settings/ai` with `{"model": "", "key": "sk-or-test"}`.

- [ ] **Step 1: Write the failing tests in `tests/test_ask.py`**

```python
def user_row():  # the only user in these tests
    con = db.connect(); row = con.execute("SELECT * FROM users").fetchone(); con.close(); return row

def save(c, **data): return c.post("/settings/ai", data={"model": "", "key": ""} | data, follow_redirects=False)

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

def test_rejected_key_not_saved(client, mock_ai):   # ("GET", "/api/v1/key") -> 401
    ...  assert "OpenRouter rejected that key." in r.text and user_row()["ai_key_enc"] is None

def test_unknown_model_not_saved(client, mock_ai):
    r = save(client, key="sk-or-test", model="nope/x")
    assert "OpenRouter has no model named nope/x." in r.text and user_row()["ai_key_enc"] is None

def test_limited_model_saved_with_warning(client, mock_ai):
    r = save(client, key="sk-or-test", model="text/only")
    assert "Saved. text/only can&#39;t use tools or read photos, so some features won&#39;t work." in r.text
    assert user_row()["ai_model"] == "text/only"

def test_blank_key_keeps_saved_key(ai_client):
    assert save(ai_client, model="text/only").status_code == 200   # the warning page
    u = user_row(); assert ai.decrypt(u["ai_key_enc"]) == "sk-or-test" and u["ai_model"] == "text/only"

def test_blank_key_with_none_saved(client, mock_ai):
    assert "Enter your OpenRouter key." in save(client).text

def test_overlong_key_refused(client, mock_ai):
    assert "That doesn&#39;t look like an OpenRouter key." in save(client, key="x" * 301).text

def test_remove_key(ai_client):
    r = save(ai_client, remove="1")
    assert r.status_code == 303 and user_row()["ai_key_enc"] is None
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_ask.py -q`. Expected: 404s and a missing fixture.

- [ ] **Step 3: Implement.** Order of checks in `POST /settings/ai`: remove; `secret_ok` (message: "Set SECRET_KEY on the server to a long random value before saving an AI key. Keys are stored encrypted with it."); key present or already saved; key length (1 to 300 after strip); `check_key` is False; `model_check` unknown. A blank model means `ai.DEFAULT_MODEL`. Success with no warning redirects to `/me`; every other outcome renders `me._page(..., ai_msg=...)`. A key of unknown validity (`check_key` is None) is saved.

- [ ] **Step 4: Write the `me.html` section.** Fixed copy:
  - Intro: "Bring your own OpenRouter key to use the Ask tab. What you type there is sent to OpenRouter under your key. Your weight is never sent."
  - Key field: `<input type="password" name="key" autocomplete="off" maxlength="300">`, label "OpenRouter key". When a key is saved, a line "A key is saved. Type a new one to replace it." and a second submit button `name="remove" value="1"` labelled "Remove key" (`btn-danger`).
  - Model field: text, label "Model", `value` the saved model, `placeholder="openai/gpt-5-nano"`.
  - Button: "Save AI settings".
  - `ai_msg` renders as `<p class="msg" role="alert">` at the top of the section, and `<details ... open>` when it is set.

- [ ] **Step 5: Local setup and docs.** In `docker-compose.yml` change the app's `SECRET_KEY: change-me` to `SECRET_KEY: ${SECRET_KEY:-change-me}`. In `README.md`, extend the `SECRET_KEY` row and note: it also encrypts saved AI keys, the app will not save an AI key while it is unset or a placeholder, and changing it means everyone re-enters their key.

- [ ] **Step 6: Run** `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 7: Commit** `git commit -m "feat: AI key and model settings"`

---

### Task 3: The Ask tab

**Files:**
- Modify: `app/ask.py`, `app/db.py` (table), `app/me.py` (delete its `/ask` route), `app/templates/soon.html` (drop the Ask branch), `app/static/app.css`, `tests/test_me.py:71` (the "on the way" assertion for `/ask` goes)
- Create: `app/templates/ask.html`, `app/templates/_chat.html`
- Test: `tests/test_ask.py`

**Interfaces:**
- Consumes: `ai.chat`, `ai.decrypt`, `ai.AIError`, `ai.DEFAULT_MODEL`, `today.local_today`, fixtures `mock_ai`, `ai_client`, helpers `reply`, `cite`, `err`, `CHAT` (move them from `tests/test_ai.py` into `tests/conftest.py` as plain functions and import them).
- Produces:
  - Table (in `db.SCHEMA`):
    ```sql
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(mealie_user_id),
        role TEXT NOT NULL CHECK (role IN ('user','assistant')),
        content TEXT,      -- NULL on an assistant row: the answer is still being fetched
        sources TEXT,      -- JSON list of {"url","title"}
        error INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    ```
  - `GET /ask`: the page. `POST /ask` (form field `message`). `GET /ask/chat`: the `_chat.html` fragment. `POST /ask/new`: clears this person's conversation, 303 to `/ask`.
  - Constants in `app/ask.py`: `MAX_MESSAGE = 4000`, `HISTORY = 20`, `STALE_SECONDS = 300`, `SYSTEM` (below).

- [ ] **Step 1: Write the failing tests in `tests/test_ask.py`**

```python
HX = {"HX-Request": "true"}
def rows(): con = db.connect(); out = con.execute("SELECT * FROM chat_messages ORDER BY id").fetchall(); con.close(); return out
def add_row(role, content, minutes_ago=0, error=0, user_id="u1"): ...  # direct INSERT with created_at = now - minutes_ago (UTC isoformat)

def test_no_key_page(client, mock_ai):
    r = client.get("/ask")
    assert r.status_code == 200 and "Add your AI key" in r.text and 'href="/me#ai"' in r.text and "<textarea" not in r.text
    assert client.post("/ask", data={"message": "hi"}, follow_redirects=False).status_code == 303 and rows() == []

def test_key_unreadable_after_secret_change(ai_client, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a-different-secret")
    r = ai_client.get("/ask");  assert r.status_code == 200 and "Add your AI key" in r.text

def test_ask_and_answer(ai_client, mock_ai):
    mock_ai[CHAT] = reply("Use bread flour.", [cite("https://k.com/r", "King Arthur")])
    r = ai_client.post("/ask", data={"message": "Best flour for rolls?"}, headers=HX)
    assert r.status_code == 200 and "Best flour for rolls?" in r.text and "Thinking" in r.text
    assert 'hx-trigger="every 3s"' in r.text and "disabled" in r.text
    done = ai_client.get("/ask/chat").text          # TestClient runs the background task before returning
    assert "Use bread flour." in done and "Thinking" not in done and "every 3s" not in done and "disabled" not in done
    assert '<a href="https://k.com/r" target="_blank" rel="noopener noreferrer">King Arthur</a>' in done
    assert "Use bread flour." in ai_client.get("/ask").text    # the full page shows the conversation too

def test_messages_sent_to_model(ai_client, mock_ai):
    bodies = []
    def handler(request): bodies.append(json.loads(request.content)); return reply("A1")
    mock_ai[CHAT] = handler
    ai_client.post("/ask", data={"message": "Q1"}, headers=HX)
    add_row("assistant", "Your OpenRouter account is out of credit.", error=1)
    ai_client.post("/ask", data={"message": "Q2"}, headers=HX)
    sys = bodies[0]["messages"][0]
    assert sys["role"] == "system" and today.local_today().strftime("%A, %B %-d, %Y") in sys["content"]
    assert bodies[0]["messages"][1:] == [{"role": "user", "content": "Q1"}]
    assert bodies[1]["messages"][1:] == [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"}, {"role": "user", "content": "Q2"}]
    assert bodies[1]["model"] == "openai/gpt-5-nano"

def test_history_capped(ai_client, mock_ai):   # 30 old rows, then ask: len(messages) == 1 + HISTORY, last is the new question
def test_provider_error_shown(ai_client, mock_ai):   # CHAT -> err(402); /ask/chat has "out of credit" inside class "chat-error"; row error == 1
def test_unexpected_failure_does_not_hang(ai_client, monkeypatch):   # ai.chat raises RuntimeError -> "The AI service didn't answer. Try again."
def test_answer_is_escaped(ai_client, mock_ai):   # reply("<script>alert(1)</script>") -> "&lt;script&gt;" in fragment, "<script>alert" not
def test_second_message_while_waiting_is_ignored(ai_client, mock_ai):
    add_row("user", "Q1"); add_row("assistant", None)
    ai_client.post("/ask", data={"message": "Q2"}, headers=HX)
    assert [r["content"] for r in rows()] == ["Q1", None]
def test_stale_wait_becomes_error(ai_client):
    add_row("user", "Q1", minutes_ago=10); add_row("assistant", None, minutes_ago=10)
    t = ai_client.get("/ask/chat").text
    assert "That took too long. Ask again." in t and "every 3s" not in t and "disabled" not in t
def test_blank_and_long_messages(ai_client, mock_ai):   # "   " stores nothing; "x" * 5000 stores 4000 characters
def test_plain_post_redirects(ai_client, mock_ai):      # no HX header -> 303 to /ask
def test_conversations_are_private(ai_client, login_as):   # u1 row "secret question"; login_as("u2") saves a key; its /ask/chat lacks the text
def test_new_chat(ai_client, login_as):   # rows for u1 and u2; POST /ask/new -> 303; only u2's rows remain
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_ask.py -q`. Expected: the new tests fail.

- [ ] **Step 3: Implement the routes in `app/ask.py`.**
  - A person "has a key" when `ai.decrypt(user["ai_key_enc"])` is not None. Without one, `GET /ask` renders the add-key state and the other three routes redirect to `/ask`.
  - `POST /ask`: strip and cut the message to `MAX_MESSAGE`; if it is empty or an answer is being waited for, change nothing. Otherwise insert the user row and an assistant row with `content` NULL, and add a `BackgroundTasks` task that calls `ai.chat` and fills that row (text and sources, or the `AIError` sentence with `error = 1`; any other exception stores "The AI service didn't answer. Try again." with `error = 1`). Respond with the fragment for htmx, 303 to `/ask` otherwise.
  - Messages sent: the system message, then this person's last `HISTORY` rows that have content and `error = 0`, oldest first.
  - Before reading the conversation, turn this person's waiting rows older than `STALE_SECONDS` into `content = "That took too long. Ask again."`, `error = 1`.
  - The model is `user["ai_model"] or ai.DEFAULT_MODEL`.
  - `SYSTEM`, with the date filled in as `local_today().strftime("%A, %B %-d, %Y")`:
    ```
    You are the cooking assistant inside Homeplate, a home-cooking and calorie-diary app. Help with recipes, meal ideas, cooking and nutrition questions. Search the web when it helps, and prefer pages with a clear ingredient list and steps. Keep answers short: they are read on a phone. Write plain text with no Markdown, and do not put links in your answer: the sources you used are shown under it. Today is {date}.
    ```
  - Add a `# ponytail:` comment on the history cap (a fixed 20 messages; switch to a token budget if long chats get cut off or cost too much).

- [ ] **Step 4: Write the templates.**
  - `ask.html`: page head "Ask". No key: `<section class="card empty">` with the ask icon, heading "Add your AI key", the line "The assistant runs on your own OpenRouter key.", and `<a class="btn" href="/me#ai">Open Settings</a>`. With a key: `<div id="chat">` including `_chat.html`, then a `<form method="post" action="/ask/new">` with a `btn-secondary` button "New chat", shown only when the conversation is not empty.
  - `_chat.html` (everything htmx swaps, target `#chat`, `hx-swap="innerHTML"`):
    - `<ol class="chat" aria-live="polite">`, one `<li>` per row: `chat-user`, `chat-ai`, or `chat-ai chat-error`. Text in a `<p class="chat-text">` (CSS `white-space: pre-wrap; overflow-wrap: anywhere`).
    - Under an answer with sources: `<ul class="chat-sources">` of `<a href="{{ s.url }}" target="_blank" rel="noopener noreferrer">{{ s.title }}</a>`, attributes in exactly that order.
    - A waiting row: `<li class="chat-ai chat-wait" role="status" hx-get="/ask/chat" hx-trigger="every 3s" hx-target="#chat" hx-swap="innerHTML">Thinking. This can take a little while.</li>`
    - Empty conversation: `<p class="muted chat-empty">Ask about recipes, cooking or nutrition.</p>`
    - The form: `<form class="chat-form" method="post" action="/ask" hx-post="/ask" hx-target="#chat" hx-swap="innerHTML">` with `<textarea name="message" rows="2" maxlength="4000" required aria-label="Your question">` and a "Send" button. While waiting, both carry `disabled`. The word `disabled` appears nowhere else in the fragment.
  - `soon.html`: remove the Ask conditionals; it serves only `/order` now.

- [ ] **Step 5: Style it in `app/static/app.css`** using the existing tokens (`--s-*`, `--text`, `--muted`, `--border`, `--danger`, `--t-small`). Only the new `chat-*` classes. The person's bubbles sit right, answers left, at most 85% wide; the form sits under the conversation in normal flow (the tab bar is already fixed at the bottom).

- [ ] **Step 6: Run** `.venv/bin/pytest -q`. Expected: all pass.

- [ ] **Step 7: Commit** `git commit -m "feat: Ask tab with web search and sources"`

---

### Task 4: Live check in a real browser

Needs OpenRouter credit on the key in `.env`. Check first with `GET https://openrouter.ai/api/v1/credits`; if `total_credits - total_usage` is under $0.50, stop and report that the owner must add credit. Never print the key or pass it on a command line or into the browser tool.

**Files:**
- Modify: `app/ai.py` (only if step 4 says so), `docs/superpowers/specs/2026-11-09-assistant.md`, `docs/HANDOFF.md`

- [ ] **Step 1: Run it.** If `.env` has no `SECRET_KEY` line, append one (`python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env`). `docker compose up -d --build`. Sign in at `http://localhost:8000` as the test admin from the handoff notes, in a real browser.
- [ ] **Step 2: Settings through the browser.** Save the key `sk-or-not-a-real-key`: expect "OpenRouter rejected that key." (this proves the form passes the same-origin guard). Then store the real key without showing it: a short script run with `.venv/bin/python`, `DATA_DIR=data` and `SECRET_KEY` and `OPENROUTER_API_KEY` read from `.env`, that calls `ai.encrypt` and updates the admin's `users` row. Reload Me: "A key is saved".
- [ ] **Step 3: Ask three questions in the browser** and record seconds to answer, cost (from OpenRouter's activity page or `usage.cost`), and whether sources show: "How long do I rest pizza dough?", "Find a highly rated cinnamon roll recipe", "What cinnamon roll recipe do people on Reddit recommend most?". Check there is no Markdown or link text left in the answers, the waiting bubble appears and is replaced without a reload, and a reload mid-wait still ends with the answer.
- [ ] **Step 4: Check the targets and one other model.** Each of the three questions should finish in under 20 seconds and cost under half a cent; if not, record what was measured and stop for the owner. Then set the model to `google/gemini-2.5-flash-lite` in Settings and ask the second question: if OpenRouter rejects the request because of `reasoning`, send that field only when the model's `supported_parameters` lists `reasoning`, with a test.
- [ ] **Step 5: Settle design point 5.** One request to `/chat/completions` with the search tool, one function tool and `response_format` of type `json_schema` (research notes 1.8), asking for a pancake recipe from the web; then the same without tools. Record in the spec whether each returned valid JSON matching the schema.
- [ ] **Step 6: Look at it.** At 375, 390 and 430 px wide, light and dark: Ask with no key, Ask empty, Ask with a long answer and sources, Ask while waiting, Me with the AI section open and with a message. Fix anything that overflows or collides with the tab bar.
- [ ] **Step 7: Write up.** Replace the "NOT TESTED" line in the spec's live results with what step 5 found, add the timings and costs, and update `docs/HANDOFF.md` (state of the code, test count, what is next). Commit `git commit -m "docs: piece 1 live check results"`.

After Task 4: whole-branch review, then a pull request to `main` (merge when checks are green, per the standing permission), then show the owner before piece 2 starts.
