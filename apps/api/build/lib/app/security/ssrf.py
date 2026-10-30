"""SSRF-safe outbound HTTP fetching.

Defences:
  * Scheme allow-list (http/https) and port allow-list.
  * Hostname resolution with *every* resolved address validated against private,
    loopback, link-local, multicast, reserved, CGNAT, unique-local and metadata ranges.
  * Connection pinned to the validated IP (DNS-rebinding safe), with TLS SNI/certificate
    verification still performed against the original hostname.
  * Redirects followed manually with full re-validation of each hop (bounded).
  * Response size cap enforced while streaming, plus connect/read/total timeouts.
  * Credentials in URLs (user:pass@host) rejected.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.config import get_settings

BLOCKED_HOSTNAMES = {
    "localhost", "localhost.localdomain", "metadata.google.internal", "metadata", "instance-data",
    "kubernetes.default", "kubernetes.default.svc",
}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa", ".corp", ".svc",
                    ".cluster.local", ".localdomain")
_EXTRA_BLOCKED_NETS = [
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("169.254.169.254/32"),  # cloud metadata (also link-local)
    ipaddress.ip_network("fd00:ec2::254/128"),  # AWS IMDS IPv6
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 — could map to internal IPv4
]


class SSRFBlocked(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class FetchError(Exception):
    def __init__(self, reason: str, status: int | None = None) -> None:
        self.reason = reason
        self.status = status
        super().__init__(reason)


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status: int
    content_type: str
    body: bytes
    truncated: bool
    elapsed_ms: int


def ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip_is_public(ip.ipv4_mapped)
    if isinstance(ip, ipaddress.IPv6Address) and ip.sixtofour is not None:
        return ip_is_public(ip.sixtofour)
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
            or ip.is_unspecified or not ip.is_global):
        return False
    return not any(ip in net for net in _EXTRA_BLOCKED_NETS if net.version == ip.version)


def validate_url_shape(url: str) -> tuple[str, str, int]:
    """Static checks. Returns (scheme, hostname, port)."""
    if len(url) > 2048:
        raise SSRFBlocked("url too long")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise SSRFBlocked(f"scheme not allowed: {scheme or 'none'}")
    if parts.username or parts.password:
        raise SSRFBlocked("credentials in URL are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise SSRFBlocked("missing host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as e:
        raise SSRFBlocked("invalid port") from e
    if port not in get_settings().fetch_allowed_ports:
        raise SSRFBlocked(f"port not allowed: {port}")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise SSRFBlocked("internal hostname")
    # Literal IPs, including obfuscated decimal/octal forms, are parsed by inet_aton semantics.
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
        if host.replace(".", "").isdigit() or host.startswith("0x"):
            try:
                ip = ipaddress.ip_address(socket.inet_aton(host))
            except OSError:
                raise SSRFBlocked("malformed numeric host") from None
    if ip is not None and not ip_is_public(ip):
        raise SSRFBlocked("non-public address")
    return scheme, host, port


async def resolve_public(host: str, port: int) -> list[str]:
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        if not ip_is_public(ip):
            raise SSRFBlocked("non-public address")
        return [str(ip)]
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=5)
    except (TimeoutError, OSError) as e:
        raise FetchError("dns resolution failed") from e
    addrs = sorted({info[4][0] for info in infos})
    if not addrs:
        raise FetchError("dns resolution returned no addresses")
    for a in addrs:
        if not ip_is_public(ipaddress.ip_address(a.split("%")[0])):
            # If *any* record is internal, refuse (prevents mixed-record rebinding tricks).
            raise SSRFBlocked("hostname resolves to a non-public address")
    return addrs


_ALLOWED_CONTENT = ("text/html", "application/xhtml+xml", "text/plain", "application/pdf", "text/markdown",
                    "application/json", "application/xml", "text/xml")


async def safe_fetch(url: str, *, max_bytes: int | None = None, timeout: float | None = None, max_redirects: int = 5,
                     accept: str = "text/html,application/xhtml+xml,application/pdf;q=0.9,text/plain;q=0.8,*/*;q=0.1",
                     transport: httpx.AsyncBaseTransport | None = None) -> FetchResult:
    s = get_settings()
    max_bytes = max_bytes or s.FETCH_MAX_BYTES
    timeout = timeout or s.FETCH_TIMEOUT_SECONDS
    started = time.monotonic()
    current = url
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(timeout, 8.0)), follow_redirects=False,
                                 transport=transport, trust_env=False) as client:
        for _hop in range(max_redirects + 1):
            scheme, host, port = validate_url_shape(current)
            addrs = await resolve_public(host, port)
            ip = addrs[0]
            parts = urlsplit(current)
            ip_host = f"[{ip}]" if ":" in ip else ip
            netloc = ip_host if parts.port is None else f"{ip_host}:{port}"
            pinned = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
            headers = {"Host": parts.netloc.split("@")[-1], "Accept": accept,
                       "User-Agent": f"{s.APP_NAME}-ResearchBot/1.0 (+{s.FRONTEND_URL})",
                       "Accept-Language": "en;q=0.9,*;q=0.5"}
            ext = {"sni_hostname": host} if scheme == "https" else {}
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise FetchError("timeout")
            try:
                req = client.build_request("GET", pinned, headers=headers, extensions=ext)
                resp = await asyncio.wait_for(client.send(req, stream=True), timeout=remaining)
            except (TimeoutError, httpx.TimeoutException) as e:
                raise FetchError("timeout") from e
            except httpx.HTTPError as e:
                raise FetchError(f"connection failed: {type(e).__name__}") from e
            try:
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location")
                    if not loc:
                        raise FetchError("redirect without location", resp.status_code)
                    current = urljoin(current, loc)
                    continue
                if resp.status_code >= 400:
                    raise FetchError(f"http {resp.status_code}", resp.status_code)
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and not ctype.startswith(_ALLOWED_CONTENT):
                    raise FetchError(f"unsupported content type: {ctype}")
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes * 4:
                    raise FetchError("response too large")
                buf = bytearray()
                truncated = False
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        truncated = True
                        del buf[max_bytes:]
                        break
                    if time.monotonic() - started > timeout:
                        raise FetchError("timeout")
                return FetchResult(url=current, status=resp.status_code, content_type=ctype, body=bytes(buf),
                                   truncated=truncated, elapsed_ms=int((time.monotonic() - started) * 1000))
            finally:
                await resp.aclose()
    raise FetchError("too many redirects")
