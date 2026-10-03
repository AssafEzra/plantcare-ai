# PlantCare AI

AI-powered personal manager for every plant in the home. Hebrew (RTL) MVP.

**Stack:** React + TypeScript (Vite, PWA) → FastAPI → orchestration/domain services → Supabase (PostgreSQL / Auth / Storage), with a provider-agnostic AI Gateway and Resend for email.

Full specification lives in [`PlantCare_AI_Spec/`](./PlantCare_AI_Spec). The spec is authoritative — when code and spec disagree, one of them is a bug.

## Quick start

```bash
git clone <repository>
cd plantcare-ai
git checkout dev

uv sync --all-groups          # creates .venv and installs everything
cp .env.example .env          # then fill in from your DEV Supabase project

uv run pytest                 # unit tests
uv run uvicorn app.api.main:app --reload   # API → http://localhost:8000
```

Then the interface, in a second terminal:

```bash
cd frontend
npm install
cp .env.example .env.local    # VITE_SUPABASE_URL and the anon key
npm run dev                   # → http://localhost:5173
```

Vite proxies `/v1` to the API on :8000, so the browser sees one origin and no CORS
configuration is needed. `npm run preview` (:4173) serves the built bundle and is
the only way to exercise the service worker.

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+ and the Supabase CLI.

## Architecture

```
Browser (React) → API → Orchestration / Domain Services → Repositories / Infrastructure → Supabase
```

In production both halves ship in one container: uvicorn serves `/v1` and the built
bundle from the same origin (`app/api/spa.py`). See `docs/DEPLOY_CLOUD_RUN.md`.

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
| `frontend/` | The interface: React + TypeScript, built with Vite. No business logic. |
| `app/api/` | FastAPI routers and request/response schemas. |
| `app/agents/` | The four AI agents behind stable contracts. |
| `app/orchestration/` | Workflows that coordinate agents and services. |
| `app/domain/` | Models, services and pure rules (lifecycle, recurrence, validation). |
| `app/repositories/` | Persistence only — no business rules. |
| `app/infrastructure/` | Supabase, Storage, AI providers, email. |
| `prompts/` | Versioned prompt files (`<agent>/<name>.v001.md`). |
| `supabase/migrations/` | SQL migrations (canonical — see `migrations/README.md`). |
| `tests/` | `unit`, `integration`, `api`, `agents`, `security`, `e2e`. The interface has no test runner yet — see `TESTING_STRATEGY.md`. |

## Environments

DEV and PROD are entirely separate Supabase projects. Local development points at DEV, never PROD. See `docs/ENVIRONMENTS.md`.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). Branch from `dev`; `main` is production.

