# PlantCare AI — Project Structure

## 1. Purpose

This document defines the recommended repository structure, module boundaries, naming conventions, and dependency direction for PlantCare AI.

The goal is to keep UI, domain logic, AI Agents, infrastructure, and persistence clearly separated so the MVP can evolve without rewriting the core architecture.

## 2. Repository Layout

```text
plantcare-ai/
├── frontend/              # the interface: React + TypeScript + Vite, a PWA
│   ├── src/
│   │   ├── pages/         # Tasks, MyPlants, Health, AddPlant, PlantDashboard,
│   │   │                  #   Settings, Admin, Auth, More
│   │   ├── components/
│   │   ├── api/           # one module per resource, over fetch
│   │   ├── app/           # AppShell: header, sidebar, bottom nav
│   │   ├── auth/          # supabase-js session handling
│   │   ├── lib/           # api client, errors, dates, vocabulary
│   │   └── styles/        # tokens.css, base.css, components.css
│   └── dist/              # `npm run build` output; served by app/api/spa.py
│
├── app/
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
│   ├── e2e/             # the nine journeys (PR 23)
│   └── browser/         # PR 31: real Chromium, real API, live model. Marked
│                        # `browser` and excluded from CI - it is the only layer
│                        # that renders and calls at the same time, which is
│                        # where every serious defect in this build has lived
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

The domain layer must not depend on the web framework, and cannot depend on the
interface at all: the interface is a separate TypeScript application that reaches
data only over `/v1`. `tests/unit/test_architecture_boundaries.py` walks the import
graph for the rules it can still check from Python.

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

The interface orchestrates presentation and user interaction only.

It should not:
- contain SQL;
- call Supabase directly for business operations;
- implement Agent prompts;
- decide authorization;
- mutate authoritative records without going through application services.

Most of this is now structural rather than a rule to remember. The interface is a
bundle running in a browser: it has no database driver, no agent module and no
service layer to reach past, so four of the five are things it *cannot* do rather
than things it must not. What remains a genuine discipline is the last one — every
write goes through `/v1`, and the interface must not treat a 202 as a completed
change.

The one exception is authentication, and it is deliberate. `frontend/src/auth/`
talks to Supabase Auth directly, because obtaining a credential is not a business
operation and proxying it through the API would buy nothing. The browser holds the
anon key, which is public by design; the service-role key never leaves the server.

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

## 13. UI Pages Directory — Deviation Withdrawn

This document names `app/ui/pages/`. Streamlit reserved `pages/` beside the entry
script for its legacy auto-discovery API, which competed with the explicit
`st.navigation` routing, so the directory was `app/ui/app_pages/`.

**Withdrawn.** There is no `app/ui/`. Screens live in `frontend/src/pages/`, and
the framework constraint that forced the rename does not exist in React Router —
routes are declared in `frontend/src/App.tsx` and the directory is named for what
it holds.

Kept as a record rather than deleted, because the original deviation is in the
history and a reader who finds `app_pages` in an old commit should be able to
learn why. Recorded per `FINAL_SPECIFICATION §37`.

## 14. UI Styling — Where It Lives

`UI_DESIGN_TOKENS_AND_WIREFRAMES` expresses the visual direction as CSS custom
properties, and they are now literally that: `frontend/src/styles/tokens.css`
holds the palette, type scale, spacing and radii; `base.css` the element
defaults; `components.css` the shared pieces. Everything else is a stylesheet
beside the component it styles.

This was `.streamlit/config.toml`, which mapped the tokens onto Streamlit's own
theme options because hand-written CSS against that framework's internal class
names broke silently on upgrade. The constraint is gone — the stylesheets are the
implementation now, not a translation of it — and so is the trap that came with
it, where an invalid `[theme]` option made Streamlit discard the whole block and
report it only in the server log.

Two rules replaced it, both enforceable by reading:

- **Logical properties only.** No `left`, `right`, `margin-left`,
  `padding-right`. The interface is Hebrew and right-to-left, so a physical
  offset is a bug that only shows up in one direction. A grep for those
  properties across `frontend/src` should return nothing but comment prose.
- **Two breakpoints.** 640px for components and 900px for the shell, which is
  where the sidebar replaces the bottom navigation. Where content width rather
  than viewport width decides a layout, `auto-fill` sizing does the work instead
  of a third breakpoint.
