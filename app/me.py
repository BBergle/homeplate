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


def num(n: float | None) -> str:
    """180.0 -> "180", 180.5 -> "180.5"; None -> ""."""
    if n is None:
        return ""
    n = round(n, 2)
    return str(int(n)) if n == int(n) else str(n)


CRITERIA = {
    "First cook": "Log your first cook",
    "10 meals": "Cook 10 meals",
    "50 meals": "Cook 50 meals",
    "4-week streak": "Hit your goal 4 weeks running",
    "5 different recipes": "Cook 5 different recipes",
}


def sparkline(points: list[tuple[date, float]], w: int = 320, h: int = 80, goal: float | None = None) -> dict:
    """Chart geometry: the line, its area polygon, the last point and the goal line's y (None if the goal is outside the range)."""
    if len(points) < 2:
        return {}
    pad = 4
    d0, d1 = points[0][0], points[-1][0]
    lo, hi = min(p[1] for p in points), max(p[1] for p in points)
    span = (d1 - d0).days or 1
    y_of = lambda v: h / 2 if hi == lo else pad + (hi - v) / (hi - lo) * (h - 2 * pad)
    xy = [(pad + (d - d0).days / span * (w - 2 * pad), y_of(v)) for d, v in points]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    area = f"{line} {xy[-1][0]:.1f},{h} {xy[0][0]:.1f},{h}"
    goal_y = y_of(goal) if goal is not None and lo <= goal <= hi else None
    return {"line": line, "area": area, "last": (round(xy[-1][0], 1), round(xy[-1][1], 1)), "goal_y": goal_y}


def _page(request, user, error=None):
    uid = user["mealie_user_id"]
    t = today.local_today()
    con = db.connect()
    try:
        meals = con.execute(
            "SELECT day, recipe_id FROM entries WHERE user_id = ? AND kind IN ('cooked', 'leftovers')", (uid,)
        ).fetchall()
        cooked = con.execute(
            "SELECT recipe_id, recipe_name, COUNT(*) AS n FROM entries WHERE user_id = ? AND kind IN ('cooked', 'leftovers') "
            "AND recipe_id IS NOT NULL GROUP BY recipe_id ORDER BY MAX(created_at) DESC",
            (uid,),
        ).fetchall()
        ws = con.execute(
            "SELECT date, lbs FROM weights WHERE user_id = ? AND date >= ? ORDER BY date",
            (uid, (t - timedelta(days=90)).isoformat()),
        ).fetchall()
        pending = (
            con.execute("SELECT COUNT(*) FROM requests WHERE status = 'pending'").fetchone()[0] if user["is_admin"] else 0
        )
    finally:
        con.close()
    days = [date.fromisoformat(m["day"]) for m in meals]
    totals = stats.week_totals(days, t)
    points = [(date.fromisoformat(r["date"]), r["lbs"]) for r in ws]
    goal, streak = user["weekly_goal"], stats.streak(totals, user["weekly_goal"])
    monday = t - timedelta(days=t.weekday())
    if streak:
        streak_text = f"Streak {streak} week{'' if streak == 1 else 's'}"
    elif any(d < monday for d in days):
        streak_text = "Fresh start this week"
    else:
        streak_text = None
    longest = stats.longest_run(totals, goal)
    badges = [
        {"name": n, "earned": e, "caption": "Earned" if e else CRITERIA.get(n, "")}
        for n, e in stats.achievements(len(meals), len({m["recipe_id"] for m in meals if m["recipe_id"]}), longest)
    ]
    sp = sparkline(points, goal=user["weight_goal"])
    ctx = {
        "user": user,
        "pending": pending,
        "error": error,
        "week_count": totals[-1],
        "week_extra": max(0, totals[-1] - goal),
        "streak_text": streak_text,
        "badges": badges,
        "saved": f"{max(0, stats.savings(len(meals), user['delivery_cost'], user['home_meal_cost'])):,.0f}",
        "home_meals": len(meals),
        "cooked": cooked,
        "latest": num(round(points[-1][1], 1)) if points else None,
        "weight_goal": num(user["weight_goal"]),
        "spark": sp,
        "spark_label": (
            f"Weight went from {num(round(points[0][1], 1))} to {num(round(points[-1][1], 1))} lbs, last 90 days" if sp else ""
        ),
        "v": {k: num(user[k]) for k in FIELDS},
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
