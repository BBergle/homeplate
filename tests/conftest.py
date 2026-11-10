import httpx
import pytest
from fastapi.testclient import TestClient

from app import ai, mealie
from app.main import app


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def mock_mealie(monkeypatch):
    """Dict of (method, path) -> httpx.Response (or an exception to raise). Edit it in tests."""
    routes = {("GET", "/api/households/mealplans/today"): httpx.Response(200, json=[])}

    def handler(request):
        out = routes[(request.method, request.url.path)]
        if isinstance(out, Exception):
            raise out
        return out(request) if callable(out) else out

    monkeypatch.setattr(mealie, "client", httpx.Client(base_url="http://mealie", transport=httpx.MockTransport(handler)))
    return routes


CHAT = ("POST", "/api/v1/chat/completions")


def reply(content="Hi", annotations=None, finish="stop"):
    msg = {"role": "assistant", "content": content} | ({"annotations": annotations} if annotations else {})
    return httpx.Response(200, json={"choices": [{"finish_reason": finish, "message": msg}]})


def cite(url, title=None):
    return {"type": "url_citation", "url_citation": {"url": url} | ({"title": title} if title else {})}


def err(status, **meta):
    return httpx.Response(status, json={"error": {"code": status, "message": "x", "metadata": meta}})


@pytest.fixture
def mock_ai(monkeypatch):
    """Dict of (method, path) -> httpx.Response, an exception to raise, or callable(request) -> Response."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    routes = {
        ("GET", "/api/v1/key"): httpx.Response(200, json={"data": {}}),
        ("GET", "/api/v1/models"): httpx.Response(200, json={"data": [
            {"id": "openai/gpt-5-nano", "architecture": {"input_modalities": ["text", "image"]}, "supported_parameters": ["tools"]},
            {"id": "text/only", "architecture": {"input_modalities": ["text"]}, "supported_parameters": []},
        ]}),
    }

    def handler(request):
        out = routes[(request.method, request.url.path)]
        if isinstance(out, Exception):
            raise out
        return out(request) if callable(out) else out

    monkeypatch.setattr(ai, "client", httpx.Client(base_url="https://openrouter.ai/api/v1", transport=httpx.MockTransport(handler)))
    return routes


@pytest.fixture
def login_as(mock_mealie):
    def make(user_id: str) -> TestClient:
        mock_mealie[("POST", "/api/auth/token")] = httpx.Response(200, json={"access_token": f"tok-{user_id}"})
        mock_mealie[("GET", "/api/users/self")] = httpx.Response(
            200, json={"id": user_id, "fullName": f"User {user_id}", "admin": False}
        )
        c = TestClient(app)
        r = c.post("/login", data={"username": user_id, "password": "pw"}, follow_redirects=False)
        assert r.status_code == 303 and "sid" in c.cookies
        return c

    return make


@pytest.fixture
def client(login_as):
    return login_as("u1")
