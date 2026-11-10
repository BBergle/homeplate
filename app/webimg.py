"""Safe server-side fetch of card photos. Addresses come from an AI model and web pages: untrusted."""
import io
import ipaddress
import socket
import time
import warnings
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from PIL import Image

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
DEADLINE = 15  # seconds for the whole thumbnail call, all hops
_V6_PUBLIC = ipaddress.ip_network("2000::/3")  # excludes mapped, NAT64, site-local, link-local, ULA
Image.MAX_IMAGE_PIXELS = 50_000_000
_transport = None  # tests only


def resolve(host: str) -> list[str]:
    return [i[4][0] for i in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]


def _is_public(a: str) -> bool:
    ip = ipaddress.ip_address(a.split("%")[0])
    return ip.is_global and not ip.is_multicast and (ip.version == 4 or ip in _V6_PUBLIC)


def public_https(url: str) -> str | None:
    c = _check(url)
    return c[0] if c else None


def _check(url: str) -> tuple[str, list[str]] | None:
    """(clean url, the addresses that were checked): resolve once, connect to one of these."""
    try:
        if len(url) > 2000:
            return None
        u = urlsplit(url)
        host = u.hostname
        if u.scheme not in ("http", "https") or not host or u.username or u.password or u.port not in (None, 443):
            return None
        try:
            ipaddress.ip_address(host)
            return None  # bare IP
        except ValueError:
            pass
        addrs = resolve(host)
        if not addrs or not all(_is_public(a) for a in addrs):
            return None
        return urlunsplit(("https", host, u.path, u.query, "")), addrs
    except Exception:
        return None


def thumbnail(url: str) -> bytes | None:
    try:
        cur = url
        deadline = time.monotonic() + DEADLINE
        for _ in range(MAX_REDIRECTS + 1):
            checked = _check(cur)
            if not checked or time.monotonic() > deadline:
                return None
            cur, addrs = checked
            u = urlsplit(cur)
            v4 = [a for a in addrs if ":" not in a]
            ip = v4[0] if v4 else f"[{addrs[0]}]"
            target = urlunsplit(("https", ip, u.path or "/", u.query, ""))
            # a new client per fetch: a pooled connection would skip certificate checks for the next name
            with httpx.Client(transport=_transport, follow_redirects=False, timeout=10, trust_env=False) as c:
                with c.stream("GET", target, headers={"Host": u.hostname, "Accept-Encoding": "identity"}, extensions={"sni_hostname": u.hostname}) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        cur = urljoin(cur, r.headers["location"])
                        continue
                    if r.status_code != 200:
                        return None
                    data = b""
                    for chunk in r.iter_bytes():
                        data += chunk
                        if len(data) > MAX_BYTES or time.monotonic() > deadline:
                            return None
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                img = Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP", "GIF"]).convert("RGB")
            img.thumbnail((640, 640))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=80)
            return out.getvalue()
        return None  # too many redirects
    except Exception:
        return None
