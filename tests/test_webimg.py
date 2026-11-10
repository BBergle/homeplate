import io

import httpx
import pytest
from PIL import Image

from app import webimg

PUBLIC, PRIVATE = ["93.184.216.34"], ["10.0.0.5"]


def png(size=(1200, 800)):
    b = io.BytesIO()
    Image.new("RGB", size, "red").save(b, "PNG")
    return b.getvalue()


@pytest.mark.parametrize("url,addrs,ok", [
    ("https://site.example/a?b=1", PUBLIC, "https://site.example/a?b=1"),
    ("http://site.example/a", PUBLIC, "https://site.example/a"),
    ("https://site.example/a", PRIVATE, None), ("https://site.example/a", PUBLIC + PRIVATE, None),
    ("https://site.example/a", ["127.0.0.1"], None), ("https://site.example/a", ["169.254.169.254"], None),
    ("https://site.example/a", ["::ffff:127.0.0.1"], None), ("https://site.example/a", ["::ffff:10.0.0.5"], None),
    ("https://site.example/a", ["64:ff9b::7f00:1"], None), ("https://site.example/a", ["64:ff9b::a00:5"], None),
    ("https://site.example/a", ["::127.0.0.1"], None), ("https://site.example/a", ["fec0::1"], None),
    ("https://site.example/a", ["224.0.0.1"], None), ("https://site.example/a", ["ff02::1"], None),
    ("https://site.example/a", ["0.0.0.0"], None), ("https://site.example/a", ["::"], None),
    ("https://site.example/a", ["100.64.0.1"], None), ("https://site.example/a", ["fe80::1%en0"], None),
    ("https://site.example/a", ["2606:4700::1111"], "https://site.example/a"),
    ("https://site.example/a", ["::1"], None), ("https://site.example/a", ["fd00::1"], None), ("https://site.example/a", [], None),
    ("https://192.168.1.1/a", PUBLIC, None), ("https://93.184.216.34/a", PUBLIC, None), ("https://localhost/a", ["127.0.0.1"], None),
    ("https://user:pw@site.example/a", PUBLIC, None), ("https://site.example:8443/a", PUBLIC, None),
    ("ftp://site.example/a", PUBLIC, None), ("javascript:alert(1)", PUBLIC, None), ("https://site.example/" + "a" * 2000, PUBLIC, None),
])
def test_public_https(monkeypatch, url, addrs, ok):
    monkeypatch.setattr(webimg, "resolve", lambda host: addrs)
    assert webimg.public_https(url) == ok


@pytest.fixture
def net(monkeypatch):
    """hosts table + handler hook; returns a list of (ip, host, sni) seen."""
    hosts = {"site.example": PUBLIC, "cdn.example": ["93.184.216.35"], "evil.example": PRIVATE}
    seen, state = [], {"handler": None, "clients": 0, "kw": [], "accept": []}

    def resolve(host):
        if host not in hosts:
            raise OSError("no such host")
        return hosts[host]

    def handler(request):
        state["accept"].append(request.headers["accept-encoding"])
        seen.append((request.url.host, request.headers["host"], request.extensions["sni_hostname"]))
        return state["handler"](request)

    real_client = httpx.Client

    def client(**kw):
        state["clients"] += 1
        state["kw"].append(kw)
        return real_client(**kw)

    monkeypatch.setattr(webimg, "resolve", resolve)
    monkeypatch.setattr(webimg, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(webimg.httpx, "Client", client)
    return seen, state


def test_thumbnail_fetches_checked_address_and_reencodes(net):
    seen, state = net
    state["handler"] = lambda r: httpx.Response(200, content=png())
    out = webimg.thumbnail("https://site.example/a.png?x=1")
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and max(img.size) == 640
    assert seen == [("93.184.216.34", "site.example", "site.example")]


def test_thumbnail_follows_public_redirect_and_refuses_private_one(net):
    seen, state = net

    def ok(r):
        if r.headers["host"] == "site.example":
            return httpx.Response(302, headers={"Location": "https://cdn.example/b.png"})
        return httpx.Response(200, content=png())
    state["handler"] = ok
    assert webimg.thumbnail("https://site.example/a") is not None
    assert seen[-1] == ("93.184.216.35", "cdn.example", "cdn.example")

    seen.clear()
    state["handler"] = lambda r: httpx.Response(302, headers={"Location": "https://evil.example/x"})
    assert webimg.thumbnail("https://site.example/a") is None
    assert len(seen) == 1  # the private host was never contacted

    state["handler"] = lambda r: httpx.Response(302, headers={"Location": "/again"})
    assert webimg.thumbnail("https://site.example/a") is None  # too many redirects


def test_thumbnail_refuses_bad_content(net):
    seen, state = net
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>'

    def raise_timeout(r):
        raise httpx.ReadTimeout("slow")

    for h in (
        lambda r: httpx.Response(200, content=svg),
        lambda r: httpx.Response(200, content=b"<html>hi</html>"),
        lambda r: httpx.Response(404, content=png()),
        raise_timeout,
    ):
        state["handler"] = h
        assert webimg.thumbnail("https://site.example/a") is None

    read = []

    def chunks():
        for _ in range(12):
            read.append(1)
            yield b"x" * (1024 * 1024)
    state["handler"] = lambda r: httpx.Response(200, content=chunks())
    assert webimg.thumbnail("https://site.example/a") is None
    assert len(read) <= 6  # stopped reading past the 5 MB limit


def test_thumbnail_uses_a_new_client_each_time(net):
    seen, state = net
    state["handler"] = lambda r: httpx.Response(200, content=png((10, 10)))
    webimg.thumbnail("https://site.example/a")
    webimg.thumbnail("https://site.example/a")
    assert state["clients"] == 2
    assert all(k["trust_env"] is False for k in state["kw"])
    assert state["accept"] == ["identity", "identity"]


def test_thumbnail_connects_to_the_address_that_was_checked(net, monkeypatch):
    seen, state = net
    answers = iter([PUBLIC, PRIVATE, PRIVATE, PRIVATE])  # DNS rebinding: public first, private after
    monkeypatch.setattr(webimg, "resolve", lambda host: next(answers))
    state["handler"] = lambda r: httpx.Response(200, content=png((10, 10)))
    assert webimg.thumbnail("https://site.example/a") is not None
    assert [s[0] for s in seen] == ["93.184.216.34"]


def test_thumbnail_gives_up_after_the_deadline(net, monkeypatch):
    seen, state = net
    state["handler"] = lambda r: httpx.Response(200, content=png((10, 10)))
    ticks = iter(range(0, 1000, 10))  # each clock read is 10 s later
    monkeypatch.setattr(webimg, "time", type("T", (), {"monotonic": staticmethod(lambda: next(ticks))}))
    assert webimg.thumbnail("https://site.example/a") is None
