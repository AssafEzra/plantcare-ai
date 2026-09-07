# PlantCare AI

AI-powered personal manager for every plant in the home. Hebrew (RTL) MVP.

**Stack:** Streamlit → FastAPI → orchestration/domain services → Supabase (PostgreSQL / Auth / Storage), with a provider-agnostic AI Gateway and Resend for email.

Full specification lives in [`PlantCare_AI_Spec/`](./PlantCare_AI_Spec). The spec is authoritative — when code and spec disagree, one of them is a bug.

## Quick start

```bash
git clone <repository>
cd plantcare-ai
git checkout dev

uv sync --all-groups          # creates .venv and installs everything
cp .env.example .env          # then fill in from your DEV Supabase project

uv run pytest                 # unit tests
uv run uvicorn app.api.main:app --reload      # API  → http://localhost:8000
uv run streamlit run app/ui/streamlit_app.py  # UI   → http://localhost:8501
```

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/) and the Supabase CLI.

## Architecture

```
UI → API → Orchestration / Domain Services → Repositories / Infrastructure → Supabase
```

Dependency direction is one-way. A few rules are load-bearing and enforced by tests:

- **Agents never call each other.** Orchestration coordinates them.
- **RLS is the security boundary.** The API talks to Postgres with the caller's JWT so row-level security actually applies; the service-role key is reserved for system writes.
- **Scheduling is deterministic Python.** No LLM computes a recurrence.
- **Versioned records are immutable.** Knowledge versions, care events, health assessments and system events are never updated in place.
- **AI failure never creates an authoritative record.**
- **Configuration is centralised.** Nothing outside `app/config/settings.py` reads `os.environ` — ruff enforces this.

## Layout

| Path | Purpose |
|---|---|
| `app/ui/` | Streamlit pages and components. No business logic. |
| `app/api/` | FastAPI routers and request/response schemas. |
| `app/agents/` | The four AI agents behind stable contracts. |
| `app/orchestration/` | Workflows that coordinate agents and services. |
| `app/domain/` | Models, services and pure rules (lifecycle, recurrence, validation). |
| `app/repositories/` | Persistence only — no business rules. |
| `app/infrastructure/` | Supabase, Storage, AI providers, email. |
| `prompts/` | Versioned prompt files (`<agent>/<name>.v001.md`). |
| `supabase/migrations/` | SQL migrations (canonical — see `migrations/README.md`). |
| `tests/` | `unit`, `integration`, `api`, `agents`, `security`, `e2e`. |

## Environments

DEV and PROD are entirely separate Supabase projects. Local development points at DEV, never PROD. See `docs/ENVIRONMENTS.md`.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). Branch from `dev`; `main` is production.

