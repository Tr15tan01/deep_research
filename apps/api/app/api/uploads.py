"""Document uploads (PDF, DOCX, TXT, Markdown) with signature checks, size limits,
sandboxed parsing, optional malware scanning and retention."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.auth.deps import Principal, current_principal, require_feature
from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.mongo import Collections, col, new_id
from app.extract.sandbox import ExtractionFailed, extract, sniff_kind
from app.security.injection import scan_for_injection
from app.services.account import delete_upload_files

log = get_logger("uploads")
router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"], dependencies=[Depends(require_feature("FILE_UPLOADS_ENABLED", "File uploads are disabled."))])
ALLOWED_EXT = {"pdf": "pdf", "docx": "docx", "txt": "txt", "md": "md", "markdown": "md"}
CHUNK_CHARS = 6000


def _safe_display_name(name: str) -> str:
    base = os.path.basename(name or "document")
    base = re.sub(r"[^\w.\- ()]+", "_", base)[:120]
    return base or "document"


async def malware_scan(data: bytes) -> tuple[bool, str]:
    """ClamAV (clamd INSTREAM) when CLAMAV_HOST is set; otherwise reported as 'not scanned'."""
    host = os.environ.get("CLAMAV_HOST")
    if not host:
        return True, "not_scanned"
    port = int(os.environ.get("CLAMAV_PORT", "3310"))
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5)
        writer.write(b"zINSTREAM\0")
        for i in range(0, len(data), 65536):
            chunk = data[i : i + 65536]
            writer.write(len(chunk).to_bytes(4, "big") + chunk)
        writer.write((0).to_bytes(4, "big"))
        await writer.drain()
        resp = (await asyncio.wait_for(reader.read(1024), timeout=30)).decode(errors="replace")
        writer.close()
        if "FOUND" in resp:
            return False, "infected"
        return ("OK" in resp), "clean" if "OK" in resp else "scan_error"
    except Exception:  # noqa: BLE001
        return False, "scan_unavailable"


@router.post("", status_code=201)
async def upload(request: Request, file: UploadFile = File(...), principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    s = get_settings()
    await ratelimit.enforce(ratelimit.UPLOAD, f"user:{principal.id}")
    display = _safe_display_name(file.filename or "")
    ext = display.rsplit(".", 1)[-1].lower() if "." in display else ""
    kind = ALLOWED_EXT.get(ext)
    if not kind:
        raise AppError("Only PDF, DOCX, TXT and Markdown files are supported.", code="unsupported_file_type", status_code=415)
    max_bytes = s.MAX_FILE_SIZE_MB * 1024 * 1024
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise AppError(f"Files must be {s.MAX_FILE_SIZE_MB} MB or smaller.", code="file_too_large", status_code=413)
    if not data:
        raise AppError("The file is empty.", code="empty_file", status_code=422)
    try:
        kind = sniff_kind(bytes(data), kind)
    except ExtractionFailed as e:
        raise AppError(str(e), code="file_signature_mismatch", status_code=415) from e
    ok, scan = await malware_scan(bytes(data))
    if not ok:
        raise AppError("The file failed the security scan and was rejected." if scan == "infected"
                       else "The malware scanner is unavailable; please try again later.", code=f"upload_{scan}",
                       status_code=422 if scan == "infected" else 503)
    upload_id = new_id("upl")
    os.makedirs(s.UPLOAD_DIR, mode=0o700, exist_ok=True)
    path = os.path.join(s.UPLOAD_DIR, upload_id + ".bin")  # server-generated name; never executable
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    doc = {"_id": upload_id, "user_id": principal.id, "filename": display, "kind": kind, "size": len(data),
           "status": "processing", "scan": scan, "storage_path": path, "created_at": utcnow(),
           "expires_at": utcnow() + timedelta(days=s.UPLOAD_RETENTION_DAYS)}
    await col(Collections.uploads).insert_one(doc)
    try:
        parsed = await extract(bytes(data), kind)
    except ExtractionFailed as e:
        await col(Collections.uploads).update_one({"_id": upload_id}, {"$set": {"status": "failed", "error": str(e)}})
        raise AppError(f"We couldn't read this document: {e}", code="extraction_failed", status_code=422) from e
    text = parsed.get("text") or ""
    if len(text.strip()) < 50:
        await col(Collections.uploads).update_one({"_id": upload_id}, {"$set": {"status": "failed", "error": "no text"}})
        raise AppError("No readable text was found (scanned images need OCR, which is not enabled).", code="no_text",
                       status_code=422)
    chunks = [text[i : i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)][:400]
    await col(Collections.upload_chunks).insert_many([
        {"_id": new_id("uch"), "upload_id": upload_id, "user_id": principal.id, "index": i, "text": c} for i, c in enumerate(chunks)])
    flags = scan_for_injection(text)
    upd = {"status": "ready", "chars": len(text), "pages": parsed.get("pages"), "doc_title": parsed.get("title"),
           "doc_author": parsed.get("author"), "doc_published": parsed.get("published"), "preview": text[:400],
           "warnings": parsed.get("warnings", []), "injection_flags": flags[:3]}
    await col(Collections.uploads).update_one({"_id": upload_id}, {"$set": upd})
    return {"upload": _out({**doc, **upd})}


def _out(u: dict[str, Any]) -> dict[str, Any]:
    return {"id": u["_id"], "filename": u["filename"], "kind": u["kind"], "size": u["size"], "status": u["status"],
            "chars": u.get("chars"), "pages": u.get("pages"), "warnings": u.get("warnings", []), "scan": u.get("scan"),
            "injection_suspected": bool(u.get("injection_flags")), "created_at": u["created_at"],
            "expires_at": u.get("expires_at"), "error": u.get("error")}


@router.get("")
async def list_uploads(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    items = await col(Collections.uploads).find({"user_id": principal.id}).sort("created_at", -1).limit(200).to_list(None)
    return {"items": [_out(u) for u in items], "retention_days": get_settings().UPLOAD_RETENTION_DAYS}


@router.delete("/{upload_id}")
async def delete_upload(upload_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    u = await col(Collections.uploads).find_one({"_id": upload_id, "user_id": principal.id})
    if not u:
        raise NotFound("Document not found.")
    await delete_upload_files(u)
    await col(Collections.upload_chunks).delete_many({"upload_id": upload_id})
    await col(Collections.uploads).delete_one({"_id": upload_id})
    return {"deleted": True}


async def purge_expired_uploads() -> int:
    expired = await col(Collections.uploads).find({"expires_at": {"$lt": utcnow()}}).limit(500).to_list(None)
    for u in expired:
        await delete_upload_files(u)
        await col(Collections.upload_chunks).delete_many({"upload_id": u["_id"]})
        await col(Collections.uploads).delete_one({"_id": u["_id"]})
    return len(expired)
