import math
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import auth, db, stats, today

router = APIRouter()

# field -> (min, max, whole number, optional)
FIELDS = {
    "weekly_goal": (1, 21, True, False),
    "cal_target": (500, 10000, True, True),
    "protein_target": (0, 500, True, True),
    "weight_goal": (50, 1000, False, True),
    "delivery_cost": (0, 500, False, False),
    "home_meal_cost": (0, 500, False, False),
}


def sparkline(points: list[tuple[date, float]], w: int = 320, h: int = 80) -> str:
    if len(points) < 2:
        return ""
    pad = 4
    d0, d1 = points[0][0], points[-1][0]
    lo, hi = min(p[1] for p in points), max(p[1] for p in points)
    span = (d1 - d0).days or 1
    out = []
    for d, v in points:
        x = pad + (d - d0).days / span * (w - 2 * pad)
        y = h / 2 if hi == lo else pad + (hi - v) / (hi - lo) * (h - 2 * pad)
        out.append(f"{x:.1f},{y:.1f}")
    return " ".join(out)


def _page(request, user, error=None):
    uid = user["mealie_user_id"]
    t = today.local_today()
    con = db.connect()
    try:
        meals = con.execute(
            "SELECT day, recipe_id FROM entries WHERE user_id = ? AND kind IN ('cooked', 'leftovers')", (uid,)
        ).fetchall()
        ws = con.execute(
            "SELECT date, lbs FROM weights WHERE user_id = ? AND date >= ? ORDER BY date",
            (uid, (t - timedelta(days=90)).isoformat()),
        ).fetchall()
    finally:
        con.close()
    totals = stats.week_totals([date.fromisoformat(m["day"]) for m in meals], t)
    points = [(date.fromisoformat(r["date"]), r["lbs"]) for r in ws]
    ctx = {
        "user": user,
        "error": error,
        "this_week": totals[-1],
        "streak": stats.streak(totals, user["weekly_goal"]),
        "achievements": stats.achievements(
            len(meals), len({m["recipe_id"] for m in meals if m["recipe_id"]}), stats.longest_run(totals, user["weekly_goal"])
        ),
        "saved": f"{stats.savings(len(meals), user['delivery_cost'], user['home_meal_cost']):,.0f}",
        "latest": points[-1][1] if points else None,
        "line": sparkline(points),
    }
    return auth.templates.TemplateResponse(request, "me.html", ctx)


@router.get("/me")
def me(request: Request, user=Depends(auth.current_user)):
    return _page(request, user)


@router.post("/settings")
async def settings(request: Request, user=Depends(auth.current_user)):
    form = await request.form()
    vals = {}
    for name, (lo, hi, whole, optional) in FIELDS.items():
        s = str(form.get(name, "")).strip()
        if not s and optional:
            vals[name] = None
            continue
        try:
            n = float(s)
        except ValueError:
            n = math.nan
        if not lo <= n <= hi or (whole and n != int(n)):  # nan fails the range check
            return _page(request, user, f"{name.replace('_', ' ')} must be a {'whole ' if whole else ''}number from {lo} to {hi}")
        vals[name] = int(n) if whole else n
    con = db.connect()
    try:
        con.execute(
            "UPDATE users SET " + ", ".join(f"{k} = ?" for k in vals) + " WHERE mealie_user_id = ?",
            (*vals.values(), user["mealie_user_id"]),
        )
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/me", 303)


@router.get("/order")
def order(request: Request, user=Depends(auth.current_user)):
    return auth.templates.TemplateResponse(request, "soon.html", {"blurb": "Order groceries from your shopping list."})


@router.get("/ask")
def ask(request: Request, user=Depends(auth.current_user)):
    return auth.templates.TemplateResponse(request, "soon.html", {"blurb": "Ask food and nutrition questions."})
