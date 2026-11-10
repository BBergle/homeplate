from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app import auth, db, mealie

router = APIRouter()


@router.get("/r/{recipe_id}")
def recipe_page(request: Request, recipe_id: str, user=Depends(auth.current_user)):
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
    finally:
        con.close()
    n = r.get("nutrition") or {}
    ctx = {
        "recipe": r, "photos": photos, "uid": uid, "group": mealie.me(token).get("groupSlug"),
        "link": f"{auth.base_url(request)}/r/{r['id']}",
        "calories": mealie.leading_number(n.get("calories")), "protein": mealie.leading_number(n.get("proteinContent")),
    }
    return auth.templates.TemplateResponse(request, "recipe.html", ctx)


@router.get("/r/{recipe_id}/image")
def recipe_image(recipe_id: str, user=Depends(auth.current_user)):
    try:
        data = mealie.recipe_image(mealie.recipe(user["mealie_token"], recipe_id)["id"])
    except mealie.MealieNotFound:
        data = None
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/webp")
