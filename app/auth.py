import os
import re
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


def base_url(request: Request) -> str:
    return os.environ.get("BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")


def safe_next(value: str | None) -> str | None:
    """A post-login destination, only if it is a recipe path; anything else is None."""
    return value if value and re.fullmatch(r"/r/[A-Za-z0-9-]{1,64}", value) else None


def drop_session(request: Request) -> RedirectResponse:
    con = db.connect()
    con.execute("DELETE FROM sessions WHERE id = ?", (request.cookies.get("sid", ""),))
    con.commit()
    con.close()
    if request.headers.get("HX-Request"):
        resp = Response(headers={"HX-Redirect": "/login"})  # htmx would swap a followed redirect into the page
    else:
        dest = safe_next(request.url.path) if request.method == "GET" else None
        resp = RedirectResponse(f"/login?next={dest}" if dest else "/login", 303)
    resp.delete_cookie("sid")
    return resp


def _signups_open() -> bool:
    from app import access  # access imports this module

    return access.signups_open()


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": False, "next": safe_next(request.query_params.get("next")), "signups_open": _signups_open()})


@router.post("/login")
def login(request: Request, username: str = Form(), password: str = Form(), next: str = Form("")):
    try:
        token = mealie.login(username, password)
    except mealie.MealieAuthError as e:
        error = "Too many attempts. Try again later." if isinstance(e, mealie.MealieLocked) else "Wrong username or password"
        return templates.TemplateResponse(request, "login.html", {"error": error, "next": safe_next(next), "signups_open": _signups_open()}, status_code=401)
    return start_session(mealie.me(token), token, safe_next(next))


def start_session(user: dict, token: str, dest: str | None = None) -> Response:
    now = _now()
    sid = secrets.token_urlsafe(32)
    con = db.connect()
    con.execute(
        "INSERT OR IGNORE INTO users (mealie_user_id, name) VALUES (?, ?)", (user["id"], user["fullName"])
    )
    con.execute("UPDATE users SET is_admin = ? WHERE mealie_user_id = ?", (int(bool(user.get("admin"))), user["id"]))
    con.execute(
        "INSERT INTO sessions (id, user_id, mealie_token, refreshed_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (sid, user["id"], token, now.isoformat(), (now + timedelta(days=SESSION_DAYS)).isoformat()),
    )
    con.commit()
    con.close()
    resp = RedirectResponse(dest or "/", 303)
    resp.set_cookie(
        "sid", sid, max_age=400 * 86400, httponly=True, samesite="lax",
        secure=os.environ.get("BASE_URL", "").startswith("https"),
    )
    return resp


@router.post("/logout")
def logout(request: Request):
    return drop_session(request)
