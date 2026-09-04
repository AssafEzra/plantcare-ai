# Contributing

## Branches

`main` is production-ready. `dev` is the integration branch. Branch from `dev`:

```
feature/<short-description>
fix/<short-description>
chore/<short-description>
```

Open a PR into `dev`. Releases merge `dev` → `main`. Production never deploys from an unreviewed feature branch.

## Before you push

```bash
uv run ruff format .
uv run ruff check . --fix
uv run mypy app
uv run pytest -m "not live and not integration and not e2e"
```

`pre-commit install` runs the first three automatically.

## The rules that matter

These are not style preferences — they are the architecture, and CI or review will reject violations:

1. **Never read `os.environ` outside `app/config/settings.py`.** Ruff has a banned-api rule for it.
2. **Never disable RLS to make something work.** If a query is blocked, the policy is wrong or you are using the wrong client.
3. **Never let an agent call another agent.** Orchestration coordinates.
4. **Never update an immutable record.** Knowledge versions, care events, health assessments and system events are append-only. Corrections create new rows.
5. **Never persist or log chain-of-thought.** The logging redactor drops it, but do not rely on that.
6. **Never let a failed AI call create an authoritative record.**
7. **Never commit `.env` or any credential.**
8. **Never put business logic in a Streamlit page or a repository.** Pages present; repositories persist; domain services decide.

## Changing the spec

Per `FINAL_SPECIFICATION §37`, a new requirement or a deviation from the spec must, **in the same PR**:

1. be added to the specification,
2. be classified MVP or Future,
3. record the decision and its rationale,
4. update `PlantCare_AI_DEVELOPMENT_PROGRESS_V1.md`,
5. never silently overwrite an existing architectural decision.

If a technical choice is genuinely unresolved, mark it `[~]` pending. Do not invent certainty.

## Tests

Every new domain rule needs a unit test. New user-owned tables need RLS tests. Agent work needs contract tests against mocked providers — never live models in CI.
