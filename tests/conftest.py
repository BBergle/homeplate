import httpx
import pytest
from fastapi.testclient import TestClient

from app import mealie
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
        return out

    monkeypatch.setattr(mealie, "client", httpx.Client(base_url="http://mealie", transport=httpx.MockTransport(handler)))
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
