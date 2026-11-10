import json

import httpx
import pytest
from conftest import CHAT, cite, err, reply

from app import ai


def test_encrypt_round_trip_and_changed_secret(mock_ai, monkeypatch):
    tok = ai.encrypt("sk-or-abc")
    assert "sk-or-abc" not in tok and ai.decrypt(tok) == "sk-or-abc"
    assert ai.decrypt(None) is None and ai.decrypt("garbage") is None
    monkeypatch.setenv("SECRET_KEY", "a-different-secret")
    assert ai.decrypt(tok) is None


@pytest.mark.parametrize("value,ok", [(None, False), ("", False), ("dev", False), ("change-me", False), ("x" * 32, True)])
def test_secret_ok(monkeypatch, value, ok):
    if value is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", value)
    assert ai.secret_ok() is ok


def test_chat_request_and_result(mock_ai):
    seen = {}

    def handler(request):
        seen["auth"], seen["body"] = request.headers["authorization"], json.loads(request.content)
        seen["timeout"] = request.extensions["timeout"]["read"]
        return reply("Hello", [cite("https://k.com/r", "King Arthur")])

    mock_ai[CHAT] = handler
    msgs = [{"role": "user", "content": "hi"}]
    assert ai.chat("sk-or-abc", "openai/gpt-5-nano", msgs) == {"text": "Hello", "sources": [{"url": "https://k.com/r", "title": "King Arthur"}]}
    assert seen["auth"] == "Bearer sk-or-abc"
    assert seen["timeout"] == 180
    assert seen["body"] == {"model": "openai/gpt-5-nano", "max_tokens": 4000, "reasoning": {"effort": "low"}, "messages": msgs,
                            "tools": [{"type": "openrouter:web_search", "parameters": {"engine": "parallel", "mode": "turbo", "max_results": 5}}]}


def test_chat_cleans_text_and_sources(mock_ai):
    mock_ai[CHAT] = reply(
        "Try this ([k.com](https://k.com/r?utm_source=openai)). See [King Arthur](https://k.com/r).",
        [cite("https://k.com/r?utm_source=openai&x=1"), cite("https://k.com/r?x=1", "dup"),
         cite("javascript:alert(1)", "bad"), cite("ftp://k.com/f", "bad")] + [cite(f"https://s{i}.com/") for i in range(10)])
    out = ai.chat("k", "m", [])
    assert out["text"] == "Try this. See King Arthur."
    assert out["sources"][0] == {"url": "https://k.com/r?x=1", "title": "k.com"}
    assert len(out["sources"]) == 8 and all(s["url"].startswith("https://") for s in out["sources"])


@pytest.mark.parametrize("response,text", [
    (err(401), "OpenRouter rejected your key. Check it in Settings."),
    (err(402), "Your OpenRouter account is out of credit."),
    (err(402, reason="in_flight_budget_exhausted"), "OpenRouter is still settling your last requests. Try again in a couple of minutes."),
    (err(429), "The AI service is busy. Try again in a minute."),
    (err(404), "OpenRouter couldn't use the model m. Check it in Settings."),
    (err(500), "The AI service didn't answer. Try again."),
    (httpx.ConnectError("down"), "The AI service didn't answer. Try again."),
    (httpx.Response(200, json={"error": {"code": 402, "message": "x"}}), "Your OpenRouter account is out of credit."),
    (httpx.Response(200, text="not json"), "The AI service didn't answer. Try again."),
    (reply("", finish="length"), "The answer was cut off. Ask again, or ask for something shorter."),
    (reply(None), "The AI service didn't answer. Try again."),
])
def test_chat_errors(mock_ai, response, text):
    mock_ai[CHAT] = response
    with pytest.raises(ai.AIError) as e:
        ai.chat("k", "m", [])
    assert str(e.value) == text


def test_key_never_in_error_or_log(mock_ai, caplog):
    mock_ai[CHAT] = err(401)
    with pytest.raises(ai.AIError) as e:
        ai.chat("sk-or-secret", "m", [])
    assert "sk-or-secret" not in str(e.value) and "sk-or-secret" not in caplog.text


def test_check_key(mock_ai):
    assert ai.check_key("k") is True
    mock_ai[("GET", "/api/v1/key")] = err(401)
    assert ai.check_key("k") is False
    mock_ai[("GET", "/api/v1/key")] = httpx.ConnectError("down")
    assert ai.check_key("k") is None


def test_model_check(mock_ai):
    assert ai.model_check("openai/gpt-5-nano") == (True, None)
    assert ai.model_check("text/only") == (True, "can't use tools or read photos")
    assert ai.model_check("nope/x") == (False, None)
    mock_ai[("GET", "/api/v1/models")] = httpx.ConnectError("down")
    assert ai.model_check("nope/x") == (True, None)
