# Assistant piece 2 (recipe cards with Add) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a person asks the assistant to find recipes, each recipe comes back as a card with a photo and an Add button that imports it into Mealie.

**Architecture:** The model gets three function tools next to web search: two look-ups that run without asking (`search_my_recipes`, `get_recipe`) and one proposal (`propose_recipes`). The background answer task loops up to six rounds, running look-ups and feeding results back; a `propose_recipes` call ends the turn and becomes rows in a new `proposals` table, rendered as cards under the answer. Tapping Add sends only the card's id; the server imports that card's stored address through Mealie's own link import. Card photos are fetched once by the server when the card is made, re-encoded to a small JPEG, and served from disk.

**Tech Stack:** FastAPI, Jinja2, htmx 2, sqlite3, httpx, Pillow. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-09-assistant.md` ("Decisions made by the owner", "How a turn works", "Importing a recipe, by source", "Live test results"). This plan covers the part of piece 2 the spec calls "look-up tools, the proposal cards, and finding and adding recipes from the web, with photos".

## Global Constraints

- **The assistant proposes; the person taps.** Look-ups run without asking. Nothing changes in Mealie or Homeplate until a card's button is tapped.
- The Add button sends only the card's id. The address imported is the one stored on the server for that card. A card works once and expires after a day ("Expired, ask again").
- Every tool runs as the signed-in person with their own Mealie token. No tool takes a user id.
- At most six model rounds per message. Each chat request still sends `"max_tokens": 4000`, `"reasoning": {"effort": "low"}` and the search tool `{"type":"openrouter:web_search","parameters":{"engine":"parallel","mode":"turbo","max_results":5}}`, with the function tools after it.
- A fixed JSON format (`response_format`) is never sent together with tools (live test: it is ignored).
- Card photos: fetched by the server, never by the phone from the recipe site. Only `https`, only hosts whose every address is public, re-checked after each redirect, 5 MB limit, decoded and re-encoded with Pillow (JPEG, PNG, WEBP or GIF in; JPEG out, at most 640 px). Never SVG.
- Outbound fetches to addresses the model supplied use a new `httpx` client per request and connect to the address that was checked (`https://<ip>/...` with `headers={"Host": host}` and `extensions={"sni_hostname": host}`). Never a shared client: its connection pool is keyed by IP and would reuse a connection made under another site's name.
- Mealie's link import gets a 60 second limit and its test scrape 20 seconds; other Mealie calls keep 10.
- Weight is never sent to the model. The key is never written to a log or a template. Model text is always escaped (never `|safe`).
- New page elements get their own class names (`rcard-*`). Do not restyle `.card`, `.msg`, `.hint`, `.hero`, `.chat-*` or other existing classes.
- Work on branch `assistant-cards`. `.venv/bin/pytest -q` passes at every commit (260 before this plan).

## Calls made in planning (mine, not the owner's)

- The model's one-line introduction to the cards travels inside the `propose_recipes` call (`intro`), so a turn with cards needs no extra model round. Measured: one request, 17 s, 0.14 cents.
- In later turns the model is told what it showed as text appended to its earlier answer ("[Shown as cards: 1. Name (address); ...]"), not by replaying tool-call messages. This keeps stored history plain and works with any provider.
- A card is made only for an address Mealie's test scrape can read with at least one ingredient; other proposed pages become a card with no Add button that says so.
- "Paste the recipe here" is piece 3. Until then a page Mealie cannot import says only "Mealie can't import this page."
- An `http://` address the model proposes is upgraded to `https://`.
- Only two look-ups ship here (`search_my_recipes`, `get_recipe`). The spec's other look-ups (foods on hand, meal plan, shopping list, today) ship in piece 3 with the cards that need them.

## Review Focus

1. The model proposes a local or private address (`https://192.168.1.1/x`, `https://localhost/x`, a name resolving to `10.0.0.5`), or a page redirects a photo fetch to one: no card photo is fetched from it and no card with an Add button is made for it. (Task 2, Task 3 tests)
2. A double tap on Add: one import. (Task 4 test)
3. A photo that is not an image, is SVG, or is larger than 5 MB: the card shows without a photo. (Task 2 test)
4. Another person's card id on Add or on the photo route: 404, nothing imported, nothing served. (Task 4 test)
5. Mealie cannot read the page at Add time: the card says so and stays unusable; Mealie is unreachable: the card stays usable and says to try again. (Task 4 test)

---

### Task 1: Function tools in `ai.chat`, and Mealie scrape and import

**Files:**
- Modify: `app/ai.py`, `app/mealie.py`
- Test: `tests/test_ai.py`, `tests/test_mealie.py` (create)

**Interfaces:**
- Produces:
  - `ai.chat(key: str, model: str, messages: list[dict], tools: list[dict] | None = None) -> dict` returning `{"text": str, "sources": list, "calls": [{"id": str, "name": str, "args": dict}], "message": dict}`. `tools` are appended after the search tool. `message` is `{"role": "assistant", "content": <raw content>, "tool_calls": <raw list>}` for sending back in the same turn. Blank text is an error only when there are no calls.
  - `mealie.test_scrape(token: str, url: str) -> dict | None`: `POST /api/recipes/test-scrape-url` with `{"url": url}`, 20 s. Returns `{"name": str | None, "image": str | None, "ingredients": int}`, or `None` when Mealie refuses the page or the reply is not an object.
  - `mealie.import_url(token: str, url: str) -> str`: `POST /api/recipes/create/url` with `{"url": url, "includeTags": False}`, 60 s. Returns the new recipe's slug. Mealie's 400 surfaces as the existing `MealieRejected`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai.py
def test_chat_sends_function_tools_after_search(mock_ai):   # body["tools"] == [search tool, T]; without tools= the body is unchanged
def test_chat_returns_calls_and_message(mock_ai):
    raw = [{"id": "c1", "type": "function", "function": {"name": "get_recipe", "arguments": "{\"id\": \"r1\"}"}},
           {"id": "c2", "type": "function", "function": {"name": "x", "arguments": "not json"}}]
    mock_ai[CHAT] = httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": raw}}]})
    out = ai.chat("k", "m", [], tools=[T])
    assert out["text"] == "" and out["calls"] == [{"id": "c1", "name": "get_recipe", "args": {"id": "r1"}}, {"id": "c2", "name": "x", "args": {}}]
    assert out["message"] == {"role": "assistant", "content": None, "tool_calls": raw}
def test_chat_plain_answer_has_no_calls(mock_ai):           # reply("Hi") -> calls == [], message["content"] == "Hi"
# existing blank-text error tests must still pass (no calls -> error)

# tests/test_mealie.py  (uses mock_mealie)
def test_test_scrape_shapes(mock_mealie):
    # image as a string, as {"@type": "ImageObject", "url": U}, as [U, ...], as [{"url": U}], missing -> None
    # recipeIngredient list of 18 -> ingredients == 18; missing -> 0; name passed through
def test_test_scrape_refused_or_odd(mock_mealie):            # 400 -> None; 200 with a JSON string body -> None
def test_import_url(mock_mealie):                            # 201 "the-slug" -> "the-slug"; request body == {"url": U, "includeTags": False}; 400 -> MealieRejected
def test_scrape_and_import_timeouts(mock_mealie):            # request.extensions["timeout"]["read"] == 20 and 60
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_ai.py tests/test_mealie.py -q`. Expected: the new tests fail.
- [ ] **Step 3: Implement.** In `chat`, parse `message.tool_calls`; arguments that are not a JSON object become `{}`. Keep every existing cleaning and error rule.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `git commit -m "feat: function tools in the AI client; Mealie test scrape and link import"`

---

### Task 2: Safe photo fetch

**Files:**
- Create: `app/webimg.py`
- Test: `tests/test_webimg.py`

**Interfaces:**
- Produces:
  - `webimg.resolve(host: str) -> list[str]`: the host's addresses (wraps `socket.getaddrinfo`; tests replace it).
  - `webimg.public_https(url: str) -> str | None`: the address, cleaned, if it is acceptable to show and fetch: scheme `https` (an `http` address is upgraded), a host name (not a bare IP), no user or password, port absent or 443, at most 2,000 characters, and every address `resolve` returns is public (`ipaddress.ip_address(a).is_global`). Otherwise `None`. A name that does not resolve is `None`.
  - `webimg.thumbnail(url: str) -> bytes | None`: JPEG bytes, at most 640 px on the long side, or `None` for any failure.
  - `webimg.MAX_BYTES = 5 * 1024 * 1024`, `webimg.MAX_REDIRECTS = 3`.

- [ ] **Step 1: Write the failing tests** (replace `webimg.resolve` with a table; replace the transport by monkeypatching a module-level `webimg._transport = None` that `thumbnail` passes to each new `httpx.Client(transport=...)`)

```python
PUBLIC, PRIVATE = ["93.184.216.34"], ["10.0.0.5"]
@pytest.mark.parametrize("url,addrs,ok", [
    ("https://site.example/a?b=1", PUBLIC, "https://site.example/a?b=1"),
    ("http://site.example/a", PUBLIC, "https://site.example/a"),
    ("https://site.example/a", PRIVATE, None), ("https://site.example/a", PUBLIC + PRIVATE, None),
    ("https://site.example/a", ["127.0.0.1"], None), ("https://site.example/a", ["169.254.169.254"], None),
    ("https://site.example/a", ["::1"], None), ("https://site.example/a", ["fd00::1"], None), ("https://site.example/a", [], None),
    ("https://192.168.1.1/a", PUBLIC, None), ("https://93.184.216.34/a", PUBLIC, None), ("https://localhost/a", ["127.0.0.1"], None),
    ("https://user:pw@site.example/a", PUBLIC, None), ("https://site.example:8443/a", PUBLIC, None),
    ("ftp://site.example/a", PUBLIC, None), ("javascript:alert(1)", PUBLIC, None), ("https://site.example/" + "a" * 2000, PUBLIC, None),
])
def test_public_https(monkeypatch, url, addrs, ok): ...

def test_thumbnail_fetches_checked_address_and_reencodes(...):
    # handler asserts request.url.host == "93.184.216.34", headers["host"] == "site.example", extensions["sni_hostname"] == "site.example"
    # serves a 1200x800 PNG -> result opens with Pillow as JPEG, max(size) == 640
def test_thumbnail_follows_public_redirect_and_refuses_private_one(...):   # 302 to another public host works; 302 to a host resolving private -> None; 4 redirects -> None
def test_thumbnail_refuses_bad_content(...):   # SVG body, HTML body, 6 MB body (streamed, stops reading past the limit), 404, timeout -> None
def test_thumbnail_uses_a_new_client_each_time(...):   # two calls build two clients
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_webimg.py -q`. Expected: fails, no module.
- [ ] **Step 3: Implement `app/webimg.py`.** `thumbnail` loop: `public_https` the address, pick the first IPv4 address (else the first, in brackets), stream `GET https://<ip><path?query>` with the two overrides above, `follow_redirects=False`, 10 s; on 301/302/303/307/308 take `Location` (resolved against the current address) and go round again, at most `MAX_REDIRECTS`; read at most `MAX_BYTES + 1` bytes and refuse if more; open with `Image.open(..., formats=["JPEG", "PNG", "WEBP", "GIF"])` under the same decompression-bomb guard `app/photos.py` uses, convert to RGB, `thumbnail((640, 640))`, save as JPEG quality 80. Any exception returns `None`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `git commit -m "feat: safe server-side fetch of card photos"`

---

### Task 3: Tools, the answer loop, and stored cards

**Files:**
- Create: `app/asktools.py`
- Modify: `app/ask.py` (the answer task, the messages sent, the system prompt), `app/db.py` (table)
- Test: `tests/test_ask.py`, `tests/test_asktools.py` (create)

**Interfaces:**
- Consumes: `ai.chat(..., tools=)`, `mealie.search_recipes`, `mealie.recipe`, `mealie.test_scrape`, `webimg.public_https`, `webimg.thumbnail`.
- Produces:
  - Table:
    ```sql
    CREATE TABLE IF NOT EXISTS proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(mealie_user_id),
        message_id INTEGER NOT NULL,          -- the chat_messages answer row it hangs under
        kind TEXT NOT NULL CHECK (kind IN ('recipe')),
        payload TEXT NOT NULL,                -- JSON: name, url, host, why, importable (bool), photo (bool)
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'working', 'done', 'failed')),
        result TEXT,                          -- done: the new recipe's slug; failed: the sentence shown
        created_at TEXT NOT NULL
    );
    ```
  - `asktools.TOOLS: list[dict]`, the three function tool definitions (names `search_my_recipes(query)`, `get_recipe(id)`, `propose_recipes(intro, recipes[{name, url, why}])`).
  - `asktools.lookup(name: str, args: dict, token: str) -> dict`: runs a look-up and returns a JSON-able result. `search_my_recipes` gives `{"recipes": [{"id", "name"}]}` (first 8). `get_recipe` gives `{"name", "ingredients": [str], "steps": [str], "calories": str | None, "protein": str | None}` with each list cut to 40 entries. An unknown name gives `{"error": "unknown tool"}`; any Mealie failure gives `{"error": "the recipe library could not be reached"}`.
  - `asktools.recipe_cards(args: dict, token: str) -> tuple[str, list[dict]]`: the intro (stripped, cut to 300 characters) and at most 5 card payloads `{"name", "url", "host", "why", "importable", "image"}`. For each proposed recipe in order: `webimg.public_https(url)` or skip; skip repeats; `mealie.test_scrape`; `importable` is true when the scrape has at least one ingredient; `name` is the scrape's name, else the model's, cut to 120; `why` cut to 200; `image` is `webimg.public_https` of the scrape's image, else `None`.
  - `asktools.photos_dir() -> str`: `DATA_DIR/cards`; a card's photo is `<photos_dir>/<proposal id>.jpg`.
  - `ask._answer(row_id: int, uid: str, key: str, model: str, token: str, messages: list[dict]) -> None` and `ask.ROUNDS = 6`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_asktools.py  (mock_mealie; monkeypatch webimg.public_https to accept hosts ending ".example" and webimg.thumbnail)
def test_lookup_search_and_get(mock_mealie):        # shapes above; 9 hits -> 8; nutrition passed through
def test_lookup_unknown_and_mealie_down(mock_mealie):
def test_recipe_cards(mock_mealie, monkeypatch):
    # args: 7 recipes: one private-host url, one repeat, one Mealie refuses (importable False, model's name kept), one scrape with 0 ingredients (importable False)
    # -> at most 5 payloads, in order, no private host, no repeat; intro cut to 300; why cut to 200
def test_recipe_cards_bad_args(mock_mealie):        # args {} / recipes not a list / items not dicts -> ("", [])

# tests/test_ask.py
def call(name, args, id="c1"): ...                  # an OpenRouter reply whose message has one tool call and content None
def test_lookup_round_then_answer(ai_client, mock_ai, mock_mealie):
    # replies in order: call("search_my_recipes", {"query": "rolls"}), then reply("You have one.")
    # second request's messages end with the assistant tool-call message and {"role": "tool", "tool_call_id": "c1", "content": <json of lookup result>}
    # the answer row is "You have one."; no proposals rows
def test_propose_makes_cards_and_ends_turn(ai_client, mock_ai, mock_mealie, monkeypatch):
    # one reply: call("propose_recipes", {"intro": "Here are two.", "recipes": [A, B]}) -> exactly one chat request;
    # answer row content == "Here are two."; two proposals rows (kind recipe, status open, message_id == answer row id, payload has name/url/host/why/importable/photo)
    # webimg.thumbnail returned bytes for A -> file <cards>/<id>.jpg exists and payload photo True; None for B -> photo False
def test_propose_with_no_usable_recipe(ai_client, ...):   # all urls private -> answer row is the error sentence below, error == 1, no proposals
def test_six_rounds_then_stop(ai_client, ...):            # the model calls a look-up every round -> exactly 6 chat requests, then the error sentence below
def test_tools_use_the_askers_token(ai_client, ...):      # the Authorization header Mealie sees is the signed-in person's token
def test_next_turn_tells_the_model_what_it_showed(ai_client, ...):
    # after a turn with cards, the next request's assistant message content == "Here are two.\n[Shown as cards: 1. NameA (urlA); 2. NameB (urlB)]"
def test_system_prompt_mentions_cards(ai_client, ...):    # system content contains "propose_recipes"
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_ask.py tests/test_asktools.py -q`. Expected: the new tests fail.
- [ ] **Step 3: Implement.**
  - `POST /ask` passes the person's id and `user["mealie_token"]` to the task.
  - The loop: call `ai.chat(key, model, msgs, tools=asktools.TOOLS)`. No calls: store text and sources, done. A `propose_recipes` call: build cards; if there are none, store "I found recipes but couldn't read their pages. Ask again." with `error = 1`; otherwise store the intro as the answer (if the intro is blank: "Here is what I found."), insert one `proposals` row per card, fetch each card's photo with `webimg.thumbnail(image)` and write it to `<photos_dir>/<id>.jpg`, set `photo` in the payload, done. Otherwise append `r["message"]` and one `{"role": "tool", "tool_call_id": id, "content": json.dumps(asktools.lookup(...))}` per call and go round again. After `ROUNDS` rounds: "That took too many steps. Ask again more simply." with `error = 1`.
  - The existing catch-all around the task stays, so nothing can leave a row waiting.
  - Add `# ponytail:` comments: cards' pages are scraped and photos fetched one after another (parallelise if five cards feel slow); photo files of expired cards are only removed by New chat.
  - System prompt: keep the existing text and add: "When the person asks you to find recipes, search the web, then call propose_recipes with 3 to 5 good ones instead of listing them. Use only pages your search returned. Use search_my_recipes and get_recipe for questions about their own saved recipes."
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `git commit -m "feat: assistant look-up tools and recipe proposals"`

---

### Task 4: Cards on the page, Add, and photos

**Files:**
- Create: `app/templates/_rcard.html`
- Modify: `app/ask.py` (conversation query, two routes, New chat), `app/templates/_chat.html`, `app/static/app.css`
- Test: `tests/test_ask.py`

**Interfaces:**
- Consumes: the `proposals` table and `asktools.photos_dir()` from Task 3; `mealie.import_url`; `mealie.MealieRejected`, `mealie.MealieError`.
- Produces: `POST /ask/cards/{card_id}` (Add), `GET /ask/cards/{card_id}/photo`, `ask.EXPIRE_HOURS = 24`.

- [ ] **Step 1: Write the failing tests**

```python
def add_card(status="open", hours_ago=0, importable=True, photo=False, user_id="u1", **payload): ...   # an answer row plus one proposals row; returns the card id
def test_cards_render_under_their_answer(ai_client):
    # open + importable: name, host, why, a form posting to /ask/cards/<id> with hx-post, hx-target="#rcard-<id>", hx-swap="outerHTML", a button "Add",
    #   and '<a href="<url>" target="_blank" rel="noopener noreferrer">Open page</a>'
    # photo True -> '<img class="rcard-photo" src="/ask/cards/<id>/photo" alt="" loading="lazy">'; photo False -> no <img
    # not importable -> "Mealie can't import this page." and no form
    # older than 24 h and open -> "Expired, ask again." and no form
    # done with result "the-slug" -> "Added to your recipes." and href="/r/the-slug", no form
    # working -> "Still adding. Check your recipes in a minute."; failed -> its result sentence
def test_card_text_is_escaped(ai_client):               # name "<script>x</script>" -> "&lt;script&gt;"
def test_add_imports_once(ai_client, mock_mealie):
    # POST with HX-Request -> 200, body is the single card showing "Added to your recipes."; Mealie got {"url": <card url>, "includeTags": False}
    # a second POST -> Mealie called once in total; row status done, result the slug
def test_add_ignores_posted_address(ai_client, mock_mealie):   # extra form field url=https://evil.example -> Mealie still gets the stored address
def test_add_refused_page(ai_client, mock_mealie):       # Mealie 400 -> status failed, card says "Mealie couldn't read that page."; a later POST does not call Mealie
def test_add_mealie_down(ai_client, mock_mealie):        # ConnectError -> status back to open, card says "Can't reach Mealie. Try again." and still has the Add form
def test_add_expired_or_not_importable(ai_client, mock_mealie):   # no Mealie call, card unchanged
def test_other_persons_card(ai_client, login_as, mock_mealie):    # u2 POST and GET photo on u1's card -> 404, no Mealie call
def test_photo_route(ai_client):                         # file present -> 200 image/jpeg, Cache-Control "private, max-age=86400"; absent -> 404
def test_plain_post_redirects_to_ask(ai_client, mock_mealie):     # no HX header -> 303 /ask
def test_new_chat_removes_cards_and_photos(ai_client, login_as):  # u1's proposals rows and photo files gone; u2's kept
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_ask.py -q`. Expected: the new tests fail.
- [ ] **Step 3: Implement.**
  - Add: claim the card with one statement, `UPDATE proposals SET status = 'working' WHERE id = ? AND user_id = ? AND status = 'open' AND created_at > ?`, and continue only if it changed a row and the payload is importable. Then `mealie.import_url(user["mealie_token"], url)`: success sets `done` and the slug; `MealieRejected` sets `failed` with "Mealie couldn't read that page."; any other `MealieError` sets the card back to `open` and renders it once with "Can't reach Mealie. Try again." (a `MealieAuthError` is left to the app's existing handler, after setting the card back to `open`). A card id that is not this person's is 404.
  - `_rcard.html`: `<li class="rcard" id="rcard-{{ c.id }}">`; class names `rcard-photo`, `rcard-name`, `rcard-host`, `rcard-why`, `rcard-note`. `_chat.html` renders an answer's cards in `<ul class="rcards">` after its sources.
  - New chat deletes the person's `proposals` rows and their photo files as well as the messages.
  - CSS: a card is the photo on top (16:9, `object-fit: cover`), then name, host, why, the button full width, and the "Open page" link. Existing tokens only.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `git commit -m "feat: recipe cards with Add on the Ask tab"`

---

### Task 5: Live check in a real browser

The Chrome extension may not be connected. Use the script approach that worked for piece 1: `scripts/ask-check.mjs` drives a headless Chrome over the DevTools protocol (Node 22+, no dependencies). The key in `.env` is never printed, typed into the browser, or put on a command line; the test admin already has it saved in the local database.

**Files:**
- Create: `scripts/ask-check.mjs` (start from the piece 1 scratch script the controller supplies)
- Modify: `docs/superpowers/specs/2026-11-09-assistant.md`, `docs/HANDOFF.md`

- [ ] **Step 1:** `docker compose up -d --build homeplate` (do not recreate Mealie). Extend the script: after sign-in, ask "Find me some arroz con pollo recipes"; wait for the answer; assert at least two cards, no web address in the answer text, at least one card with a photo that loads (`naturalWidth > 0`), and at least one Add button.
- [ ] **Step 2:** Tap Add on the first importable card: assert the card becomes "Added to your recipes." without a reload, its link opens the recipe page in Homeplate (status 200, the recipe's name on it), and Mealie now has exactly one recipe with that name. Tap again by posting the form a second time: still one.
- [ ] **Step 3:** Ask "Which of my saved recipes use chicken?": assert an answer arrives that names the recipe just added (a look-up ran).
- [ ] **Step 4:** Layout at 375, 390 and 430 px, light and dark, with cards on screen: no sideways overflow, the last button clear of the tab bar, screenshots saved outside the repo and looked at.
- [ ] **Step 5:** Record seconds and cost for steps 1 and 3 (cost from `GET /api/v1/credits` before and after, allowing for its lag). Delete the test recipe from the local Mealie.
- [ ] **Step 6:** Write up in the spec's live results and in `docs/HANDOFF.md` (what piece 2 added, test count, what was and was not checked, the known limits found). Fix any small defect with a test and its own commit. Commit `git commit -m "docs: piece 2 live check"`.

After Task 5: whole-branch review, pull request to `main`, merge when checks are green, then show the owner.
