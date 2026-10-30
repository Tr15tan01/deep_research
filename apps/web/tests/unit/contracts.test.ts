// The live-progress timeline must match the stages the backend actually emits
// (packages/shared/contracts.json is generated from the backend and drift-checked there).
import { describe, expect, it } from "vitest";

import contracts from "../../../../packages/shared/contracts.json";
import { STAGES } from "@/components/research/stages";
import { ACTIVE, TERMINAL } from "@/lib/utils";

describe("shared contracts", () => {
  it("timeline stages equal backend pipeline stages, in execution order", () => {
    expect(STAGES.map((s) => s.key)).toEqual(contracts.pipeline_stages);
  });

  it("frontend status sets agree with backend job statuses", () => {
    expect([...TERMINAL].sort()).toEqual([...contracts.job_statuses.terminal].sort());
    for (const s of [...contracts.job_statuses.idle, ...contracts.job_statuses.active]) expect(ACTIVE.has(s)).toBe(true);
  });
});
