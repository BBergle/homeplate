"""Safe server-side fetch of card photos. Addresses come from an AI model and web pages: untrusted."""
import io
import ipaddress
import socket
import warnings
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from PIL import Image

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
Image.MAX_IMAGE_PIXELS = 50_000_000
_transport = None  # tests only


def resolve(host: str) -> list[str]:
    return [i[4][0] for i in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]


def public_https(url: str) -> str | None:
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
        if not addrs or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs):
            return None
        return urlunsplit(("https", host, u.path, u.query, ""))
    except Exception:
        return None


def thumbnail(url: str) -> bytes | None:
    try:
        cur = url
        for _ in range(MAX_REDIRECTS + 1):
            cur = public_https(cur)
            if not cur:
                return None
            u = urlsplit(cur)
            addrs = resolve(u.hostname)
            v4 = [a for a in addrs if ":" not in a]
            ip = v4[0] if v4 else f"[{addrs[0]}]"
            target = urlunsplit(("https", ip, u.path or "/", u.query, ""))
            # a new client per fetch: a pooled connection would skip certificate checks for the next name
            with httpx.Client(transport=_transport, follow_redirects=False, timeout=10) as c:
                with c.stream("GET", target, headers={"Host": u.hostname}, extensions={"sni_hostname": u.hostname}) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        cur = urljoin(cur, r.headers["location"])
                        continue
                    if r.status_code != 200:
                        return None
                    data = b""
                    for chunk in r.iter_bytes():
                        data += chunk
                        if len(data) > MAX_BYTES:
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
