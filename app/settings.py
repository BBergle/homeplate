from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import ai, auth, db

router = APIRouter()


def _page(request, user, ai_msg=None):
    pending = 0
    if user["is_admin"]:
        con = db.connect()
        try:
            pending = con.execute("SELECT COUNT(*) FROM requests WHERE status = 'pending'").fetchone()[0]
        finally:
            con.close()
    ctx = {"user": user, "pending": pending, "ai_msg": ai_msg, "has_ai_key": ai.decrypt(user["ai_key_enc"]) is not None}
    return auth.templates.TemplateResponse(request, "settings.html", ctx)


@router.get("/settings")
def settings(request: Request, user=Depends(auth.current_user)):
    return _page(request, user)


@router.post("/settings/ai")
def save_ai(request: Request, model: str = Form(""), key: str = Form(""), remove: str | None = Form(None), user=Depends(auth.current_user)):
    typed = model.strip()
    page = lambda msg: _page(request, dict(user) | ({"ai_model": typed} if typed else {}), ai_msg=msg)  # keep what was typed
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
        return RedirectResponse("/settings", 303)
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
        return _page(request, user, ai_msg=f"Saved. {model} {warning}, so some features won't work.")
    return RedirectResponse("/settings", 303)
