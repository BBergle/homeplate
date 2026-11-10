import os
import re
from urllib.parse import quote

import httpx

client = httpx.Client(base_url=os.environ.get("MEALIE_URL", "http://mealie:9000"), timeout=10)


class MealieError(Exception):
    """Mealie unreachable or answered 5xx."""


class MealieNotFound(MealieError):
    """Mealie answered 404."""


class MealieRejected(MealieError):
    """Mealie answered 400, 403, 409 or 422: it refused the request."""


class MealieAuthError(Exception):
    """Mealie rejected the credentials or token (401), or locked the account (423)."""


class MealieLocked(MealieAuthError):
    """Mealie answered 423: too many failed logins."""


def _send(method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = client.request(method, path, headers=headers, **kw)
    except httpx.HTTPError as e:
        raise MealieError(type(e).__name__) from e
    if r.status_code == 423:
        raise MealieLocked()
    if r.status_code == 401:
        raise MealieAuthError()
    if r.status_code == 404:
        raise MealieNotFound()
    if r.status_code in (400, 403, 409, 422):
        raise MealieRejected(f"Mealie answered {r.status_code}")
    if r.status_code >= 500:
        raise MealieError(f"Mealie answered {r.status_code}")
    try:
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise MealieError(type(e).__name__) from e
    return r


def _request(method: str, path: str, token: str | None = None, **kw) -> dict | list:
    try:
        return _send(method, path, token, **kw).json()
    except (httpx.HTTPError, ValueError) as e:
        raise MealieError(type(e).__name__) from e


def login(username: str, password: str) -> str:
    data = {"username": username, "password": password, "remember_me": "true"}
    return _request("POST", "/api/auth/token", data=data)["access_token"]


def refresh(token: str) -> str:
    return _request("POST", "/api/auth/refresh", token)["access_token"]


def me(token: str) -> dict:
    return _request("GET", "/api/users/self", token)


def create_household(token: str, name: str) -> str:
    # real Mealie 500s without groupId, so create it in the admin's own group
    return _request("POST", "/api/admin/households", token, json={"name": name, "groupId": me(token)["groupId"]})["id"]


def create_invite(token: str, household_id: str | None) -> str:
    body = {"uses": 1} | ({"householdId": household_id} if household_id else {})
    return _request("POST", "/api/households/invitations", token, json=body)["token"]


def register(invite: str, full_name: str, email: str, username: str, password: str) -> None:
    body = {
        "groupToken": invite, "email": email, "username": username, "fullName": full_name,
        "password": password, "passwordConfirm": password,
    }
    _send("POST", "/api/users/register", json=body)


def search_recipes(token: str, q: str) -> list[dict]:
    return _request("GET", "/api/recipes", token, params={"search": q})["items"]


def recipe(token: str, slug_or_id: str) -> dict:
    return _request("GET", f"/api/recipes/{quote(slug_or_id, safe='')}", token)


def recipe_image(recipe_id: str) -> bytes | None:
    try:
        return _send("GET", f"/api/media/recipes/{quote(recipe_id, safe='')}/images/min-original.webp").content
    except MealieNotFound:
        return None


def planned_today(token: str) -> list[dict]:
    entries = _request("GET", "/api/households/mealplans/today", token)
    return [e["recipe"] for e in entries if e.get("recipe")]


def leading_number(value: str | None) -> int | None:
    m = re.search(r"\d+", value or "")
    return int(m.group()) if m else None
