// The live view must only display what backend events actually say — no invented progress.
import { describe, expect, it } from "vitest";

import { deriveRun } from "@/components/research/run-view";
import type { JobEvent } from "@/lib/types";

let seq = 0;
const ev = (type: string, data: Record<string, unknown> = {}, level: JobEvent["level"] = "info", message = type): JobEvent =>
  ({ seq: ++seq, type, level, message, data, at: `2026-10-24T10:00:${String(seq).padStart(2, "0")}Z` });

describe("deriveRun", () => {
  it("is empty before any events arrive", () => {
    const r = deriveRun([]);
    expect(r.current).toBeNull();
    expect(r.queries).toBe(0);
    expect(r.sources).toEqual([]);
  });

  it("derives stages, counters and source states from real events", () => {
    const r = deriveRun([
      ev("stage", { stage: "understanding" }),
      ev("stage", { stage: "searching" }),
      ev("query", { query: "a", results: 5 }),
      ev("query", { query: "b", results: 3 }),
      ev("sources_rejected", { reasons: { "excluded domain": 2, "diversity cap": 1 } }),
      ev("source_found", { number: 1, source_id: "s1", url: "https://a.example/1", domain: "a.example" }, "info", "A"),
      ev("source_found", { number: 2, source_id: "s2", url: "https://b.example/2", domain: "b.example" }, "info", "B"),
      ev("stage", { stage: "reading" }),
      ev("source_extracted", { number: 1, words: 900, injection_suspected: true, content_kind: "full_text" }),
      ev("source_rejected", { number: 2, reason: "HTTP 403" }),
      ev("evidence", { number: 1, verified: 4, discarded: 1 }),
      ev("warning", {}, "warning", "Budget low"),
      ev("stage", { stage: "not_a_real_stage" }),
    ]);
    expect(r.current).toBe("reading"); // unknown stages are ignored, not displayed
    expect([...r.reached.keys()]).toEqual(["understanding", "searching", "reading"]);
    expect(r.queries).toBe(2);
    expect(r.rejectedCandidates).toBe(3);
    expect(r.verified).toBe(4);
    expect(r.discarded).toBe(1);
    expect(r.sources[0]).toMatchObject({ number: 1, state: "read", words: 900, injection: true, verified: 4, discarded: 1 });
    expect(r.sources[1]).toMatchObject({ number: 2, state: "inaccessible", reason: "HTTP 403" });
    expect(r.warnings.map((w) => w.message)).toEqual(["Budget low"]);
  });
});
