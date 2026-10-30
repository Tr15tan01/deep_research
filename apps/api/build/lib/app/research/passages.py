"""Select the most relevant passages of a long document so it fits a model's context."""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]{1,}")
_STOP = set("""a an the and or of to in on for with by from at as is are was were be been being this that these those it its
into than then there their they them we our you your he she his her not no but if so such can could may might will would
should do does did done has have had what which who whom whose when where why how all any both each few more most other
some own same only very also just about over under between after before during through""".split())


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def select_passages(text: str, queries: list[str], max_chars: int) -> str:
    """BM25-style paragraph ranking; returns selected paragraphs in original order."""
    if len(text) <= max_chars:
        return text
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    # Merge very small paragraphs and split huge ones so windows are comparable.
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(p) > 2500:
            for i in range(0, len(p), 2000):
                chunks.append(p[i : i + 2200])
            continue
        if len(buf) + len(p) < 900:
            buf = (buf + "\n" + p).strip()
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    if not chunks:
        return text[:max_chars]
    q_terms = Counter(t for q in queries for t in _tokens(q))
    docs = [Counter(_tokens(c)) for c in chunks]
    N = len(docs)
    avgdl = sum(sum(d.values()) for d in docs) / max(N, 1)
    df = Counter(t for d in docs for t in d)
    k1, b = 1.4, 0.75
    scores = []
    for i, d in enumerate(docs):
        dl = sum(d.values()) or 1
        s = 0.0
        for t, qf in q_terms.items():
            if t not in d:
                continue
            idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
            tf = d[t]
            s += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl)) * (1 + 0.2 * (qf - 1))
        # Mild preference for the document's beginning (abstracts, summaries, ledes).
        s += 0.3 if i < 2 else 0.0
        scores.append((s, i))
    chosen: set[int] = set()
    total = 0
    for _s, i in sorted(scores, reverse=True):
        if total + len(chunks[i]) > max_chars:
            continue
        chosen.add(i)
        total += len(chunks[i])
        if total >= max_chars * 0.95:
            break
    out = []
    prev = -2
    for i in sorted(chosen):
        if i != prev + 1 and out:
            out.append("[…]")
        out.append(chunks[i])
        prev = i
    return "\n\n".join(out)


def number_in_text(value: float, text: str) -> bool:
    """True if the numeric value plausibly appears in the quote (handles 1,200 / 1.2k / 12.5% / 3 billion)."""
    t = text.lower().replace(" ", " ")
    candidates = set()
    if float(value).is_integer():
        iv = int(value)
        candidates |= {str(iv), f"{iv:,}", f"{iv:,}".replace(",", " "), f"{iv:,}".replace(",", ".")}
    candidates |= {f"{value:g}", f"{value:.1f}", f"{value:.2f}", f"{value:,.2f}"}
    for scale, words in ((1e3, ("k", "thousand")), (1e6, ("m", "million", "mn")), (1e9, ("b", "bn", "billion")),
                         (1e12, ("t", "tn", "trillion"))):
        if abs(value) >= scale:
            v = value / scale
            for w in words:
                candidates |= {f"{v:g} {w}", f"{v:g}{w}", f"{v:.1f} {w}", f"{v:.1f}{w}"}
    numbers_in_text = re.findall(r"\d[\d,\. ]*\d|\d", t)
    for c in candidates:
        if c and c in t:
            return True
    # Fallback: compare parsed numbers.
    for n in numbers_in_text:
        try:
            if abs(float(n.replace(",", "").replace(" ", "")) - value) < 1e-9:
                return True
        except ValueError:
            continue
    return False
