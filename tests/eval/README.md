# Agent evaluation

A repeatable, scored evaluation of the research agent. Each case in `dataset.jsonl` runs through the
real pipeline (API → durable job → worker → stored report), and the stored report is scored with
deterministic, transparent metrics. No LLM grades another LLM's essay here.

```bash
make eval                 # demo providers: deterministic, offline, what CI runs
make eval LIVE=1          # configured AI + search providers from .env (costs money; not run in CI)
cd apps/api && .venv/bin/python ../../tests/eval/run_eval.py --only fact-jwst-launch --live
```

Results go to `results/<timestamp>-<demo|live>.json`, with per-case rows plus a summary. The summary is
compared against `thresholds.json`, and a regression exits non-zero. **Re-run the live suite after any
prompt, model, or pipeline change** and commit the results file next to the change.

## Dataset

| Category | What a correct run looks like |
| --- | --- |
| `factual` | Known facts (with accepted alternatives) appear in the report, cited to retrieved sources. |
| `comparison`, `market` | Several independent domains; a comparison matrix whose cells cite evidence, or say "Not found in sources". |
| `academic` | Scholarly (OpenAlex) sources are used; limitations are stated. |
| `contradiction`, `counterarguments` | Disagreement is surfaced (conflicts or contradictions section), not averaged away. |
| `adversarial` | A false premise is rejected, and forbidden fabricated statements never appear. |
| `insufficient_evidence` | The correct answer is "the evidence is insufficient": the report must say so and must not invent. |
| `verify_claim` | A popular myth is identified as unsupported. |
| `prompt_injection` | Instruction-like text in a source is flagged and treated as data. |
| `freshness` | The report carries a freshness label for time-sensitive topics. |

`demo.run` marks cases that are meaningful against the synthetic demo corpus. Demo runs check the
*machinery*: completion, citation resolution, quote verification, injection flagging, matrix/charts built
only from verified data, and cost accounting. They cannot measure factual correctness. Cases whose
correctness depends on the real world (false premises, fictional people, future prices) are live-only.

## Metrics

| Metric | Definition |
| --- | --- |
| `completion_rate` | Share of cases ending `completed` with a `complete` (not partial) report. |
| `citation_validity` | Share of displayed citations that resolve to a retrieved, extracted source, plus evidence IDs that resolve to stored, quote-verified evidence. Not applicable when nothing is cited. |
| `citation_relevance` | Share of cited sources that the reading model scored ≥ 2 on its 0–3 relevance scale. |
| `claim_support` | Verifier verdicts on cited sentences (supported = 1, partial = 0.5) over sentences checked. |
| `cited_sentence_ratio` | Cited sentences ÷ all sentences in the report body. |
| `source_diversity` | Distinct registrable domains ÷ extracted sources. |
| `factual_score` | Live only: share of rubric facts found (any accepted alternative). |
| `check_pass_rate` | Share of per-case behavioural checks passed (forbidden text, insufficiency, conflicts, injection, …). |
| `cost_per_completed_usd` | Estimated provider cost (admin pricing table) ÷ completed cases. An estimate, never an invoice. |
| `latency_p50_s` / `latency_p95_s` | Wall-clock time per case. |

These metrics measure behaviour against a rubric, not truth in general. A high score does not certify a
report. It means the agent cited what it retrieved, did not invent, and admitted gaps on these cases.
Optimising for report length or user satisfaction alone is explicitly *not* a goal.

The harness itself is tested in `apps/api/tests/test_eval_harness.py`.
