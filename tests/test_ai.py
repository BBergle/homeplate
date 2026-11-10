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
    assert ai.chat("sk-or-abc", "openai/gpt-5-nano", msgs) == {"text": "Hello", "sources": [{"url": "https://k.com/r", "title": "King Arthur"}], "calls": [],
                                                           "message": {"role": "assistant", "content": "Hello", "tool_calls": None}}
    assert seen["auth"] == "Bearer sk-or-abc"
    assert seen["timeout"] == 180
    assert seen["body"] == {"model": "openai/gpt-5-nano", "max_tokens": 4000, "reasoning": {"effort": "low"}, "messages": msgs,
                            "tools": [{"type": "openrouter:web_search", "parameters": {"engine": "parallel", "mode": "turbo", "max_results": 5}}]}


def test_chat_drops_bare_urls_in_parentheses(mock_ai):
    mock_ai[CHAT] = reply("Sources\n- King Arthur (https://k.com/r?x=1)\n- Other (https://o.com/)")
    assert ai.chat("k", "m", [])["text"] == "Sources\n- King Arthur\n- Other"


def test_chat_cleans_text_and_sources(mock_ai):
    mock_ai[CHAT] = reply(
        "Try this ([k.com](https://k.com/r?utm_source=openai)). See [King Arthur](https://k.com/r).",
        [cite("https://k.com/r?utm_source=openai&x=1"), cite("https://k.com/r?x=1", "dup"),
         cite("javascript:alert(1)", "bad"), cite("ftp://k.com/f", "bad")] + [cite(f"https://s{i}.com/") for i in range(10)])
    out = ai.chat("k", "m", [])
    assert out["text"] == "Try this. See King Arthur."
    assert out["sources"][0] == {"url": "https://k.com/r?x=1", "title": "k.com"}
    assert len(out["sources"]) == 8 and all(s["url"].startswith("https://") for s in out["sources"])


def test_chat_strips_trailing_sources_block_when_sources_exist(mock_ai):
    mock_ai[CHAT] = reply("Use bread flour.\n\n  sources:  \n- King Arthur\n- Other", [cite("https://k.com/r")])
    assert ai.chat("k", "m", [])["text"] == "Use bread flour."
    mock_ai[CHAT] = reply("Use bread flour.\nSources\n- King Arthur", [cite("https://k.com/r")])
    assert ai.chat("k", "m", [])["text"] == "Use bread flour."


def test_chat_keeps_sources_block_without_source_links(mock_ai):
    mock_ai[CHAT] = reply("Use bread flour.\nSources:\n- King Arthur")
    assert ai.chat("k", "m", [])["text"] == "Use bread flour.\nSources:\n- King Arthur"


def test_chat_keeps_sources_mid_sentence(mock_ai):
    mock_ai[CHAT] = reply("Good protein sources: eggs and beans.", [cite("https://k.com/r")])
    assert ai.chat("k", "m", [])["text"] == "Good protein sources: eggs and beans."


SIMPLY = ("Simply Recipes rolls are pillowy, with tips like freezing unbaked or baked rolls.\n\n"
          "Source: Simply Recipes, Best Homemade Cinnamon Rolls Recipe\nhttps://www.simplyrecipes.com/recipes/bakery_style_cinnamon_rolls")


def test_chat_strips_singular_source_with_text_and_bare_url(mock_ai):
    mock_ai[CHAT] = reply(SIMPLY, [cite("https://www.simplyrecipes.com/recipes/bakery_style_cinnamon_rolls")])
    assert ai.chat("k", "m", [])["text"].endswith("unbaked or baked rolls.") and "Source" not in ai.chat("k", "m", [])["text"]


def test_chat_keeps_source_word_without_colon(mock_ai):
    mock_ai[CHAT] = reply("Sources of protein include eggs.", [cite("https://k.com/r")])
    assert ai.chat("k", "m", [])["text"] == "Sources of protein include eggs."


def test_chat_removes_url_only_lines_but_not_inline_urls(mock_ai):
    mock_ai[CHAT] = reply("Intro.\n- https://a.com/x\nSee https://b.com/y for more.\n\u2022 https://c.com/z\nEnd.", [cite("https://k.com/r")])
    assert ai.chat("k", "m", [])["text"] == "Intro.\nSee https://b.com/y for more.\nEnd."


def test_chat_keeps_source_block_and_urls_without_sources(mock_ai):
    mock_ai[CHAT] = reply(SIMPLY)
    assert ai.chat("k", "m", [])["text"] == SIMPLY


def test_chat_only_sources_block_is_blank_error(mock_ai):
    mock_ai[CHAT] = reply("Sources:\n- King Arthur", [cite("https://k.com/r")])
    with pytest.raises(ai.AIError, match="didn't answer"):
        ai.chat("k", "m", [])


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
    (reply("  "), "The AI service didn't answer. Try again."),
    (reply("([k.com](https://k.com))"), "The AI service didn't answer. Try again."),
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


T = {"type": "function", "function": {"name": "get_recipe", "parameters": {"type": "object", "properties": {}}}}
SEARCH = {"type": "openrouter:web_search", "parameters": {"engine": "parallel", "mode": "turbo", "max_results": 5}}


def test_chat_sends_function_tools_after_search(mock_ai):
    seen = []
    mock_ai[CHAT] = lambda request: (seen.append(json.loads(request.content)), reply("Hi"))[1]
    ai.chat("k", "m", [], tools=[T])
    ai.chat("k", "m", [])
    assert seen[0]["tools"] == [SEARCH, T]
    assert seen[1]["tools"] == [SEARCH]


def test_chat_returns_calls_and_message(mock_ai):
    raw = [{"id": "c1", "type": "function", "function": {"name": "get_recipe", "arguments": "{\"id\": \"r1\"}"}},
           {"id": "c2", "type": "function", "function": {"name": "x", "arguments": "not json"}},
           {"id": "c3", "type": "function", "function": {"name": "y", "arguments": "[1]"}}]
    mock_ai[CHAT] = httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": raw}}]})
    out = ai.chat("k", "m", [], tools=[T])
    assert out["text"] == "" and out["calls"] == [{"id": "c1", "name": "get_recipe", "args": {"id": "r1"}},
                                                  {"id": "c2", "name": "x", "args": {}}, {"id": "c3", "name": "y", "args": {}}]
    assert out["message"] == {"role": "assistant", "content": None, "tool_calls": raw}


def test_chat_plain_answer_has_no_calls(mock_ai):
    mock_ai[CHAT] = reply("Hi")
    out = ai.chat("k", "m", [])
    assert out["calls"] == [] and out["message"]["content"] == "Hi"
