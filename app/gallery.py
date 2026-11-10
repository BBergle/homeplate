from fastapi import APIRouter, Depends, Request

from app import auth, db, mealie

router = APIRouter()


@router.get("/r/{recipe_id}")
def gallery(request: Request, recipe_id: str, user=Depends(auth.current_user)):
    token = user["mealie_token"]
    try:
        r = mealie.recipe(token, recipe_id)
    except mealie.MealieNotFound:
        return auth.templates.TemplateResponse(request, "notfound.html", {}, status_code=404)
    uid = user["mealie_user_id"]
    con = db.connect()
    try:
        photos = con.execute(
            "SELECT id, user_id, private FROM photos WHERE recipe_id = ? AND (private = 0 OR user_id = ?) "
            "ORDER BY created_at DESC, id DESC",
            (r["id"], uid),
        ).fetchall()
        shared = con.execute("SELECT token FROM shares WHERE recipe_id = ?", (r["id"],)).fetchone()
    finally:
        con.close()
    base = auth.base_url(request)
    ctx = {"recipe": r, "photos": photos, "uid": uid, "share_url": shared and f"{base}/s/{shared['token']}", "group": mealie.me(token).get("groupSlug")}
    return auth.templates.TemplateResponse(request, "gallery.html", ctx)
