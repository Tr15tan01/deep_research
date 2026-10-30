"""Report exports: Markdown and CSV (synchronous), PDF and DOCX (background jobs)."""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Any

from bson import Binary

from app.core.security import utcnow
from app.db.mongo import Collections, col
from app.jobs import lifecycle
from app.research.citations import paragraph_plain
from app.research.context import JobContext, emit_event
from app.research.reports import bibliography, cited_numbers, render_markdown

EXPORT_TTL = timedelta(hours=24)
MIME = {"pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def charts_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["chart_id", "chart_title", "chart_type", "series", "x", "y", "unit", "source_numbers", "evidence_ids", "estimated"])
    for ch in report.get("charts") or []:
        for s in ch.get("series", []):
            for p in s.get("points", []):
                w.writerow([ch["id"], ch["title"], ch["type"], s.get("name"), p.get("x"), p.get("y"), ch.get("unit", ""),
                            " ".join(str(n) for n in p.get("sources", [])), " ".join(p.get("evidence_ids", [])),
                            "yes" if p.get("estimated") else "no"])
    for t in report.get("tables") or []:
        for row in t["rows"]:
            for col_name, cell in zip(t["columns"], row["cells"], strict=False):
                w.writerow([t["id"], t["title"], "matrix", col_name, row["attribute"], cell["value"], "",
                            " ".join(str(n) for n in cell.get("sources", [])), " ".join(cell.get("evidence_ids", [])), "no"])
    return buf.getvalue()


def render_pdf(report: dict[str, Any], sources: list[dict[str, Any]]) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=report["title"][:200], author="Deep Research")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
    h1, h2 = ss["Title"], ss["Heading2"]
    banner = ParagraphStyle("banner", parent=body, backColor=colors.HexColor("#FFF4D6"), borderPadding=6,
                            textColor=colors.HexColor("#6B4E00"))
    E: list[Any] = []

    def P(text: str, style: Any = body) -> None:
        E.append(Paragraph(escape(text), style))

    if report.get("is_demo"):
        P("DEMO MODE — synthetic data. This is not real research.", banner)
        E.append(Spacer(1, 6))
    if report.get("status") == "partial":
        P(f"Partial report — research did not complete ({report.get('partial_reason')}).", banner)
        E.append(Spacer(1, 6))
    P(report["title"], h1)
    P(f"Question: {report['question']}", small)
    P(f"Mode: {report.get('mode')} · Version {report.get('version')} · Generated {str(report.get('created_at'))[:19]} UTC", small)
    E.append(Spacer(1, 8))

    def section(title: str, pars: list[dict[str, Any]]) -> None:
        if not pars:
            return
        P(title, h2)
        for p in pars:
            P(paragraph_plain(p))
            E.append(Spacer(1, 4))

    section("Executive summary", report.get("executive_summary") or [])
    if report.get("key_findings"):
        P("Key findings", h2)
        for f in report["key_findings"]:
            s = (f.get("strength") or {}).get("label")
            P("• " + paragraph_plain(f) + (f" (evidence: {s})" if s else ""))
    for s in report.get("sections") or []:
        section(s["title"], s.get("paragraphs") or [])
    for t in report.get("tables") or []:
        P(t["title"], h2)
        data = [["Attribute", *t["columns"]]]
        for row in t["rows"]:
            data.append([row["attribute"], *[c["value"] + "".join(f"[{n}]" for n in c.get("sources", [])) for c in row["cells"]]])
        wrapped = [[Paragraph(escape(str(c)), small) for c in r] for r in data]
        tbl = Table(wrapped, repeatRows=1)
        tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
                                 ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        E.append(tbl)
    if report.get("charts"):
        P("Chart data", h2)
        P("Interactive charts are available in the online report. Underlying values (with source numbers):", small)
        for ch in report["charts"]:
            P(ch["title"] + (f" ({ch.get('unit')})" if ch.get("unit") else ""), ss["Heading4"])
            for sr in ch.get("series", []):
                pts = "; ".join(f"{p.get('x')}: {p.get('y')}" + (f" [{','.join(str(n) for n in p.get('sources', []))}]" if p.get("sources") else "")
                                for p in sr.get("points", [])[:30])
                P(f"{sr.get('name')}: {pts}", small)
    section("Conflicting evidence", report.get("conflicts") or [])
    if report.get("limitations"):
        P("Limitations", h2)
        for x in report["limitations"]:
            P("• " + x)
    if report.get("unknowns"):
        P("What is still unknown", h2)
        for u in report["unknowns"]:
            P(f"• {u['question']} — {u['why']}")
    section("Conclusions", report.get("conclusions") or [])
    if report.get("recommendations"):
        P("Recommendations", h2)
        for r in report["recommendations"]:
            P("• " + paragraph_plain(r))
    P("Sources", h2)
    for b in bibliography(sources, cited_numbers(report)):
        meta = ", ".join(x for x in [b.get("publisher") or b.get("domain"), b.get("author"), str(b.get("published_at") or "n.d.")[:10]] if x)
        P(f"[{b['number']}] {b['title']} — {meta}. {b['url']} (retrieved {str(b.get('retrieved_at') or '')[:10]})", small)
    doc.build(E)
    return buf.getvalue()


def render_docx(report: dict[str, Any], sources: list[dict[str, Any]]) -> bytes:
    import docx

    d = docx.Document()
    if report.get("is_demo"):
        d.add_paragraph("DEMO MODE — synthetic data. This is not real research.").runs[0].bold = True
    if report.get("status") == "partial":
        d.add_paragraph(f"Partial report — research did not complete ({report.get('partial_reason')}).").runs[0].bold = True
    d.add_heading(report["title"], 0)
    d.add_paragraph(f"Question: {report['question']}")
    d.add_paragraph(f"Mode: {report.get('mode')} · Version {report.get('version')} · Generated {str(report.get('created_at'))[:19]} UTC")

    def section(title: str, pars: list[dict[str, Any]]) -> None:
        if pars:
            d.add_heading(title, 1)
            for p in pars:
                d.add_paragraph(paragraph_plain(p))

    section("Executive summary", report.get("executive_summary") or [])
    if report.get("key_findings"):
        d.add_heading("Key findings", 1)
        for f in report["key_findings"]:
            s = (f.get("strength") or {}).get("label")
            d.add_paragraph(paragraph_plain(f) + (f" (evidence: {s})" if s else ""), style="List Bullet")
    for s in report.get("sections") or []:
        section(s["title"], s.get("paragraphs") or [])
    for t in report.get("tables") or []:
        d.add_heading(t["title"], 1)
        table = d.add_table(rows=1, cols=len(t["columns"]) + 1)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "Attribute"
        for i, c in enumerate(t["columns"]):
            hdr[i + 1].text = c
        for row in t["rows"]:
            cells = table.add_row().cells
            cells[0].text = row["attribute"]
            for i, c in enumerate(row["cells"]):
                cells[i + 1].text = c["value"] + "".join(f"[{n}]" for n in c.get("sources", []))
    section("Conflicting evidence", report.get("conflicts") or [])
    if report.get("limitations"):
        d.add_heading("Limitations", 1)
        for x in report["limitations"]:
            d.add_paragraph(x, style="List Bullet")
    if report.get("unknowns"):
        d.add_heading("What is still unknown", 1)
        for u in report["unknowns"]:
            d.add_paragraph(f"{u['question']} — {u['why']}", style="List Bullet")
    section("Conclusions", report.get("conclusions") or [])
    if report.get("recommendations"):
        d.add_heading("Recommendations", 1)
        for r in report["recommendations"]:
            d.add_paragraph(paragraph_plain(r), style="List Bullet")
    d.add_heading("Sources", 1)
    for b in bibliography(sources, cited_numbers(report)):
        meta = ", ".join(x for x in [b.get("publisher") or b.get("domain"), b.get("author"), str(b.get("published_at") or "n.d.")[:10]] if x)
        d.add_paragraph(f"[{b['number']}] {b['title']} — {meta}. {b['url']}")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


async def run_export_job(job: dict[str, Any], ctx: JobContext, token: str) -> None:
    opts = job.get("options", {})
    fmt = opts.get("format")
    report = await col(Collections.research_reports).find_one({"_id": opts.get("report_id"), "user_id": job["user_id"]})
    if not report or fmt not in MIME:
        await lifecycle.finish(job["_id"], token, "failed", last_error={"code": "not_found", "message": "Report not found."})
        return
    sources = await col(Collections.research_sources).find({"job_id": report["job_id"]}).sort("number", 1).to_list(None)
    await ctx.set_stage("exporting", status="synthesizing", message=f"Preparing {fmt.upper()}")
    try:
        import asyncio

        data = await asyncio.to_thread(render_pdf if fmt == "pdf" else render_docx, report, sources)
    except Exception as e:  # noqa: BLE001
        await lifecycle.finish(job["_id"], token, "failed",
                               last_error={"code": "export_failed", "message": f"Could not generate the {fmt.upper()} file.",
                                           "detail": type(e).__name__})
        await emit_event(job["_id"], job["user_id"], "failed", f"Export failed ({fmt.upper()}).", {}, level="error")
        return
    if len(data) > 15 * 1024 * 1024:
        await lifecycle.finish(job["_id"], token, "failed", last_error={"code": "export_too_large",
                                                                        "message": "The export is too large."})
        return
    await col(Collections.exports).update_one(
        {"_id": job["_id"]},
        {"$set": {"user_id": job["user_id"], "report_id": report["_id"], "format": fmt, "mime": MIME[fmt],
                  "filename": f"{_slug(report['title'])}-v{report['version']}.{fmt}", "data": Binary(data),
                  "size": len(data), "created_at": utcnow(), "expires_at": utcnow() + EXPORT_TTL}},
        upsert=True)
    await lifecycle.finish(job["_id"], token, "completed", stage="done")
    await emit_event(job["_id"], job["user_id"], "completed", "Export ready", {"export_id": job["_id"]}, stage="done")


def _slug(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "report"


__all__ = ["charts_csv", "render_docx", "render_markdown", "render_pdf", "run_export_job"]
