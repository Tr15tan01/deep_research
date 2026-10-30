"""Document parsers, executed in a resource-limited subprocess (see sandbox.py).

This file must only import the standard library and the parsing libraries, because it is
run directly by file path in isolated mode (``python -I parsers.py <kind>``) with the
document bytes on stdin and JSON on stdout.
"""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile

MAX_TEXT_CHARS = 2_000_000
MAX_PDF_PAGES = 600
MAX_ZIP_ENTRIES = 3000
MAX_ZIP_UNCOMPRESSED = 150 * 1024 * 1024
MAX_ZIP_RATIO = 250


def _limits(cpu_seconds: int = 40, mem_bytes: int = 1536 * 1024 * 1024) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 2))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))  # no file writes
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except Exception:  # noqa: BLE001,S110 — best effort on non-Linux
        pass


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT_CHARS]


def parse_html(data: bytes) -> dict:
    import trafilatura

    html = data.decode("utf-8", errors="replace")
    out = trafilatura.extract(html, output_format="json", with_metadata=True, include_comments=False,
                              include_tables=True, favor_precision=True, deduplicate=True)
    if not out:
        # Fallback: crude tag strip so we at least have something to verify against.
        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        body = re.sub(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>", " ", html)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        return {"text": _clean(re.sub(r"[ \t]{2,}", " ", body)), "title": (title_m.group(1).strip() if title_m else None),
                "warnings": ["main-content extraction failed; used raw text"]}
    meta = json.loads(out)
    return {"text": _clean(meta.get("text") or meta.get("raw_text") or ""), "title": meta.get("title"),
            "author": meta.get("author"), "published": meta.get("date"), "site_name": meta.get("sitename"),
            "warnings": []}


def parse_pdf(data: bytes) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                return {"text": "", "warnings": ["encrypted PDF"], "pages": 0}
        except Exception:  # noqa: BLE001
            return {"text": "", "warnings": ["encrypted PDF"], "pages": 0}
    pages = len(reader.pages)
    warnings = []
    parts: list[str] = []
    total = 0
    for i, page in enumerate(reader.pages):
        if i >= MAX_PDF_PAGES:
            warnings.append(f"only first {MAX_PDF_PAGES} pages processed")
            break
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
            warnings.append(f"page {i + 1} could not be read")
        parts.append(f"[page {i + 1}]\n{t}")
        total += len(t)
        if total > MAX_TEXT_CHARS:
            warnings.append("text truncated")
            break
    meta = {}
    try:
        info = reader.metadata or {}
        meta = {"title": info.get("/Title"), "author": info.get("/Author"), "published": str(info.get("/CreationDate") or "") or None}
    except Exception:  # noqa: BLE001
        pass
    text = _clean("\n\n".join(parts))
    if len(text) < 50 and pages:
        warnings.append("little or no extractable text (scanned PDF?); OCR is not enabled")
    return {"text": text, "pages": pages, "warnings": warnings, **{k: (str(v) if v else None) for k, v in meta.items()}}


def _check_zip(data: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ValueError("archive has too many entries")
        total = 0
        for inf in infos:
            total += inf.file_size
            if inf.compress_size and inf.file_size / max(inf.compress_size, 1) > MAX_ZIP_RATIO and inf.file_size > 1_000_000:
                raise ValueError("suspicious compression ratio (possible zip bomb)")
            if ".." in inf.filename or inf.filename.startswith("/"):
                raise ValueError("unsafe archive path")
        if total > MAX_ZIP_UNCOMPRESSED:
            raise ValueError("archive expands beyond the allowed size")


def parse_docx(data: bytes) -> dict:
    _check_zip(data)
    import docx  # python-docx

    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables[:200]:
        for row in table.rows[:500]:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    props = d.core_properties
    return {"text": _clean("\n\n".join(parts)), "title": props.title or None, "author": props.author or None,
            "published": props.created.isoformat() if props.created else None, "warnings": []}


def parse_text(data: bytes) -> dict:
    for enc in ("utf-8", "utf-16"):
        try:
            return {"text": _clean(data.decode(enc)), "warnings": []}
        except UnicodeDecodeError:
            continue
    return {"text": _clean(data.decode("latin-1", errors="replace")), "warnings": ["decoded as latin-1"]}


PARSERS = {"html": parse_html, "pdf": parse_pdf, "docx": parse_docx, "txt": parse_text, "md": parse_text}


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    data = sys.stdin.buffer.read()
    _limits()
    fn = PARSERS.get(kind)
    if fn is None:
        print(json.dumps({"error": f"unsupported kind {kind}"}))
        return
    try:
        result = fn(data)
    except Exception as e:  # noqa: BLE001
        result = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
