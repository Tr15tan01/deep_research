"""Citation parsing and validation.

The model writes evidence markers ([E12]). We deterministically:
  * keep only markers that resolve to verified evidence stored for *this* job,
  * map them to stored source numbers ([3]),
  * record invalid markers and uncited sentences,
  * attach the evidence used by each sentence so the UI can show the exact passage.
"""

from __future__ import annotations

import re
from typing import Any

from app.db.mongo import new_id

_MARKER = re.compile(r"\[\s*(E\s*\d+(?:\s*[,;]\s*E?\s*\d+)*)\s*\]", re.IGNORECASE)
_SENT_SPLIT = re.compile(r"(?<=[.!?])(?:\s*(?:\[[^\]]*\])*)\s+(?=[A-Z0-9\"“(])")
_SOURCE_STYLE = re.compile(r"\[(\d{1,3})\]")  # models sometimes emit [3]; never trusted


def _split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    # Split while keeping markers attached to the preceding sentence.
    parts: list[str] = []
    last = 0
    for m in re.finditer(r"(?<=[.!?])((?:\s*\[[^\]]+\])*)\s+(?=[A-Z0-9\"“(])", text):
        end = m.end(1)
        parts.append(text[last:end].strip())
        last = m.end()
    parts.append(text[last:].strip())
    return [p for p in parts if p]


def _marker_ids(raw: str) -> list[str]:
    ids = []
    for tok in re.split(r"[,;]", raw):
        tok = tok.strip().upper().replace(" ", "")
        if not tok:
            continue
        if not tok.startswith("E"):
            tok = "E" + tok
        ids.append(tok)
    return ids


class CitationResolver:
    def __init__(self, evidence_by_id: dict[str, dict[str, Any]]) -> None:
        self.evidence = evidence_by_id
        self.stats = {"markers": 0, "valid": 0, "invalid": 0, "sentences": 0, "cited_sentences": 0,
                      "uncited_sentences": 0, "stray_numeric_markers": 0}
        self.invalid_ids: list[str] = []

    def paragraph(self, text: str, *, require_citations: bool = True) -> dict[str, Any]:
        segments = []
        for sent in _split_sentences(text):
            ids: list[str] = []
            for m in _MARKER.finditer(sent):
                ids.extend(_marker_ids(m.group(1)))
            clean = _MARKER.sub("", sent)
            stray = _SOURCE_STYLE.findall(clean)
            if stray:
                self.stats["stray_numeric_markers"] += len(stray)
                clean = _SOURCE_STYLE.sub("", clean)
            clean = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s{2,}", " ", clean)).strip()
            valid: list[str] = []
            for eid in ids:
                self.stats["markers"] += 1
                if eid in self.evidence:
                    if eid not in valid:
                        valid.append(eid)
                    self.stats["valid"] += 1
                else:
                    self.stats["invalid"] += 1
                    self.invalid_ids.append(eid)
            sources: list[int] = []
            for eid in valid:
                n = self.evidence[eid]["source_number"]
                if n not in sources:
                    sources.append(n)
            self.stats["sentences"] += 1
            if valid:
                self.stats["cited_sentences"] += 1
            elif require_citations:
                self.stats["uncited_sentences"] += 1
            segments.append({
                "text": clean,
                "evidence_ids": valid,
                "sources": sources,
                "dropped_markers": [e for e in ids if e not in self.evidence],
                "support": ("unverified" if valid else ("uncited" if require_citations else "n/a")),
                "support_note": "",
            })
        return {"id": new_id("p"), "segments": segments}

    def summary(self) -> dict[str, Any]:
        return {**self.stats, "invalid_ids": sorted(set(self.invalid_ids))[:50]}


def paragraph_plain(par: dict[str, Any], numbered: bool = True) -> str:
    out = []
    for seg in par.get("segments", []):
        cites = "".join(f"[{n}]" for n in seg.get("sources", [])) if numbered else ""
        text = seg["text"]
        if cites and text and text[-1] in ".!?":
            out.append(text[:-1] + " " + cites + text[-1])
        else:
            out.append((text + (" " + cites if cites else "")).strip())
    return " ".join(out)
