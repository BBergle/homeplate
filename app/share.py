import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from app import auth, db, mealie, photos

router = APIRouter()


def _recipe_or_404(request: Request, user, recipe_id: str):
    try:
        return mealie.recipe(user["mealie_token"], recipe_id), None
    except mealie.MealieNotFound:
        return None, auth.templates.TemplateResponse(request, "notfound.html", {}, status_code=404)


@router.post("/r/{recipe_id}/share")
def create(request: Request, recipe_id: str, user=Depends(auth.current_user)):
    r, notfound = _recipe_or_404(request, user, recipe_id)
    if notfound:
        return notfound
    con = db.connect()
    try:
        if not con.execute("SELECT 1 FROM shares WHERE recipe_id = ?", (r["id"],)).fetchone():
            token = mealie.create_share(user["mealie_token"], r["id"])
            con.execute(
                "INSERT INTO shares (token, recipe_id, created_by, created_at) VALUES (?, ?, ?, ?)",
                (token, r["id"], user["mealie_user_id"], datetime.now(timezone.utc).isoformat()),
            )
            con.commit()
    finally:
        con.close()
    return RedirectResponse(f"/r/{recipe_id}", 303)


@router.post("/r/{recipe_id}/unshare")
def remove(request: Request, recipe_id: str, user=Depends(auth.current_user)):
    r, notfound = _recipe_or_404(request, user, recipe_id)
    if notfound:
        return notfound
    con = db.connect()
    try:
        row = con.execute("SELECT token FROM shares WHERE recipe_id = ?", (r["id"],)).fetchone()
        if row:
            mealie.delete_share(user["mealie_token"], row["token"])
            con.execute("DELETE FROM shares WHERE token = ?", (row["token"],))
            con.commit()
    finally:
        con.close()
    return RedirectResponse(f"/r/{recipe_id}", 303)


def _gone(request: Request):
    return auth.templates.TemplateResponse(request, "public_gone.html", {}, status_code=404)


def _share(token: str):
    con = db.connect()
    try:
        return con.execute("SELECT recipe_id FROM shares WHERE token = ?", (token,)).fetchone()
    finally:
        con.close()


@router.get("/s/{token}")
def page(request: Request, token: str):
    share = _share(token)
    if not share:
        return _gone(request)
    try:
        r = mealie.shared_recipe(token)
    except (mealie.MealieNotFound, mealie.MealieAuthError):  # never send a public visitor to /login
        return _gone(request)
    con = db.connect()
    try:
        pics = con.execute(
            "SELECT id FROM photos WHERE recipe_id = ? AND private = 0 ORDER BY created_at DESC, id DESC",
            (share["recipe_id"],),
        ).fetchall()
    finally:
        con.close()
    n = r.get("nutrition") or {}
    ctx = {
        "recipe": r, "photos": pics, "token": token,
        "calories": mealie.leading_number(n.get("calories")), "protein": mealie.leading_number(n.get("proteinContent")),
    }
    return auth.templates.TemplateResponse(request, "share.html", ctx)


@router.get("/s/{token}/photo/{photo_id}")
def photo(token: str, photo_id: int):
    con = db.connect()
    try:
        row = con.execute(
            "SELECT p.path FROM photos p JOIN shares s ON s.recipe_id = p.recipe_id "
            "WHERE s.token = ? AND p.id = ? AND p.private = 0",
            (token, photo_id),
        ).fetchone()
    finally:
        con.close()
    f = row and os.path.join(photos.photos_dir(), row["path"])
    if not f or not os.path.exists(f):
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg")


@router.get("/s/{token}/image")
def image(token: str):
    share = _share(token)
    try:
        data = share and mealie.recipe_image(share["recipe_id"])
    except mealie.MealieAuthError:
        data = None
    if not data:
        raise HTTPException(404)
    return Response(data, media_type="image/webp")
