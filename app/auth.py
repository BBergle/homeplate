import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import db, mealie

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["mealie_url"] = os.environ.get("MEALIE_PUBLIC_URL", "")
router = APIRouter()

SESSION_DAYS = 14


class LoginRequired(Exception):
    """No valid session."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def current_user(request: Request):
    con = db.connect()
    try:
        row = con.execute(
            "SELECT u.*, s.mealie_token, s.refreshed_at, s.expires_at FROM sessions s "
            "JOIN users u ON u.mealie_user_id = s.user_id WHERE s.id = ?",
            (request.cookies.get("sid", ""),),
        ).fetchone()
        now = _now()
        if not row or datetime.fromisoformat(row["expires_at"]) <= now:
            raise LoginRequired()
        if now - datetime.fromisoformat(row["refreshed_at"]) > timedelta(hours=24):
            try:
                token = mealie.refresh(row["mealie_token"])
            except mealie.MealieAuthError:
                raise
            except mealie.MealieError:
                return row  # Mealie down: keep the old token, refreshed_at unchanged so the next request retries
            con.execute(
                "UPDATE sessions SET mealie_token = ?, refreshed_at = ?, expires_at = ? WHERE id = ?",
                (token, now.isoformat(), (now + timedelta(days=SESSION_DAYS)).isoformat(), request.cookies["sid"]),
            )
            con.commit()
            row = dict(row) | {"mealie_token": token}
        return row
    finally:
        con.close()


def drop_session(request: Request) -> RedirectResponse:
    con = db.connect()
    con.execute("DELETE FROM sessions WHERE id = ?", (request.cookies.get("sid", ""),))
    con.commit()
    con.close()
    if request.headers.get("HX-Request"):
        resp = Response(headers={"HX-Redirect": "/login"})  # htmx would swap a followed redirect into the page
    else:
        resp = RedirectResponse("/login", 303)
    resp.delete_cookie("sid")
    return resp


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": False})


@router.post("/login")
def login(request: Request, username: str = Form(), password: str = Form()):
    try:
        token = mealie.login(username, password)
    except mealie.MealieAuthError as e:
        error = "Too many attempts. Try again later." if isinstance(e, mealie.MealieLocked) else "Wrong username or password"
        return templates.TemplateResponse(request, "login.html", {"error": error}, status_code=401)
    user = mealie.me(token)
    now = _now()
    sid = secrets.token_urlsafe(32)
    con = db.connect()
    con.execute(
        "INSERT OR IGNORE INTO users (mealie_user_id, name) VALUES (?, ?)", (user["id"], user["fullName"])
    )
    con.execute(
        "INSERT INTO sessions (id, user_id, mealie_token, refreshed_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (sid, user["id"], token, now.isoformat(), (now + timedelta(days=SESSION_DAYS)).isoformat()),
    )
    con.commit()
    con.close()
    resp = RedirectResponse("/", 303)
    resp.set_cookie(
        "sid", sid, max_age=400 * 86400, httponly=True, samesite="lax",
        secure=os.environ.get("BASE_URL", "").startswith("https"),
    )
    return resp


@router.post("/logout")
def logout(request: Request):
    return drop_session(request)
