import math
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app import auth, db, mealie, photos, stats

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TZ", "UTC"))


def local_today() -> date:
    return _now().astimezone(_tz()).date()


def _time_label(created_at: str) -> str:
    t = datetime.fromisoformat(created_at).astimezone(_tz())
    return f"{t.hour % 12 or 12}:{t:%M %p}"


def _page(request, user, error=None, open_form=None):
    """open_form: "cooked" or "other", the form whose optional fields start open (the one that errored)."""
    uid, d = user["mealie_user_id"], local_today()
    con = db.connect()
    try:
        entries = con.execute(
            "SELECT e.*, p.id AS photo_id FROM entries e LEFT JOIN photos p ON p.entry_id = e.id "
            "WHERE e.user_id = ? AND e.day = ? ORDER BY e.id",
            (uid, d.isoformat()),
        ).fetchall()
        w = con.execute("SELECT lbs FROM weights WHERE user_id = ? AND date = ?", (uid, d.isoformat())).fetchone()
        meal_days = con.execute(
            "SELECT day FROM entries WHERE user_id = ? AND kind IN ('cooked', 'leftovers')", (uid,)
        ).fetchall()
    finally:
        con.close()
    cal = sum(e["calories"] or 0 for e in entries)
    target, goal = user["cal_target"], user["weekly_goal"]
    week = stats.week_totals([date.fromisoformat(r["day"]) for r in meal_days], d)[-1]
    ctx = {
        "entries": [dict(e, time_label=_time_label(e["created_at"])) for e in entries],
        "cal": cal,
        "protein": round(sum(e["protein_g"] or 0 for e in entries)),
        "cal_pct": min(100, max(0, round(cal * 100 / target))) if target else None,
        "cal_left": max(0, target - cal) if target else None,
        "cal_over": max(0, cal - target) if target else None,
        "week_count": week,
        "week_extra": max(0, week - goal),
        "date_label": f"{d:%A} {d.day} {d:%b}",
        "user": user,
        "weight": w["lbs"] if w else None,
        "error": error,
        "open_form": open_form,
    }
    return auth.templates.TemplateResponse(request, "today.html", ctx)


def _num(s: str, name: str) -> int | None:
    if not s.strip():
        return None
    try:
        n = float(s)
    except ValueError:
        n = -1
    if not math.isfinite(n) or n < 0 or n > 100000:
        raise ValueError(f"{name} must be a number from 0 to 100000")
    return round(n)


@router.get("/")
def index(request: Request, user=Depends(auth.current_user)):
    return _page(request, user)


@router.get("/recipes/search")
def search(request: Request, q: str = "", user=Depends(auth.current_user)):
    token = user["mealie_token"]
    recipes = mealie.search_recipes(token, q) if q.strip() else mealie.planned_today(token)
    return auth.templates.TemplateResponse(request, "_recipe_results.html", {"recipes": recipes})


@router.post("/entries")
def add_entry(
    request: Request,
    kind: str = Form(),
    recipe_id: str = Form(""),
    description: str = Form(""),
    calories: str = Form(""),
    protein_g: str = Form(""),
    leftovers: str = Form(""),
    show_photo: str = Form(""),
    photo: UploadFile | None = File(None),
    user=Depends(auth.current_user),
):
    if kind not in ("cooked", "leftovers", "other"):
        return _page(request, user, "Pick a kind of entry")
    form = "other" if kind == "other" else "cooked"
    if kind != "other" and leftovers:
        kind = "leftovers"
    description = description.strip()
    try:
        cal, prot = _num(calories, "Calories"), _num(protein_g, "Protein")
    except ValueError as e:
        return _page(request, user, str(e), form)
    name = None
    if recipe_id and kind != "other":
        try:
            r = mealie.recipe(user["mealie_token"], recipe_id)
        except mealie.MealieNotFound:
            return _page(request, user, "That recipe no longer exists", form)
        recipe_id, name = r["id"], r["name"]  # Mealie's canonical id, not the posted string
        nutrition = r.get("nutrition") or {}
        if cal is None:
            cal = mealie.leading_number(nutrition.get("calories"))
        if prot is None:
            prot = mealie.leading_number(nutrition.get("proteinContent"))
    else:
        recipe_id = None
        if not description:
            return _page(request, user, "Add a description or pick a recipe" if kind != "other" else "Add a description", form)

    now = _now().isoformat()
    con = db.connect()
    try:
        cur = con.execute(
            "INSERT INTO entries (user_id, day, created_at, kind, recipe_id, recipe_name, description, calories, protein_g) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user["mealie_user_id"], local_today().isoformat(), now, kind, recipe_id, name, description or None, cal, prot),
        )
        error = None
        data = photo.file.read(photos.MAX_BYTES + 1) if photo else b""
        if data:
            try:
                path = photos.save(data)
                con.execute(
                    "INSERT INTO photos (entry_id, user_id, recipe_id, path, private, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (cur.lastrowid, user["mealie_user_id"], recipe_id, path, 0 if show_photo and recipe_id else 1, now),
                )
            except ValueError as e:
                error = (
                    "That photo is too large (15 MB max)" if str(e) == "too large" else "That file isn't an image"
                )
        con.commit()
    finally:
        con.close()
    return _page(request, user, error, "cooked") if error else RedirectResponse("/", 303)  # the photo field is in "I cooked"


@router.post("/entries/{entry_id}/delete")
def delete_entry(entry_id: int, user=Depends(auth.current_user)):
    uid = user["mealie_user_id"]
    con = db.connect()
    try:
        if not con.execute("SELECT 1 FROM entries WHERE id = ? AND user_id = ?", (entry_id, uid)).fetchone():
            raise HTTPException(404)
        paths = [r[0] for r in con.execute("SELECT path FROM photos WHERE entry_id = ? AND user_id = ?", (entry_id, uid))]
        con.execute("DELETE FROM photos WHERE entry_id = ? AND user_id = ?", (entry_id, uid))
        con.execute("DELETE FROM entries WHERE id = ? AND user_id = ?", (entry_id, uid))
        con.commit()
    finally:
        con.close()
    for p in paths:
        try:
            os.remove(os.path.join(photos.photos_dir(), p))
        except FileNotFoundError:
            pass
    return RedirectResponse("/", 303)


@router.get("/photos/{photo_id}")
def photo(photo_id: int, user=Depends(auth.current_user)):
    if not 1 <= photo_id < 2**63:
        raise HTTPException(404)
    con = db.connect()
    try:
        row = con.execute(
            "SELECT path FROM photos WHERE id = ? AND (user_id = ? OR (private = 0 AND recipe_id IS NOT NULL))",
            (photo_id, user["mealie_user_id"]),
        ).fetchone()
    finally:
        con.close()
    f = row and os.path.join(photos.photos_dir(), row["path"])
    if not f or not os.path.exists(f):
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg")


@router.post("/photos/{photo_id}/private")
def toggle_private(photo_id: int, user=Depends(auth.current_user)):
    if not 1 <= photo_id < 2**63:
        raise HTTPException(404)
    con = db.connect()
    try:
        row = con.execute(
            "SELECT recipe_id FROM photos WHERE id = ? AND user_id = ?", (photo_id, user["mealie_user_id"])
        ).fetchone()
        if not row or row["recipe_id"] is None:
            raise HTTPException(404)
        con.execute("UPDATE photos SET private = 1 - private WHERE id = ?", (photo_id,))
        con.commit()
    finally:
        con.close()
    return RedirectResponse(f"/r/{row['recipe_id']}", 303)


@router.post("/weight")
def weight(request: Request, lbs: str = Form(), user=Depends(auth.current_user)):
    try:
        n = float(lbs)
    except ValueError:
        n = 0
    if not 50 <= n <= 1000:
        return _page(request, user, "Weight must be between 50 and 1000 lbs")
    con = db.connect()
    try:
        con.execute(
            "INSERT INTO weights (user_id, date, lbs) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, date) DO UPDATE SET lbs = excluded.lbs",
            (user["mealie_user_id"], local_today().isoformat(), n),
        )
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/", 303)
