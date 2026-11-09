import os
import re

import httpx

client = httpx.Client(base_url=os.environ.get("MEALIE_URL", "http://mealie:9000"), timeout=10)


class MealieError(Exception):
    """Mealie unreachable or answered 5xx."""


class MealieNotFound(MealieError):
    """Mealie answered 404."""


class MealieAuthError(Exception):
    """Mealie rejected the credentials or token (401), or locked the account (423)."""


def _request(method: str, path: str, token: str | None = None, **kw) -> dict | list:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = client.request(method, path, headers=headers, **kw)
    except httpx.HTTPError as e:
        raise MealieError(type(e).__name__) from e
    if r.status_code in (401, 423):
        raise MealieAuthError()
    if r.status_code == 404:
        raise MealieNotFound()
    if r.status_code >= 500:
        raise MealieError(f"Mealie answered {r.status_code}")
    try:
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise MealieError(type(e).__name__) from e


def login(username: str, password: str) -> str:
    data = {"username": username, "password": password, "remember_me": "true"}
    return _request("POST", "/api/auth/token", data=data)["access_token"]


def refresh(token: str) -> str:
    return _request("POST", "/api/auth/refresh", token)["access_token"]


def me(token: str) -> dict:
    return _request("GET", "/api/users/self", token)


def search_recipes(token: str, q: str) -> list[dict]:
    return _request("GET", "/api/recipes", token, params={"search": q})["items"]


def recipe(token: str, slug_or_id: str) -> dict:
    return _request("GET", f"/api/recipes/{slug_or_id}", token)


def planned_today(token: str) -> list[dict]:
    entries = _request("GET", "/api/households/mealplans/today", token)
    return [e["recipe"] for e in entries if e.get("recipe")]


def leading_number(value: str | None) -> int | None:
    m = re.search(r"\d+", value or "")
    return int(m.group()) if m else None
