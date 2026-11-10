import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import auth, db, invite, mealie

router = APIRouter()
MAX_PENDING = 20


class NotAdmin(Exception):
    """The signed-in user is not a Mealie admin (checked live)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def signups_open() -> bool:
    con = db.connect()
    try:
        return con.execute("SELECT value FROM instance WHERE key = 'signups_open'").fetchone() is not None
    finally:
        con.close()


def admin_user(user=Depends(auth.current_user)):
    if not mealie.me(user["mealie_token"]).get("admin", False):
        raise NotAdmin()
    return user


def _form(request: Request, error: str | None = None, **values):
    if not signups_open():
        raise HTTPException(404)
    return auth.templates.TemplateResponse(request, "request.html", {"error": error, "v": values}, status_code=200)


@router.get("/request")
def request_form(request: Request):
    return _form(request)


@router.post("/request")
def request_submit(request: Request, name: str = Form(""), email: str = Form(""), note: str = Form("")):
    name, email, note = name.strip(), email.strip(), note.strip()
    error = (
        "Enter your name (up to 100 characters)." if not 1 <= len(name) <= 100
        else "Enter a valid email address." if "@" not in email or len(email) > 254
        else "The note can be up to 200 characters." if len(note) > 200
        else None
    )
    if error:
        return _form(request, error, name=name, email=email if len(email) <= 254 else "", note=note if len(note) <= 200 else "")
    if not signups_open():
        raise HTTPException(404)
    secret = secrets.token_urlsafe(32)
    con = db.connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        n, dup = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(lower(email) = lower(?)), 0) FROM requests WHERE status = 'pending'", (email,)
        ).fetchone()
        if n >= MAX_PENDING or dup:
            con.rollback()
            return RedirectResponse("/request/sent", 303)  # same answer as success, nothing revealed
        con.execute(
            "INSERT INTO requests (secret, name, email, note, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (secret, name, email, note or None, _now()),
        )
        con.commit()
    finally:
        con.close()
    return RedirectResponse(f"/request/{secret}", 303)


def _status(request: Request, state: str, token: str | None = None):
    if state == "approved" and not token:
        state = "pending"  # claimed, invite not stored yet
    return auth.templates.TemplateResponse(request, "request_status.html", {"state": state, "token": token})


@router.get("/request/sent")
def request_sent(request: Request):
    return _status(request, "pending")


@router.get("/request/{secret}")
def request_status(request: Request, secret: str):
    con = db.connect()
    try:
        row = con.execute("SELECT status, invite_token FROM requests WHERE secret = ?", (secret,)).fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(404)
    return _status(request, row["status"], row["invite_token"])


def _admin_page(request: Request, error: str | None = None, status: int = 200):
    con = db.connect()
    try:
        pending = con.execute("SELECT * FROM requests WHERE status = 'pending' ORDER BY id").fetchall()
        recent = con.execute(
            "SELECT * FROM requests WHERE status != 'pending' ORDER BY decided_at DESC, id DESC LIMIT 20"
        ).fetchall()
    finally:
        con.close()
    ctx = {"open": signups_open(), "pending": pending, "recent": recent, "error": error, "base": auth.base_url(request)}
    return auth.templates.TemplateResponse(request, "admin.html", ctx, status_code=status)


@router.get("/admin")
def admin_page(request: Request, user=Depends(admin_user)):
    return _admin_page(request)


@router.post("/admin/signups")
def set_signups(open: str = Form(""), user=Depends(admin_user)):
    con = db.connect()
    try:
        if open == "1":
            con.execute("INSERT OR REPLACE INTO instance (key, value) VALUES ('signups_open', '1')")
        else:
            con.execute("DELETE FROM instance WHERE key = 'signups_open'")
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/admin", 303)


def _decide(con, rid: int, user, status: str):
    return con.execute(
        "UPDATE requests SET status = ?, decided_at = ?, decided_by = ? WHERE id = ? AND status = 'pending'",
        (status, _now(), user["mealie_user_id"], rid),
    )


def _exists(con, rid: int) -> None:
    if not con.execute("SELECT 1 FROM requests WHERE id = ?", (rid,)).fetchone():
        raise HTTPException(404)


@router.post("/admin/requests/{rid}/approve")
def approve(request: Request, rid: int, where: str = Form("mine"), household_name: str = Form(""), user=Depends(admin_user)):
    if where == "new" and not 1 <= len(household_name.strip()) <= 50:
        return _admin_page(request, invite.NAME_ERROR)
    con = db.connect()
    try:
        _exists(con, rid)
        # claim first, atomically: only the request that flips pending -> approved goes on to call Mealie
        claimed = _decide(con, rid, user, "approved").rowcount == 1
        con.commit()
        if claimed:
            try:
                token = invite.make_invite(user["mealie_token"], where, household_name)
                con.execute("UPDATE requests SET invite_token = ? WHERE id = ?", (token, rid))
            except BaseException:
                con.execute("UPDATE requests SET status = 'pending', decided_at = NULL, decided_by = NULL WHERE id = ?", (rid,))
                raise
            finally:
                con.commit()
    finally:
        con.close()
    return RedirectResponse("/admin", 303)


@router.post("/admin/requests/{rid}/decline")
def decline(rid: int, user=Depends(admin_user)):
    con = db.connect()
    try:
        _exists(con, rid)
        _decide(con, rid, user, "declined")
        con.commit()
    finally:
        con.close()
    return RedirectResponse("/admin", 303)
