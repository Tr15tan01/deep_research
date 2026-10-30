"""Deterministic evidence checks: verbatim-quote verification, source-type heuristics,
evidence-strength labels with transparent criteria, and freshness statistics."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from statistics import median
from typing import Any

from app.search.canonical import registrable_domain

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[\"'“”‘’`´«»„‚‘’“”*_#>|\[\]()]")


def normalize_for_match(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = t.replace("–", "-").replace("—", "-").replace("−", "-").replace(" ", " ")
    t = _PUNCT.sub("", t)
    return _WS.sub(" ", t).strip()


@dataclass
class QuoteMatch:
    verified: bool
    method: str  # exact | normalized | fuzzy | none
    score: float
    location: int | None = None
    matched_text: str | None = None


def verify_quote(quote: str, source_text: str, fuzzy_threshold: float = 0.9) -> QuoteMatch:
    """Check that a model-provided quote really appears in the retrieved source text."""
    q = quote.strip().strip('"').strip()
    if len(q) < 12:
        return QuoteMatch(False, "none", 0.0)
    idx = source_text.find(q)
    if idx >= 0:
        return QuoteMatch(True, "exact", 1.0, idx, source_text[idx : idx + len(q)])
    nq = normalize_for_match(q)
    ns = normalize_for_match(source_text)
    pos = ns.find(nq)
    if pos >= 0:
        return QuoteMatch(True, "normalized", 1.0, pos, None)
    # Fuzzy: compare against windows anchored on the rarest word of the quote.
    words = [w for w in nq.split(" ") if len(w) >= 5]
    if not words:
        return QuoteMatch(False, "none", 0.0)
    counts = Counter(ns.split(" "))
    anchors = sorted(set(words), key=lambda w: counts.get(w, 0))[:3]
    best = 0.0
    best_pos = None
    L = len(nq)
    for anchor in anchors:
        start = 0
        seen = 0
        while seen < 40:
            p = ns.find(anchor, start)
            if p < 0:
                break
            seen += 1
            off = nq.find(anchor)
            lo = max(0, p - off - 20)
            window = ns[lo : lo + L + 40]
            sm = SequenceMatcher(None, nq, window, autojunk=False)
            # Ratio relative to the quote length (how much of the quote is covered).
            matched = sum(b.size for b in sm.get_matching_blocks())
            score = matched / max(L, 1)
            if score > best:
                best, best_pos = score, lo
            start = p + 1
    if best >= fuzzy_threshold:
        return QuoteMatch(True, "fuzzy", round(best, 3), best_pos)
    return QuoteMatch(False, "none", round(best, 3))


# --- Source-type heuristics (used to cross-check the model's classification) ---------------

_PRIMARY_HINTS = (".gov", ".gov.", ".mil", "europa.eu", "who.int", "un.org", "oecd.org", "worldbank.org", "imf.org",
                  "sec.gov", "census.gov", "data.", "docs.", "developer.", "github.com", "arxiv.org", "doi.org",
                  "nature.com", "sciencedirect.com", "springer.com", "nih.gov", "acm.org", "ieee.org", "ssrn.com")
_COMMENTARY_HINTS = ("medium.com", "substack.com", "reddit.com", "quora.com", "blogspot.", "wordpress.com",
                     "linkedin.com/pulse", "x.com", "twitter.com", "facebook.com", "youtube.com", "tiktok.com")


def heuristic_source_type(url: str) -> str | None:
    u = url.lower()
    if any(h in u for h in _COMMENTARY_HINTS):
        return "commentary"
    if any(h in u for h in _PRIMARY_HINTS):
        return "primary"
    return None


# --- Dates ---------------------------------------------------------------------------------

_DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "ymd"),
    (re.compile(r"(\d{4})/(\d{2})/(\d{2})"), "ymd"),
    (re.compile(r"^(\d{4})-(\d{2})$"), "ym"),
    (re.compile(r"^(\d{4})$"), "y"),
]


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    v = str(value).strip()
    for pat, kind in _DATE_PATTERNS:
        m = pat.search(v)
        if m:
            try:
                if kind == "ymd":
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif kind == "ym":
                    d = date(int(m.group(1)), int(m.group(2)), 1)
                else:
                    d = date(int(m.group(1)), 1, 1)
            except ValueError:
                continue
            if 1900 <= d.year <= datetime.now(UTC).year + 1:
                return d
    m = re.search(r"D:(\d{4})(\d{2})(\d{2})", v)  # PDF dates
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(v[:40], fmt).date()
        except ValueError:
            continue
    return None


def freshness(sources: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    dates = [d for d in (parse_date(s.get("published_at")) for s in sources) if d]
    if not dates:
        return {"dated": 0, "undated": len(sources), "newest": None, "oldest": None, "median_age_days": None,
                "label": "unknown"}
    ages = [(today - d).days for d in dates]
    med = median(ages)
    label = "fresh" if med <= 365 else ("mixed" if med <= 3 * 365 else "dated")
    return {"dated": len(dates), "undated": len(sources) - len(dates), "newest": max(dates).isoformat(),
            "oldest": min(dates).isoformat(), "median_age_days": int(med), "label": label}


# --- Evidence strength -----------------------------------------------------------------------

STRENGTH_CRITERIA = {
    "strong": "At least two independent domains, including a primary source, or three or more independent domains; no contradicting evidence.",
    "moderate": "Two independent domains, or a single primary source; no contradicting evidence.",
    "limited": "A single secondary or commentary source.",
    "contested": "Cited evidence includes sources that contradict each other.",
    "unsupported": "No verified evidence is attached.",
}


def evidence_strength(cited: list[dict[str, Any]], contradicted: bool = False) -> dict[str, Any]:
    """Transparent rule-based label — explicitly *not* a calibrated probability."""
    if not cited:
        return {"label": "unsupported", "basis": STRENGTH_CRITERIA["unsupported"], "independent_domains": 0,
                "primary_sources": 0}
    domains = {registrable_domain(e.get("domain") or "") for e in cited if e.get("domain")}
    primaries = {e.get("source_id") for e in cited if e.get("source_type") == "primary"}
    stances = {e.get("stance") for e in cited}
    if contradicted or ("contradicts" in stances and "supports" in stances):
        label = "contested"
    elif (len(domains) >= 2 and primaries) or len(domains) >= 3:
        label = "strong"
    elif len(domains) >= 2 or primaries:
        label = "moderate"
    else:
        label = "limited"
    return {"label": label, "basis": STRENGTH_CRITERIA[label], "independent_domains": len(domains),
            "primary_sources": len(primaries)}
