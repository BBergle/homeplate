import base64
import hashlib
import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken

DEFAULT_MODEL = "openai/gpt-5-nano"
client = httpx.Client(base_url="https://openrouter.ai/api/v1", timeout=10)

_TOOL = {"type": "openrouter:web_search", "parameters": {"engine": "parallel", "mode": "turbo", "max_results": 5}}
_DOWN = "The AI service didn't answer. Try again."


class AIError(Exception):
    """str(e) is a sentence fit to show the person."""


def secret_ok() -> bool:
    return os.environ.get("SECRET_KEY", "") not in ("", "dev", "change-me")


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"ai-key:" + os.environ.get("SECRET_KEY", "").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def check_key(key: str) -> bool | None:
    try:
        r = client.get("/key", headers=_headers(key))
    except httpx.HTTPError:
        return None
    if r.status_code == 401:
        return False
    return True if r.status_code == 200 else None


def model_check(model: str) -> tuple[bool, str | None]:
    try:
        models = client.get("/models").json()["data"]
        found = next((m for m in models if m["id"] == model), None)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return True, None
    if found is None:
        return False, None
    tools = "tools" in (found.get("supported_parameters") or [])
    photos = "image" in (found.get("architecture", {}).get("input_modalities") or [])
    if tools and photos:
        return True, None
    return True, "can't " + ("read photos" if tools else "use tools" if photos else "use tools or read photos")


def _error(code: int, body: dict, model: str) -> AIError:
    reason = ((body.get("error") or {}).get("metadata") or {}).get("reason")
    if code == 401:
        return AIError("OpenRouter rejected your key. Check it in Settings.")
    if code == 402 and reason == "in_flight_budget_exhausted":
        return AIError("OpenRouter is still settling your last requests. Try again in a couple of minutes.")
    if code == 402:
        return AIError("Your OpenRouter account is out of credit.")
    if code == 429:
        return AIError("The AI service is busy. Try again in a minute.")
    if code == 404:
        return AIError(f"OpenRouter couldn't use the model {model}. Check it in Settings.")
    return AIError(_DOWN)


def _clean_url(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "utm_source"])
    return urlunsplit(parts._replace(query=query))


def chat(key: str, model: str, messages: list[dict]) -> dict:
    body = {"model": model, "max_tokens": 4000, "reasoning": {"effort": "low"}, "messages": messages, "tools": [_TOOL]}
    try:
        r = client.post("/chat/completions", headers=_headers(key), json=body, timeout=180)
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise AIError(_DOWN) from e
    if not isinstance(data, dict):
        raise AIError(_DOWN)
    if data.get("error") or r.status_code >= 400:
        code = (data.get("error") or {}).get("code")
        raise _error(code if isinstance(code, int) else r.status_code, data, model)
    try:
        choice = data["choices"][0]
        content, annotations = choice["message"]["content"], choice["message"].get("annotations") or []
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(_DOWN) from e
    if not content:
        if choice.get("finish_reason") == "length":
            raise AIError("The answer was cut off. Ask again, or ask for something shorter.")
        raise AIError(_DOWN)
    text = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", content)
    text = re.sub(r"\[([^\]]*)\]\(http[^)]*\)", r"\1", text).strip()
    sources, seen = [], set()
    for a in annotations:
        c = a.get("url_citation") or {}
        url = _clean_url(c.get("url") or "")
        if url and url not in seen:
            seen.add(url)
            sources.append({"url": url, "title": c.get("title") or urlsplit(url).hostname})
    return {"text": text, "sources": sources[:8]}
