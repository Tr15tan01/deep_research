# Shared contracts

Generated from the backend — **do not edit by hand**.

| File | What it is |
| --- | --- |
| `openapi.json` | OpenAPI 3 description of every `/api/v1` endpoint and health route. |
| `contracts.json` | Enumerations both sides must agree on: pipeline stages (in execution order), job statuses, SSE event types, research modes, SSE resume semantics. |

Regenerate after changing routes, stages, statuses or event types:

```bash
make contracts          # or: cd apps/api && python -m app.contracts
```

Drift is caught automatically:

- `apps/api/tests/test_contracts.py` fails if these files are stale, or if the code emits a stage or event type
  that is not declared here.
- `apps/web/tests/unit/contracts.test.ts` fails if the live-progress timeline in the frontend
  (`components/research/stages.ts`) does not match `pipeline_stages`.

Optional typed client: `npx openapi-typescript packages/shared/openapi.json -o apps/web/lib/openapi.d.ts`.
