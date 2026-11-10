from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app import ai, auth, db, me

router = APIRouter()


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
