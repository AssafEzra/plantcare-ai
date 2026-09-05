# PlantCare AI — Project Structure

## 1. Purpose

This document defines the recommended repository structure, module boundaries, naming conventions, and dependency direction for PlantCare AI.

The goal is to keep UI, domain logic, AI Agents, infrastructure, and persistence clearly separated so the MVP can evolve without rewriting the core architecture.

## 2. Repository Layout

```text
plantcare-ai/
├── app/
│   ├── ui/
│   │   ├── streamlit_app.py
│   │   ├── app_pages/     # see §13
│   │   │   ├── home.py
│   │   │   ├── my_plants.py
│   │   │   ├── add_plant.py
│   │   │   ├── plant_dashboard.py
│   │   │   ├── settings.py
│   │   │   └── admin.py
│   │   ├── components/
│   │   ├── state/
│   │   └── styles/
│   │
│   ├── api/
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   ├── routers/
│   │   └── schemas/
│   │
│   ├── agents/
│   │   ├── base.py
│   │   ├── identification/
│   │   ├── knowledge/
│   │   ├── care/
│   │   └── health/
│   │
│   ├── orchestration/
│   │   ├── workflows/
│   │   └── services/
│   │
│   ├── domain/
│   │   ├── models/
│   │   ├── services/
│   │   └── rules/
│   │
│   ├── repositories/
│   │   ├── profiles.py
│   │   ├── plants.py
│   │   ├── knowledge.py
│   │   ├── care.py
│   │   ├── health.py
│   │   └── agents.py
│   │
│   ├── infrastructure/
│   │   ├── supabase/
│   │   ├── storage/
│   │   ├── ai/
│   │   └── email/
│   │
│   ├── notifications/
│   │   └── service.py
│   │
│   ├── config/
│   │   ├── settings.py
│   │   └── logging.py
│   │
│   └── common/
│       ├── errors.py
│       ├── enums.py
│       └── utils.py
│
├── prompts/
│   ├── identification/
│   ├── knowledge/
│   ├── care/
│   └── health/
│
├── migrations/          # pointer only — see §12
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── api/
│   ├── agents/
│   ├── ui/              # AppTest; added in PR 9, absent from this tree until PR 23
│   ├── security/        # the RLS matrix (PR 23)
│   └── e2e/             # the nine journeys (PR 23)
│
├── docs/
├── scripts/
├── .env.example
├── .gitignore
├── README.md
├── DEVELOPMENT_PROGRESS.md
├── pyproject.toml
└── Dockerfile
```

## 3. Dependency Direction

Preferred dependency flow:

```text
UI
 ↓
API
 ↓
Orchestration / Domain Services
 ↓
Repositories / Infrastructure
 ↓
Supabase / Storage / External Providers
```

Agents are domain-level components invoked by orchestration. Agents must not call one another directly.

The domain layer must not depend on Streamlit.

## 4. Naming

- Python files/modules: `snake_case`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Pydantic request/response schemas: descriptive `*Request`, `*Response`
- Agent contracts: explicit domain names such as `IdentificationRequest`, `IdentificationResult`
- Database tables: `snake_case`, plural
- API paths: plural nouns where appropriate, under `/v1`

## 5. Agent Boundary

Each Agent exposes a stable contract:

```text
IdentificationAgent.identify(request)
KnowledgeAgent.generate(request)
CareAgent.generate_plan(request)
HealthAgent.assess(request)
```

Agent implementations use the AI Gateway abstraction and never contain provider-specific credentials or SDK assumptions.

## 6. Configuration

All environment-specific configuration belongs in `app/config`.

Do not read `os.environ` throughout the codebase. Centralize configuration through a settings object.

AI model selection is configuration-driven:

```text
IDENTIFICATION_MODEL
KNOWLEDGE_MODEL
CARE_MODEL
HEALTH_MODEL
```

## 7. UI Boundary

Streamlit pages should orchestrate presentation and user interaction only.

They should not:
- contain SQL;
- call Supabase directly for business operations;
- implement Agent prompts;
- decide authorization;
- mutate authoritative records without going through application services.

## 8. Repository Boundary

Repositories encapsulate persistence operations.

Business rules belong in domain/application services rather than repository methods.

## 9. Prompts

Prompts are versioned files, not anonymous strings scattered through Python code.

Recommended convention:

```text
prompts/<agent>/<prompt_name>.v001.md
```

The active prompt version must be recorded in `agent_executions`.

## 10. Testing

Every new domain rule should have a unit test. API behavior, RLS, Agent contracts, and critical user journeys require dedicated tests as described in `TESTING_STRATEGY.md`.

## 11. Architectural Rule

When in doubt, prefer explicit boundaries over convenience.

A temporary shortcut is acceptable during prototyping only if it does not make the long-term architecture harder to recover.

## 12. Migrations Directory — Recorded Deviation

This document specifies a top-level `migrations/` directory. The Supabase CLI
requires migrations under `supabase/migrations/` and will not discover them
elsewhere.

**Resolution:** `supabase/migrations/` is canonical. The top-level `migrations/`
directory is retained and contains a `README.md` pointing there, so the repository
layout does not silently diverge from this specification.

Classified: MVP. Rationale: tooling constraint, not a design preference. Recorded
per `FINAL_SPECIFICATION §37`.

## 13. UI Pages Directory — Recorded Deviation

This document names `app/ui/pages/`. Streamlit reserves a `pages/` directory
beside the entry script for its legacy auto-discovery API, which would compete
with the explicit `st.navigation` routing the app uses. Streamlit's own guidance
is to name the directory anything but `pages/`.

**Resolution:** the directory is `app/ui/app_pages/`. Nothing else about the
structure changes.

Classified: MVP. Rationale: framework constraint, not a design preference.
Recorded per `FINAL_SPECIFICATION §37`.

## 14. UI Styling — Where It Lives

`UI_DESIGN_TOKENS_AND_WIREFRAMES` expresses the visual direction as CSS custom
properties. In implementation those live in `.streamlit/config.toml`, which
Streamlit applies to its own components — colours, fonts, radii and the heading
scale all map onto native theme options.

Hand-written CSS is confined to `app/ui/styles/rtl.py` and covers only
right-to-left layout, which Streamlit's theming cannot express. This is
deliberate: CSS written against Streamlit's internal class names breaks silently
on upgrade, so the smaller that surface, the better.

One trap worth knowing: Streamlit rejects the **entire** `[theme]` block when any
option is invalid — for instance a Google Fonts URL requesting two families — and
reports it only in the server log. The app then renders in default styling with
no browser-visible error. `tests/ui/test_theme_config.py` guards the cases that
trigger it.
