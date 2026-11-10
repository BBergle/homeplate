import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import ai, auth, db, me, today

router = APIRouter()

MAX_MESSAGE = 4000
HISTORY = 20  # ponytail: a fixed 20 messages; switch to a token budget if long chats get cut off or cost too much
STALE_SECONDS = 300
SYSTEM = (
    "You are the cooking assistant inside Homeplate, a home-cooking and calorie-diary app. "
    "Help with recipes, meal ideas, cooking and nutrition questions. Search the web when it helps, "
    "and prefer pages with a clear ingredient list and steps. Keep answers short: they are read on a phone. "
    "Write plain text with no Markdown, and do not put links in your answer: the sources you used are shown under it. "
    "Today is {date}."
)
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


def _answer(row_id: int, key: str, model: str, messages: list[dict]) -> None:
    try:
        r = ai.chat(key, model, messages)
        text, sources, error = r["text"], json.dumps(r["sources"]), 0
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
        return RedirectResponse("/ask", 303)
    return _fragment(request, user["mealie_user_id"])


@router.post("/ask")
def ask_send(request: Request, tasks: BackgroundTasks, message: str = Form(""), user=Depends(auth.current_user)):
    key = _key(user)
    if key is None:
        return RedirectResponse("/ask", 303)
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
        finally:
            con.close()
        sent = [{"role": m["role"], "content": m["content"]} for m in history if m["content"] is not None and not m["error"]]
        sent = (sent + [{"role": "user", "content": message}])[-HISTORY:]
        system = {"role": "system", "content": SYSTEM.format(date=today.local_today().strftime("%A, %B %-d, %Y"))}
        tasks.add_task(_answer, row_id, key, user["ai_model"] or ai.DEFAULT_MODEL, [system, *sent])
    if request.headers.get("HX-Request"):
        return _fragment(request, uid)
    return RedirectResponse("/ask", 303)


@router.post("/ask/new")
def ask_new(user=Depends(auth.current_user)):
    con = db.connect()
    try:
        con.execute("DELETE FROM chat_messages WHERE user_id = ?", (user["mealie_user_id"],))
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/ask", 303)


@router.post("/settings/ai")
async def save_ai(request: Request, user=Depends(auth.current_user)):
    form = await request.form()
    page = lambda msg: me._page(request, user, ai_msg=msg)
    uid = user["mealie_user_id"]

    def update(sql, args):
        con = db.connect()
        try:
            con.execute(f"UPDATE users SET {sql} WHERE mealie_user_id = ?", (*args, uid))
            con.commit()
        finally:
            con.close()

    if "remove" in form:
        update("ai_provider = NULL, ai_key_enc = NULL", ())
        return RedirectResponse("/me", 303)
    if not ai.secret_ok():
        return page("Set SECRET_KEY on the server to a long random value before saving an AI key. Keys are stored encrypted with it.")
    key = str(form.get("key", "")).strip()
    model = str(form.get("model", "")).strip() or ai.DEFAULT_MODEL
    if not key and not user["ai_key_enc"]:
        return page("Enter your OpenRouter key.")
    if len(key) > 300:
        return page("That doesn't look like an OpenRouter key.")
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
