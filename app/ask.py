import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from app import ai, asktools, auth, db, me, today, webimg

router = APIRouter()

MAX_MESSAGE = 4000
HISTORY = 20  # ponytail: a fixed 20 messages; switch to a token budget if long chats get cut off or cost too much
STALE_SECONDS = 300
SYSTEM = (
    "You are the cooking assistant inside Homeplate, a home-cooking and calorie-diary app. "
    "Help with recipes, meal ideas, cooking and nutrition questions. Search the web when it helps, "
    "and prefer pages with a clear ingredient list and steps. Keep answers short: they are read on a phone. "
    "Write plain text with no Markdown, and do not put links in your answer: the sources you used are shown under it. "
    "Today is {date}. "
    "When the person asks you to find recipes, search the web, then call propose_recipes with 3 to 5 good ones instead of listing them. "
    "Use only pages your search returned. Use search_my_recipes and get_recipe for questions about their own saved recipes."
)
ROUNDS = 6
FAILED = "The AI service didn't answer. Try again."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conversation(uid: str) -> list[dict]:
    """This person's messages, oldest first; waiting rows past STALE_SECONDS are failed first."""
    con = db.connect()
    try:
        cutoff = (_now() - timedelta(seconds=STALE_SECONDS)).isoformat()
        con.execute(
            "UPDATE chat_messages SET content = 'That took too long. Ask again.', error = 1 WHERE user_id = ? AND role = 'assistant' AND content IS NULL AND created_at < ?",
            (uid, cutoff),
        )
        con.commit()
        out = con.execute("SELECT * FROM chat_messages WHERE user_id = ? ORDER BY id", (uid,)).fetchall()
    finally:
        con.close()
    return [dict(r) | {"sources": json.loads(r["sources"] or "[]")} for r in out]


def _fragment(request, uid):
    msgs = _conversation(uid)
    waiting = any(m["content"] is None for m in msgs)
    return auth.templates.TemplateResponse(request, "_chat.html", {"msgs": msgs, "waiting": waiting})


def _key(user) -> str | None:
    return ai.decrypt(user["ai_key_enc"])


def _to_ask(request):
    """No readable key: htmx would swap a followed redirect into #chat, so tell it to navigate."""
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": "/ask"})
    return RedirectResponse("/ask", 303)


def _answer(row_id: int, uid: str, key: str, model: str, token: str, messages: list[dict]) -> None:
    msgs = list(messages)
    try:
        text, sources, error = "That took too many steps. Ask again more simply.", None, 1
        for _ in range(ROUNDS):
            r = ai.chat(key, model, msgs, tools=asktools.TOOLS)
            proposal = next((c for c in r["calls"] if c["name"] == "propose_recipes"), None)
            if proposal:
                intro, cards = asktools.recipe_cards(proposal["args"], token)
                if cards:
                    _store_cards(row_id, uid, cards)
                    text, sources, error = intro or "Here is what I found.", None, 0
                else:
                    text, sources, error = "I found recipes but couldn't read their pages. Ask again.", None, 1
                break
            if not r["calls"]:
                text, sources, error = r["text"], json.dumps(r["sources"]), 0
                break
            msgs.append(r["message"])
            msgs += [{"role": "tool", "tool_call_id": c["id"], "content": json.dumps(asktools.lookup(c["name"], c["args"], token))} for c in r["calls"]]
    except ai.AIError as e:
        text, sources, error = str(e), None, 1
    except Exception:
        text, sources, error = FAILED, None, 1
    con = db.connect()
    try:
        con.execute("UPDATE chat_messages SET content = ?, sources = ?, error = ? WHERE id = ?", (text, sources, error, row_id))
        con.commit()
    finally:
        con.close()


def _store_cards(row_id: int, uid: str, cards: list[dict]) -> None:
    os.makedirs(asktools.photos_dir(), exist_ok=True)
    con = db.connect()
    try:
        for c in cards:
            image = c.pop("image")
            cur = con.execute(
                "INSERT INTO proposals (user_id, message_id, kind, payload, created_at) VALUES (?, ?, 'recipe', ?, ?)",
                (uid, row_id, "{}", _now().isoformat()),
            )
            # ponytail: photos are fetched one after another; photo files of expired cards are only removed by New chat
            jpg = webimg.thumbnail(image) if image else None
            if jpg:
                with open(os.path.join(asktools.photos_dir(), f"{cur.lastrowid}.jpg"), "wb") as f:
                    f.write(jpg)
            con.execute("UPDATE proposals SET payload = ? WHERE id = ?", (json.dumps(c | {"photo": bool(jpg)}), cur.lastrowid))
        con.commit()
    finally:
        con.close()


def _shown(uid: str) -> dict[int, str]:
    """For each answer row that has cards: the note telling the model what was shown."""
    con = db.connect()
    try:
        rows = con.execute("SELECT message_id, payload FROM proposals WHERE user_id = ? ORDER BY id", (uid,)).fetchall()
    finally:
        con.close()
    names: dict[int, list[str]] = {}
    for r in rows:
        p = json.loads(r["payload"])
        names.setdefault(r["message_id"], []).append(f"{len(names.get(r['message_id'], [])) + 1}. {p['name']} ({p['url']})")
    return {k: "\n[Shown as cards: " + "; ".join(v) + "]" for k, v in names.items()}


@router.get("/ask")
def ask_page(request: Request, user=Depends(auth.current_user)):
    has_key = _key(user) is not None
    ctx = {"has_key": has_key}
    if has_key:
        msgs = _conversation(user["mealie_user_id"])
        ctx |= {"msgs": msgs, "waiting": any(m["content"] is None for m in msgs)}
    return auth.templates.TemplateResponse(request, "ask.html", ctx)


@router.get("/ask/chat")
def ask_chat(request: Request, user=Depends(auth.current_user)):
    if _key(user) is None:
        return _to_ask(request)
    return _fragment(request, user["mealie_user_id"])


@router.post("/ask")
def ask_send(request: Request, tasks: BackgroundTasks, message: str = Form(""), user=Depends(auth.current_user)):
    key = _key(user)
    if key is None:
        return _to_ask(request)
    uid = user["mealie_user_id"]
    message = message.strip()[:MAX_MESSAGE]
    history = _conversation(uid)
    if message and not any(m["content"] is None for m in history):
        con = db.connect()
        try:
            now = _now().isoformat()
            con.execute("INSERT INTO chat_messages (user_id, role, content, created_at) VALUES (?, 'user', ?, ?)", (uid, message, now))
            cur = con.execute("INSERT INTO chat_messages (user_id, role, created_at) VALUES (?, 'assistant', ?)", (uid, now))
            con.commit()
            row_id = cur.lastrowid
        except sqlite3.IntegrityError:  # a concurrent request already has an answer pending (unique index): ignore this message
            con.rollback()
            row_id = None
        finally:
            con.close()
        if row_id is not None:
            shown = _shown(uid)
            sent = [{"role": m["role"], "content": m["content"] + shown.get(m["id"], "")} for m in history if m["content"] is not None and not m["error"]]
            sent = (sent + [{"role": "user", "content": message}])[-HISTORY:]
            system = {"role": "system", "content": SYSTEM.format(date=today.local_today().strftime("%A, %B %-d, %Y"))}
            tasks.add_task(_answer, row_id, uid, key, user["ai_model"] or ai.DEFAULT_MODEL, user["mealie_token"], [system, *sent])
    if request.headers.get("HX-Request"):
        return _fragment(request, uid)
    return RedirectResponse("/ask", 303)


@router.post("/ask/new")
def ask_new(user=Depends(auth.current_user)):
    # ponytail: New chat while an answer is being fetched lets one person run several model calls at once (each holds a threadpool thread); a per-person in-flight counter is the upgrade path if abused
    con = db.connect()
    try:
        con.execute("DELETE FROM chat_messages WHERE user_id = ?", (user["mealie_user_id"],))
        for p in con.execute("SELECT id FROM proposals WHERE user_id = ?", (user["mealie_user_id"],)).fetchall():
            try:
                os.remove(os.path.join(asktools.photos_dir(), f"{p['id']}.jpg"))
            except OSError:
                pass
        con.execute("DELETE FROM proposals WHERE user_id = ?", (user["mealie_user_id"],))
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/ask", 303)


@router.post("/settings/ai")
def save_ai(request: Request, model: str = Form(""), key: str = Form(""), remove: str | None = Form(None), user=Depends(auth.current_user)):
    typed = model.strip()
    page = lambda msg: me._page(request, dict(user) | ({"ai_model": typed} if typed else {}), ai_msg=msg)  # keep what was typed
    uid = user["mealie_user_id"]

    def update(sql, args):
        con = db.connect()
        try:
            con.execute(f"UPDATE users SET {sql} WHERE mealie_user_id = ?", (*args, uid))
            con.commit()
        finally:
            con.close()

    if remove is not None:
        update("ai_provider = NULL, ai_key_enc = NULL", ())
        return RedirectResponse("/me", 303)
    if not ai.secret_ok():
        return page("Set SECRET_KEY on the server to a long random value before saving an AI key. Keys are stored encrypted with it.")
    key, model = key.strip(), typed or ai.DEFAULT_MODEL
    if not key and ai.decrypt(user["ai_key_enc"]) is None:
        return page("Enter your OpenRouter key.")
    if len(key) > 300 or not key.isascii():
        return page("That doesn't look like an OpenRouter key.")
    if len(model) > 100:
        return page("That doesn't look like a model name.")
    if key and ai.check_key(key) is False:
        return page("OpenRouter rejected that key.")
    known, warning = ai.model_check(model)
    if not known:
        return page(f"OpenRouter has no model named {model}.")
    if key:
        update("ai_provider = 'openrouter', ai_key_enc = ?, ai_model = ?", (ai.encrypt(key), model))
    else:
        update("ai_model = ?", (model,))
    if warning:
        con = db.connect()  # re-read so the page shows the saved state
        try:
            user = con.execute("SELECT * FROM users WHERE mealie_user_id = ?", (uid,)).fetchone()
        finally:
            con.close()
        return me._page(request, user, ai_msg=f"Saved. {model} {warning}, so some features won't work.")
    return RedirectResponse("/me", 303)
