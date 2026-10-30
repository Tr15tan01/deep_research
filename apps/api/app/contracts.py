"""Shared API contracts exported for the frontend and other clients.

    python -m app.contracts            # write packages/shared/{openapi.json,contracts.json}
    python -m app.contracts --check    # exit 1 if the checked-in files are stale (used in CI)

``contracts.json`` holds the enumerations both sides must agree on (pipeline stages, job
statuses, SSE event types, research modes). The frontend's unit tests assert that its stage
timeline matches these, so a backend change cannot silently break the live progress view.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "packages" / "shared"

# Order matters: this is the order in which the pipeline enters stages.
PIPELINE_STAGES = ["understanding", "planning", "searching", "reading", "comparing", "gaps", "writing", "verifying",
                   "visualizing"]
AUXILIARY_STAGES = ["queued", "awaiting_approval", "exporting", "done"]

EVENT_TYPES = {
    "stage": "Pipeline entered a stage (data.stage)",
    "status": "Job status changed (data.status)",
    "understanding": "Question restated; ambiguities, clarifying questions and assumptions",
    "plan": "Research plan with sub-questions",
    "query": "A search ran (query, provider, results, new_results, cached, subquestion_id)",
    "query_failed": "A search failed (query, provider, error)",
    "source_found": "Candidate source selected (source_id, number, url, domain, provider)",
    "sources_rejected": "Candidates set aside, with reason counts",
    "source_extracted": "Source text read (words, content_kind, injection_suspected)",
    "source_rejected": "Source could not be accessed (reason)",
    "evidence": "Quotes verified/discarded for a source",
    "gap": "A sub-question lacks sufficient evidence",
    "contradiction": "Sources disagree (topic, evidence_ids)",
    "followup": "Bounded follow-up search round",
    "report_draft": "Draft written; citation validation summary",
    "verification": "Cited sentences checked against quotes",
    "charts": "Charts built from verified datapoints",
    "report": "Report published or a new version created",
    "warning": "Non-fatal problem (budget, injection, parse failure)",
    "retry": "Transient failure; automatic retry scheduled",
    "recovery": "Resumed from checkpoint after a restart",
    "usage": "Usage counters updated",
    "completed": "Job finished successfully",
    "failed": "Job stopped (code, resumable)",
    "cancelled": "Job cancelled by the user",
}


def contracts() -> dict[str, Any]:
    from app.jobs.lifecycle import ACTIVE_STATUSES, RUNNABLE_IDLE, TERMINAL
    from app.research.modes import MODES

    return {
        "api_version": "v1",
        "pipeline_stages": PIPELINE_STAGES,
        "auxiliary_stages": AUXILIARY_STAGES,
        "job_statuses": {"idle": list(RUNNABLE_IDLE), "active": list(ACTIVE_STATUSES),
                         "paused": ["awaiting_approval"], "terminal": list(TERMINAL)},
        "event_types": EVENT_TYPES,
        "research_modes": list(MODES),
        "sse": {"stream_path": "/api/v1/research/{job_id}/stream", "poll_path": "/api/v1/research/{job_id}/events",
                "resume_header": "Last-Event-ID", "resume_query": "after", "id": "monotonic per-job sequence number"},
    }


def openapi() -> dict[str, Any]:
    import os

    os.environ.setdefault("APP_ENV", "development")
    from app.main import create_app

    return create_app().openapi()


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n"


def main(argv: list[str]) -> int:
    files = {SHARED / "contracts.json": _dump(contracts()), SHARED / "openapi.json": _dump(openapi())}
    if "--check" in argv:
        stale = [p.name for p, body in files.items() if not p.exists() or p.read_text() != body]
        if stale:
            print("stale shared contracts: " + ", ".join(stale) + " — run `python -m app.contracts`")
            return 1
        print("shared contracts up to date")
        return 0
    SHARED.mkdir(parents=True, exist_ok=True)
    for p, body in files.items():
        p.write_text(body)
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
