"""Chart specifications built deterministically from verified, traceable data.

No chart is ever generated from model-invented numbers: data charts use only datapoints
whose quotes were verified verbatim in a retrieved source; process charts (source types,
publication years, evidence coverage) are computed from stored records. Every point carries
its evidence IDs and source numbers so the UI can open the evidence behind it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.db.mongo import new_id
from app.research.evidence import parse_date


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%$€£ ]+", "", s.lower()).strip()


def _period_key(period: str | None) -> tuple[int, str] | None:
    if not period:
        return None
    d = parse_date(period)
    if d:
        return (d.year * 10000 + d.month * 100 + d.day, period)
    m = re.search(r"(19|20)\d{2}", period)
    if m:
        return (int(m.group(0)) * 10000, m.group(0))
    q = re.search(r"Q([1-4])\s*(\d{4})|(\d{4})\s*Q([1-4])", period, re.IGNORECASE)
    if q:
        year = int(q.group(2) or q.group(3))
        quarter = int(q.group(1) or q.group(4))
        return (year * 10000 + quarter * 300, f"{year} Q{quarter}")
    return None


def data_charts(datapoints: list[dict[str, Any]], max_charts: int = 4) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for dp in datapoints:
        groups[(_norm(dp["metric"]), _norm(dp["unit"]))].append(dp)
    charts: list[dict[str, Any]] = []
    for (_metric, _unit), pts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(pts) < 2:
            continue
        metric_label = pts[0]["metric"]
        unit_label = pts[0]["unit"]
        entities = sorted({p["entity"] for p in pts})
        periods = [(_period_key(p.get("period")), p) for p in pts]
        dated = [(k, p) for k, p in periods if k]
        notes: list[str] = []
        if len({k[1] for k, _ in dated}) >= 3 and len(entities) <= 6 and len(dated) >= 3:
            series = []
            for ent in entities:
                ent_pts = sorted(((k, p) for k, p in dated if p["entity"] == ent), key=lambda kp: kp[0][0])
                if not ent_pts:
                    continue
                series.append({"name": ent, "points": [
                    {"x": k[1], "y": p["value"], "evidence_ids": [p["evidence_id"]], "sources": [p["source_number"]],
                     "estimated": p.get("estimated", False)} for k, p in ent_pts]})
            undated = len(pts) - len(dated)
            if undated:
                notes.append(f"{undated} value(s) without a stated period were excluded.")
            charts.append({"id": new_id("ch"), "type": "line", "title": f"{metric_label} over time",
                           "x_label": "Period", "y_label": unit_label, "unit": unit_label, "series": series,
                           "notes": notes, "kind": "data"})
        elif len(entities) >= 2:
            # One bar per entity; if several values exist for an entity, keep the most recent and note it.
            by_ent: dict[str, list[tuple[Any, dict[str, Any]]]] = defaultdict(list)
            for k, p in periods:
                by_ent[p["entity"]].append((k, p))
            points = []
            conflicting = []
            for ent in entities:
                cands = sorted(by_ent[ent], key=lambda kp: (kp[0][0] if kp[0] else -1), reverse=True)
                k, p = cands[0]
                same_period = [c for c in cands if c[0] == k]
                if len({c[1]["value"] for c in same_period}) > 1:
                    conflicting.append(ent)
                label = ent + (f" ({k[1]})" if k else "")
                points.append({"x": label, "y": p["value"], "evidence_ids": [c[1]["evidence_id"] for c in same_period],
                               "sources": sorted({c[1]["source_number"] for c in same_period}), "estimated": False})
                if len(cands) > 1:
                    notes.append(f"{ent}: {len(cands)} values found; showing the most recent.")
            if conflicting:
                notes.append("Sources report different values for: " + ", ".join(conflicting) + " (first shown; open the evidence for all).")
            charts.append({"id": new_id("ch"), "type": "bar", "title": f"{metric_label} by entity",
                           "x_label": "Entity", "y_label": unit_label, "unit": unit_label,
                           "series": [{"name": metric_label, "points": points}], "notes": notes, "kind": "data"})
        if len(charts) >= max_charts:
            break
    return charts


def process_charts(sources: list[dict[str, Any]], evidence: list[dict[str, Any]], subquestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    extracted = [s for s in sources if s.get("status") == "extracted"]
    if extracted:
        by_type: dict[str, list[int]] = defaultdict(list)
        for s in extracted:
            by_type[s.get("source_type") or "unknown"].append(s["number"])
        charts.append({"id": new_id("ch"), "type": "donut", "title": "Sources by type", "unit": "sources",
                       "series": [{"name": "Sources", "points": [
                           {"x": t, "y": len(nums), "sources": nums, "evidence_ids": []} for t, nums in sorted(by_type.items())]}],
                       "notes": ["Primary = originator's own data or statement; secondary = reporting/analysis; commentary = opinion or unattributed."],
                       "kind": "process"})
        by_year: dict[str, list[int]] = defaultdict(list)
        undated = 0
        for s in extracted:
            d = parse_date(s.get("published_at"))
            if d:
                by_year[str(d.year)].append(s["number"])
            else:
                undated += 1
        if by_year:
            charts.append({"id": new_id("ch"), "type": "bar", "title": "Publication year of sources", "x_label": "Year",
                           "y_label": "Sources", "unit": "sources",
                           "series": [{"name": "Sources", "points": [
                               {"x": y, "y": len(n), "sources": n, "evidence_ids": []} for y, n in sorted(by_year.items())]}],
                           "notes": [f"{undated} source(s) had no detectable publication date."] if undated else [],
                           "kind": "process"})
    if evidence and subquestions:
        pts = []
        for sq in subquestions:
            ev = [e for e in evidence if e["subquestion_id"] == sq["id"]]
            pts.append({"x": sq["id"], "label": sq["question"][:80], "y": len(ev),
                        "y2": len({e["domain"] for e in ev}), "evidence_ids": [e["id"] for e in ev][:40],
                        "sources": sorted({e["source_number"] for e in ev})})
        charts.append({"id": new_id("ch"), "type": "bar", "title": "Verified evidence per sub-question",
                       "x_label": "Sub-question", "y_label": "Verified claims", "unit": "claims",
                       "series": [{"name": "Verified claims", "points": pts}],
                       "notes": ["Counts only claims whose quotes were verified verbatim in the source."], "kind": "process"})
    return charts
