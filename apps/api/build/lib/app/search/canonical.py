"""URL canonicalisation and domain helpers for deduplication and filtering."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = re.compile(
    r"^(utm_.*|gclid|fbclid|dclid|msclkid|mc_cid|mc_eid|igshid|ref|ref_src|ref_url|source|cmpid|_hsenc|_hsmi|"
    r"oly_anon_id|oly_enc_id|vero_id|yclid|spm|share|s_cid|cid)$",
    re.IGNORECASE,
)


def canonicalize_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.startswith(("m.", "mobile.")) and host.count(".") >= 2:
        host = host.split(".", 1)[1]
    port = parts.port
    netloc = host if not port or (scheme, port) in (("http", 80), ("https", 443)) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    for suffix in ("/index.html", "/index.htm", "/index.php"):
        if path.endswith(suffix):
            path = path[: -len(suffix)] or "/"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
                             if not _TRACKING_PARAMS.match(k)))
    # Treat http and https as the same document for dedup purposes.
    return urlunsplit(("https" if scheme in ("http", "https") else scheme, netloc, path, query, ""))


def domain_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def registrable_domain(url_or_host: str) -> str:
    """Approximate eTLD+1 (good enough for diversity counting; not a security boundary)."""
    host = domain_of(url_or_host) if "/" in url_or_host else url_or_host.lower()
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    two_level = {"co.uk", "ac.uk", "gov.uk", "org.uk", "com.au", "edu.au", "gov.au", "co.jp", "ac.jp", "co.nz",
                 "com.br", "gov.br", "co.in", "ac.in", "gov.in", "com.cn", "edu.cn", "gov.cn", "co.za", "ac.za"}
    if ".".join(parts[-2:]) in two_level:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def domain_matches(url: str, patterns: list[str]) -> bool:
    d = domain_of(url)
    for p in patterns:
        p = p.lower().strip().lstrip("*.").removeprefix("www.")
        if p and (d == p or d.endswith("." + p)):
            return True
    return False
