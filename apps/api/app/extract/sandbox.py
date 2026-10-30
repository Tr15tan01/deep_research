"""Run document parsers in an isolated, resource-limited subprocess.

Parsing untrusted PDFs/DOCX/HTML is a classic exploit surface (parser bugs, decompression
bombs, pathological inputs). Each parse runs in a fresh ``python -I`` process with CPU,
memory, file-write and process limits, a wall-clock timeout and no inherited environment.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

PARSER_PATH = str(Path(__file__).with_name("parsers.py"))
_MAGIC = {
    "pdf": [b"%PDF-"],
    "docx": [b"PK\x03\x04"],
}


class ExtractionFailed(Exception):
    pass


def sniff_kind(data: bytes, declared: str) -> str:
    """Verify the file signature matches the declared type; returns the verified kind."""
    declared = declared.lower()
    if declared in _MAGIC:
        if not any(data.startswith(m) for m in _MAGIC[declared]):
            raise ExtractionFailed(f"file content does not match the {declared.upper()} format")
        return declared
    if declared in ("txt", "md"):
        if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise ExtractionFailed("file looks binary, not text")
        if data.startswith((b"%PDF-", b"PK\x03\x04", b"\x7fELF", b"MZ")):
            raise ExtractionFailed("file content does not match a text format")
        return declared
    if declared == "html":
        return "html"
    raise ExtractionFailed(f"unsupported type: {declared}")


async def extract(data: bytes, kind: str, timeout: float = 45.0) -> dict[str, Any]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "PYTHONHASHSEED": "0",
           "OMP_NUM_THREADS": "1"}
    if os.name == "nt":  # Windows cannot start Python without SYSTEMROOT; nothing else is inherited
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", PARSER_PATH, kind,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    try:
        out, _err = await asyncio.wait_for(proc.communicate(data), timeout=timeout)
    except TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise ExtractionFailed("document parsing timed out") from e
    if proc.returncode != 0:
        raise ExtractionFailed("document parser crashed or exceeded resource limits")
    try:
        result = json.loads(out.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError as e:
        raise ExtractionFailed("document parser returned invalid output") from e
    if "error" in result:
        raise ExtractionFailed(str(result["error"]))
    return result
