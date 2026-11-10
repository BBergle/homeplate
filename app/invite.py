from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app import auth, mealie

router = APIRouter()

REJECTED = "Couldn't create the account. The invite may have been used, or the username or email is taken."


NAME_ERROR = "Give the household a name of 1 to 50 characters."


def make_invite(token: str, where: str, household_name: str) -> str:
    """Create the household when asked (ValueError on a bad name), then a single-use invite; returns its token."""
    name = household_name.strip()
    if where == "new" and not 1 <= len(name) <= 50:
        raise ValueError(NAME_ERROR)
    return mealie.create_invite(token, mealie.create_household(token, name) if where == "new" else None)


def _page(request: Request, status: int = 200, **ctx):
    return auth.templates.TemplateResponse(request, "invite.html", ctx, status_code=status)


def _allowed(user: dict):
    """Live permission check: (may_invite, is_admin)."""
    me = mealie.me(user["mealie_token"])
    return me.get("admin", False) or me.get("canInvite", False), me.get("admin", False)


@router.get("/invite")
def form(request: Request, user=Depends(auth.current_user)):
    may, admin = _allowed(user)
    return _page(request, 200 if may else 403, may=may, admin=admin)


@router.post("/invite")
def create(request: Request, where: str = Form("mine"), household_name: str = Form(""), user=Depends(auth.current_user)):
    may, admin = _allowed(user)
    if not may or (where == "new" and not admin):
        return _page(request, 403, may=False, admin=admin)
    try:
        link = f"{auth.base_url(request)}/join/{make_invite(user['mealie_token'], where, household_name)}"
    except ValueError:
        return _page(request, may=True, admin=admin, error=NAME_ERROR)
    return _page(request, may=True, admin=admin, link=link)


def _join(request: Request, token: str, error: str | None = None, **values):
    return auth.templates.TemplateResponse(request, "join.html", {"token": token, "error": error, "v": values})


@router.get("/join/{token}")
def join_form(request: Request, token: str):
    return _join(request, token)


@router.post("/join/{token}")
def join(
    request: Request, token: str, name: str = Form(""), email: str = Form(""), username: str = Form(""),
    password: str = Form(""), password_confirm: str = Form(""),
):
    name, email, username = name.strip(), email.strip(), username.strip()
    error = (
        "Enter your name (up to 100 characters)." if not 1 <= len(name) <= 100
        else "Enter a valid email address." if "@" not in email or len(email) > 254
        else "Choose a username (up to 50 characters)." if not 1 <= len(username) <= 50
        else "Password must be 8 to 200 characters." if not 8 <= len(password) <= 200
        else "The two passwords don't match." if password != password_confirm
        else None
    )
    kept = {"name": name, "email": email if len(email) <= 254 else "", "username": username}  # over-long email is not echoed
    if error:
        return _join(request, token, error, **kept)
    try:
        mealie.register(token, name, email, username, password)
    except mealie.MealieRejected:
        return _join(request, token, REJECTED, **kept)
    try:
        session_token = mealie.login(username, password)
        return auth.start_session(mealie.me(session_token), session_token)
    except (mealie.MealieError, mealie.MealieAuthError):  # the account exists; let them sign in
        return RedirectResponse("/login", 303)
