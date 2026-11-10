from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import auth, db
from app.today import _now, _num, _page, local_today

router = APIRouter()

ACTIVITIES = ("cycling", "running", "walking", "strength", "swimming", "other")
INTENSITIES = ("easy", "moderate", "hard")
# MET (metabolic equivalent) by activity: (easy, moderate, hard)
MET = {
    "cycling": (4.0, 8.0, 10.0),
    "running": (7.0, 9.8, 11.5),
    "walking": (3.0, 3.8, 5.0),
    "strength": (3.5, 5.0, 6.0),
    "swimming": (6.0, 8.0, 10.0),
    "other": (3.0, 5.0, 7.0),
}
DEFAULT_LBS = 170.0
LB_TO_KG = 0.45359237


def estimate(activity: str, intensity: str, minutes: int, weight_lbs: float | None) -> int:
    """Calories burned above resting: (MET - 1) x kg x hours."""
    met = MET[activity][INTENSITIES.index(intensity)]
    return round((met - 1) * (weight_lbs or DEFAULT_LBS) * LB_TO_KG * minutes / 60)


def latest_weight(con, user_id: str) -> float | None:
    row = con.execute("SELECT lbs FROM weights WHERE user_id = ? ORDER BY date DESC LIMIT 1", (user_id,)).fetchone()
    return row["lbs"] if row else None


def _parse(activity: str, intensity: str, minutes: str):
    """(activity, intensity, minutes) or ValueError with a message for the user."""
    if activity not in ACTIVITIES:
        raise ValueError("Pick an activity")
    if intensity not in INTENSITIES:
        raise ValueError("Pick an effort level")
    mins = _num(minutes, "Minutes", 1, 1440)
    if mins is None:
        raise ValueError("Minutes must be a number from 1 to 1440")
    return activity, intensity, mins


@router.post("/workouts")
def add_workout(
    request: Request,
    activity: str = Form(""),
    intensity: str = Form(""),
    minutes: str = Form(""),
    calories: str = Form(""),
    note: str = Form(""),
    user=Depends(auth.current_user),
):
    uid = user["mealie_user_id"]
    note = note.strip()
    try:
        activity, intensity, mins = _parse(activity, intensity, minutes)
        cal = _num(calories, "Calories", 0, 20000)
        if len(note) > 200:
            raise ValueError("Note must be 200 characters or fewer")
    except ValueError as e:
        return _page(request, user, str(e), "workout")
    con = db.connect()
    try:
        source = "entered" if cal is not None else "estimated"
        if cal is None:
            cal = estimate(activity, intensity, mins, latest_weight(con, uid))
        con.execute(
            "INSERT INTO workouts (user_id, day, activity, minutes, intensity, calories, source, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, local_today().isoformat(), activity, mins, intensity, cal, source, note or None, _now().isoformat()),
        )
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/", 303)


@router.post("/workouts/estimate")
def estimate_fragment(
    request: Request,
    activity: str = Form(""),
    intensity: str = Form(""),
    minutes: str = Form(""),
    user=Depends(auth.current_user),
):
    ctx = {"value": "", "error": None, "hint": None}
    con = db.connect()
    try:
        lbs = latest_weight(con, user["mealie_user_id"])
    finally:
        con.close()
    try:
        activity, intensity, mins = _parse(activity, intensity, minutes)
        ctx["value"] = estimate(activity, intensity, mins, lbs)
        ctx["hint"] = f"Estimated from {mins} minute{'' if mins == 1 else 's'} at {intensity} effort and {lbs or 170:g} lb. Change it if you know better."
    except ValueError as e:
        ctx["error"] = str(e)
    ctx["has_weight"] = lbs is not None
    return auth.templates.TemplateResponse(request, "_workout_calories.html", ctx)


@router.post("/workouts/{workout_id}/delete")
def delete_workout(workout_id: int, user=Depends(auth.current_user)):
    if not 1 <= workout_id < 2**63:
        raise HTTPException(404)
    con = db.connect()
    try:
        cur = con.execute("DELETE FROM workouts WHERE id = ? AND user_id = ?", (workout_id, user["mealie_user_id"]))
        con.commit()
    finally:
        con.close()
    if not cur.rowcount:
        raise HTTPException(404)
    return RedirectResponse("/", 303)
