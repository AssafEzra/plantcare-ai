# PlantCare AI — MVP Implementation Plan

> **Status:** in progress — PRs 1–12 of 24 delivered.
> **Repository:** https://github.com/AssafEzra/plantcare-ai (branch `dev`)
> **DEV environment:** Supabase project `plantcare-dev`, eu-central-1
>
> This document is the execution plan: 24 reviewable PRs across 18 phases, in the
> order `DEVELOPMENT_PROGRESS §24` prescribes. It is a living document — each PR
> records what it actually did, including where implementation diverged from the
> plan and why.
>
> It was written by reading all nine specification documents, then revised after
> an independent gap audit of the plan against those documents. That audit found
> 12 coverage gaps, 6 contradictions and 12 additional ambiguities; all are folded
> in below and marked **[audit]**.

## How to read this document

- **Delivery status** — one table, what is done and what is next.
- **Architectural invariants** — the rules every PR must preserve, and the
  mechanism that enforces each. These are not aspirations; each has a named test.
- **Decisions taken** — four choices the specification left open, plus the schema
  additions they required.
- **Phases and PRs** — the plan itself.
- **Spec ambiguities** — 28 places the specification is unclear, each with a
  recommendation. Four were resolved before Phase 2 because migrations are
  expensive to reverse; the rest carry a working default.
- **Amendments during implementation** — every deviation from this plan or from
  the specification, with its reason. Per `FINAL_SPECIFICATION §37`, nothing is
  changed silently.

## Context

The project began with `PlantCare_AI_Spec/` alone — nine documents, 3,609 lines,
no repository, no code, no Supabase project. All product decisions were closed
(`DEVELOPMENT_PROGRESS §1`), and the spec's own next step was *"Start
implementation"* with an 18-item ordered milestone list (`§24`).

This plan turns that milestone list into **24 reviewable PRs across 18 phases**,
preserving every architectural invariant in the spec, and flags where the spec is
ambiguous rather than guessing.

Target: the Definition of Done in `FINAL_SPECIFICATION §35`.

---

## Delivery status

| PR | Phase | Scope | Status |
|---|---|---|---|
| 1 | 0 · Repo & tooling | uv, ruff, mypy, pytest, CI, settings, logging, enums, errors | ✅ |
| 2 | 1 · Supabase DEV | DEV + PROD projects, Auth config, storage bucket | ✅ |
| 3 | 2 · Migrations | Enums, `profiles`, `notification_preferences`, `is_admin()`, triggers | ✅ |
| 4 | 2 · Migrations | `species`, `plants`, `plant_environments`, `plant_images`, identification | ✅ |
| 5 | 2 · Migrations | Knowledge drafts, versions, sources, approved sources, reports | ✅ |
| 6 | 2 · Migrations | Care, health, AI infra, notifications, audit, storage policies, seed | ✅ |
| 7 | 3 · Auth | Supabase clients, JWKS verification, `/v1/me`, admin gating | ✅ |
| 8 | 4 · API structure | Rate limiting, readiness, request timing, error envelopes | ✅ |
| 9 | 5 · Streamlit shell | RTL Hebrew UI, design tokens, navigation, auth flows | ✅ |
| 10 | 6 · Image pipeline | Validation, EXIF handling, derivatives, storage adapter | ✅ |
| 11 | 7 · Add Plant slice | Plants CRUD, archive/restore, environment, image endpoints, grid | ✅ |
| 12 | 8 · AI Gateway | Provider abstraction, gateway, prompts, request lifecycle | ✅ |
| 13 | 8 · Identification | `IdentificationAgent`, Wikipedia verification, confirm workflow | ✅ |
| 14 | 9 · Knowledge Agent | Research, deterministic source verification | ✅ |
| 15 | 9 · Knowledge admin | Review, publication, fan-out to pending plants | ✅ |
| 16 | 10 · Care Agent | Context assembly, proposals, operational adjustment | ✅ |
| 17 | 11 · Scheduler | Deterministic recurrence, tasks, events, `/internal/tick` | ✅ |
| 18 | 11 · Home dashboard | The twelve `PROGRESS §9` items **[audit]** | ✅ |
| 19 | 12 · Notifications | Resend provider, digest, `dedupe_key` idempotency | ✅ |
| 20 | 13 · Plant dashboard | Full view model, history timeline | ✅ |
| 21 | 14 · Health Agent | Assessment, findings, sources, Python-computed trend | ✅ |
| 22 | 15 · Admin panel | Monitoring, reports, audit log, anonymisation | ✅ |
| 23 | 16 · Testing | Nine E2E journeys, RLS matrix, no-authoritative-record | ✅ |
| 24 | 17 · Deployment | Railway, PROD Supabase, cron tick, alerts, runbook | ▶ next |

**1,461 tests** currently pass - 864 unit, API, agent and UI tests that CI runs on
every push, plus 597 integration, journey and RLS-matrix tests executed against the
DEV Supabase project, plus one live provider test excluded from both.

---

## Architectural invariants (must hold in every PR)

| Invariant | Source | Enforced by |
|---|---|---|
| Agents never call each other; orchestration coordinates | `FINAL §23`, `STRUCTURE §5` | Import-boundary test: `app/agents/**` may not import another agent or `app.repositories` |
| RLS on every user-owned table; Python checks insufficient | `FINAL §26`, `SCHEMA` RLS model | Generated RLS matrix test (Phase 16) |
| **Content**-immutable, status-mutable: `care_plan_versions` **[audit]** | `SCHEMA` care_plan_versions | Trigger rejects UPDATE of `professional_recommendations`/`operational_preferences`/`version_number`; **permits `status` transitions** (`PROPOSED→ACTIVE→SUPERSEDED/REJECTED`) |
| **Content**-immutable, `is_current` mutable: `knowledge_versions` **[corrected in PR 5]** | `SCHEMA` knowledge_versions | Trigger protects content/version/language/published_*; permits the `is_current` flip publication requires. DELETE refused outright (`FINAL §29`) |
| Row-immutable: `care_events`, `health_assessments`, `system_events` | `FINAL §1.5` | `BEFORE UPDATE/DELETE` trigger rejecting all mutation |
| Scheduling is deterministic Python, never an LLM | `FINAL §1.4, §13` | `app/domain/rules/recurrence.py` is pure; zero imports from `app.agents`/`app.infrastructure.ai` |
| Structured output, max **2** retries, no chain-of-thought persisted | `FINAL §23`, `API` | Gateway unit tests; `agent_executions` column allow-list |
| AI failure never creates an authoritative record | `FINAL §25`, `TESTING §13` | Per-agent failure test asserting zero rows written |
| Professional recommendations not user-editable | `FINAL §12` | Operational-adjustment test asserting recs copied byte-identical |
| Published Knowledge never deleted; one current version per species+language | `FINAL §10, §29` | Partial unique index + immutability trigger |

**[audit] Contradiction fixed:** the first draft listed `care_plan_versions` as row-immutable while Phase 10 required updating its `status` to `SUPERSEDED` — impossible under such a trigger, and `DATABASE_SCHEMA` never calls the row immutable. The invariant is now content-immutability.

---

## Decisions taken (were open in the spec)

1. **Data access — user-JWT via PostgREST.** Request-scoped `supabase-py` client built from the caller's access token for all user-scoped work, so RLS is genuinely the boundary. **Service-role reserved** for: `agent_executions`, `agent_requests` status writes, `system_events`, knowledge publication, notification sends, `/internal/tick`. Aggregate reads use `SECURITY INVOKER` RPCs so RLS still applies.
2. **Species created at confirm, not at identification.** `identification_candidates` stores raw `scientific_name`/`common_name`, `species_id` nullable; `confirm` takes `{"candidate_id": "uuid"}` and upserts `species` then. Keeps hallucinated binomials out of the taxonomy table. *(Deviation from `API_CONTRACTS`'s `confirmed_species_id`.)*
3. **Scheduling — cron endpoint + lazy reads.** State computed on read; `POST /v1/internal/tick` (shared secret, service-role) every ~15 min persists OVERDUE transitions, writes `MISSED` events, dispatches email. Tick body is a pure function of `(now, rules, events)`.
4. **AI content in Hebrew, `language` column now.** Current-version uniqueness keys on `(species_id, language)`.

### Schema additions beyond `DATABASE_SCHEMA_V1.md` — all resolved

Per `FINAL §37` each is written back into the spec in the PR that introduces it. **These are settled decisions, not open questions** — they were resolved before Phase 2 because migrations are expensive to reverse.

**Guiding rule:** Postgres `ALTER TYPE … ADD VALUE` is cheap and non-breaking; removing or renaming a value is not. Every enum below is therefore deliberately **minimal** — grow it later rather than guess wide now.

| Addition | Resolved shape |
|---|---|
| `care_rule_action_type` enum **(A19)** | `WATERING \| FERTILIZING \| REPOTTING \| PRUNING \| MISTING \| ROTATING \| INSPECTION`. Covers the wireframe icons and the `FINAL §10` Knowledge sections; `MISTING`/`ROTATING` follow from the `humidity_percent` and `light_direction` environment fields; `INSPECTION` is what a Health finding schedules. Validated at proposal ingest — out-of-vocabulary fails schema validation. |
| `system_event_type` enum **(A22)** | `PLANT_CREATED, PLANT_ARCHIVED, PLANT_RESTORED, PLANT_RENAMED, ENVIRONMENT_CHANGED, MAIN_IMAGE_CHANGED, REPOTTED, MOVED, PRUNED, CUSTOM_NOTE`. **Deliberately excludes** care events, health checks, identifications and plan versions — those have dedicated tables that the Phase 13 timeline merges, so putting them here would double-write every care action. The last four are user-logged out-of-band actions, distinct from the same action arriving via a scheduled task. |
| `species.normalized_name` **(A23)** | `normalize_scientific_name()`: NFKC → lowercase → collapse whitespace → strip authorship **only after a binomial pattern matches** (`Liebm.`, `(L.) Schott`) → retain genus + epithet + infraspecific rank (`var.`, `subsp.`). Unique index moves onto this column; first-seen `scientific_name` retained for display. Risk is one-directional (over-stripping merges distinct taxa), so every merge is logged. |
| `notification_preferences` defaults **(A27)** | Written by the same signup trigger as `profiles`: `email_enabled=true`, `preferred_time_local='08:00'`, `daily_digest=true` — matching the `UI_DESIGN_TOKENS` Settings wireframe. |
| `health_assessment_sources` table | Mirrors `knowledge_sources`: `id, health_assessment_id, source_class, title, url nullable, publisher, retrieved_at, citation_text, created_at`. Reuses `source_verification.py`. Row-immutable like its parent. Required by `FINAL §16`, which lists `sources` as an assessment output with no table to hold it. |
| `admin_audit_log` table | `id, admin_user_id, action, target_table, target_id, payload jsonb, created_at`. Append-only; admin-read; service-role write. `action` is **text, not an enum** — an enum would force a migration for every new admin action, and an audit log must never block a feature. |
| `notification_deliveries.dedupe_key text UNIQUE` | Format `{scope}:{identifier}:{local_date}` — `digest:{user_id}:2026-09-05`, `task:{care_task_id}:reminder`. The date component is the user's **local** date, so a timezone change cannot yield two sends on one local day. |
| `knowledge_versions.language`, `knowledge_drafts.language` | Decision 4; current-version uniqueness keys on `(species_id, language)`. |
| `identification_candidates.scientific_name`, `.common_name`; `species_id` nullable | Decision 2. |
| `plants.name` nullable | Until confirmation (A2). |

---

## Phases and PRs

### Phase 0 — Repository & engineering setup → **PR 1** ✅
Covers `PROGRESS §3`.

- GitHub repo; `main` (protected, PR + green CI) and `dev`; branch conventions; PR/issue templates; `README`, `CONTRIBUTING`, `.gitignore`.
- Python 3.12, **uv**, `pyproject.toml`. `ruff`, `mypy`, `pytest`(+asyncio, +cov), `pre-commit`.
- Package skeleton per `PROJECT_STRUCTURE §2`, **including the top-level `migrations/` directory [audit]** — see the note under Phase 2 for how it reconciles with Supabase CLI layout.
- `app/config/settings.py` — single `Settings`; **nothing else reads `os.environ`** (`STRUCTURE §6`); fail-fast with a named message per missing key (`SETUP §11`); Resend degrades to a null provider rather than failing boot.
- `app/config/logging.py` — JSON logs with the `DEPLOYMENT §9` field set; redaction filter for `password`, `*_key`, `authorization`, `token`.
- `app/common/enums.py` mirrors every DB enum; `app/common/errors.py` maps to error-envelope codes.
- `.env.example` — names only.
- CI: ruff → mypy → pytest on every PR.

**Verify:** `uv run ruff check . && uv run mypy app && uv run pytest`; removing a required var yields a readable named failure.

---

### Phase 1 — Supabase DEV project → **PR 2** ✅
Covers `PROGRESS §4 DEV`.

- Create `plantcare-dev` and `plantcare-prod` (prod empty until Phase 17).
- Supabase CLI linked; `config.toml` committed so `supabase db reset` reproduces schema locally.
- DEV Auth: email+password, **email confirmation ON**, reset redirect, session lifetime.
- Storage: private bucket `plant-images`.
- **[audit] Configure DEV AI provider credentials** (`PROGRESS §4` lists this separately) and verify a live call from the DEV environment only.
- `docs/ENVIRONMENTS.md` documenting every variable and its owning environment.

**Verify:** `supabase db reset`; repo grep finds no live key; local `.env` points at DEV only.

---

### Phase 2 — Database migrations + RLS → **PRs 3–6** ✅
Covers `PROGRESS §5`, `§6` (storage policies). Raw SQL via Supabase CLI.

> **[audit] Directory reconciliation.** `PROJECT_STRUCTURE §2` specifies a top-level `migrations/`, but the Supabase CLI requires `supabase/migrations/`. Resolution: `supabase/migrations/` is canonical (tooling constraint) and top-level `migrations/` holds a `README.md` pointing there. Record this deviation in `PROJECT_STRUCTURE.md` per `FINAL §37` rather than leaving the plan silently contradicting the spec.

**PR 3 — `0001_foundation.sql`**
- All `DATABASE_SCHEMA` enums; `pgcrypto`.
- `profiles`; trigger on `auth.users` insert → `profiles` row (`role='USER'`, tz default `Asia/Jerusalem`) **and a `notification_preferences` row (`email_enabled=true`, `preferred_time_local='08:00'`, `daily_digest=true`) [audit — A27]**.
- `public.is_admin() SECURITY DEFINER STABLE` — required, since an RLS policy on `profiles` reading `profiles.role` recurses.
- Shared `set_updated_at()`; `reject_mutation()`; `reject_content_mutation()` for `care_plan_versions`.
- RLS + policies on `profiles`, `notification_preferences`.

**PR 4 — `0002_plants.sql`, `0003_identification.sql`**
- `plants` (name nullable), `plant_environments` (`plant_id UNIQUE`), `plant_images`, `identifications`, `identification_candidates` (nullable `species_id`, raw names, `rank` CHECK 1–3).
- Owner-only RLS; child rows authorized through the owning plant.
- Indexes `idx_plants_user_status`, `idx_plants_user_health`, `idx_plant_images_plant`, `idx_identifications_plant`.

**PR 5 — `0004_knowledge.sql`**
- `species` (+ `normalized_name UNIQUE` **[audit]**), `knowledge_drafts` (+`language`), `knowledge_versions` (+`language`), `knowledge_sources`, `approved_sources`, `knowledge_reports`.
- `unique index on knowledge_versions(species_id, language) where is_current`.
- `reject_mutation()` on `knowledge_versions`, `knowledge_sources`.
- RLS: authenticated users read `where is_current`; **admin read-all policy via `is_admin()` [audit]** — without it the Phase 9 admin history endpoint is denied by the plan's own JWT-scoped client; all writes admin-only; users manage their own `knowledge_reports`.

**PR 6 — `0005_care.sql`, `0006_health.sql`, `0007_system.sql`, storage policies, seed**
- Care: `care_plans`, `care_plan_versions` (content-immutable trigger, status mutable), `care_rules` (`action_type` as the new `care_rule_action_type` enum **[audit]**), `care_tasks`, `care_events` (row-immutable).
- Health: `health_assessments` (row-immutable), `health_assessment_images` (composite PK), `health_observations`, `health_issues`, `health_recommendations`, **`health_assessment_sources` [audit]**.
- System: `agent_requests` (`UNIQUE (user_id, idempotency_key)`), `agent_executions`, `notification_deliveries` (+`dedupe_key UNIQUE`), `system_events` (+ `system_event_type` enum covering the ~11 timeline kinds in `FINAL §19` **[audit]**), `admin_audit_log`.
- Remaining indexes from `DATABASE_SCHEMA`.
- Storage RLS on `plant-images`: owner reads under `{auth.uid()}/…`; admin reads all.
- `seed.sql`: `approved_sources` starter set; 2 species with published Hebrew knowledge (required by the "existing species reuses Knowledge" journey).

**Verify:** `supabase db reset`; `tests/security/test_rls_smoke.py` (two real users, A↔B isolation); `tests/integration/test_immutability.py` asserts row-immutable tables reject UPDATE **and that `care_plan_versions.status` updates succeed while content updates raise [audit]**.

---

### Phase 3 — Auth & authorization → **PR 7** ✅
Covers `PROGRESS §7`.

- `infrastructure/supabase/client.py`: `anon_client()`, `user_client(token)`, `service_client()`.
- `api/dependencies.py`: `get_current_user` verifies the JWT and yields `(user_id, role, user_client)`; `require_admin` re-reads `profiles.role` server-side — **client-supplied `user_id`/`role` always ignored**.
- `GET/PATCH /v1/me` (`display_name`, `timezone`; `care_level` rejected).
- Register/login/verify/reset run in Streamlit against the Supabase **anon** client (A1).

**Verify:** anonymous → 401; forged `user_id` ignored; non-admin on admin route → 403; expired token → 401.

---

### Phase 4 — FastAPI structure → **PR 8** ✅
Covers `FINAL §28`.

- App factory; `/v1` mount; `request_id` middleware into logs and both envelopes; global handler → error envelope with **safe messages only**.
- `DataEnvelope`/`ErrorEnvelope` generics on every route.
- `/health`, `/ready`.
- Rate limiting on AI-triggering POSTs (A14).
- `repositories/base.py` — injected client, **no business rules** (`STRUCTURE §8`).

**Verify:** envelope-shape tests for 200/404/422; `/health` 200.

---

### Phase 5 — Streamlit shell → **PR 9** ✅
Covers `PROGRESS §8`, `UI_DESIGN_TOKENS`.

- `st.navigation`; CSS injecting `dir="rtl"`, `--pc-*` tokens verbatim, Noto Sans Hebrew/Assistant, 1280px max width, 16px card radius.
- Components: `app_shell`, `sidebar`, `page_header`, `status_badge`, `empty_state`, `confirmation_dialog` **[audit]**, loading/error primitives. `status_badge` always icon + Hebrew text; color never carries status alone.
- **[audit] Responsive + accessibility pass** (`UI_DESIGN_TOKENS`, `FINAL §33`): 3–4 cards/row desktop, 2 tablet, 1 mobile; keyboard-reachable controls, visible focus, meaningful alt text, no critical icon-only actions.
- **[audit] Automatic timezone detection** (`FINAL §15`): read the browser IANA zone on first login via a small JS component, write it to `profiles.timezone` if unset, always overridable in Settings.
- `state/session.py`, `state/api_client.py` (Bearer injection, error-code → Hebrew message).
- Pages: auth, `home`, `my_plants`, `add_plant`, `plant_dashboard`, `settings`, `admin` — stubs with real empty/loading/error states. Admin nav hidden unless `role == ADMIN` (still 403-enforced server-side).
- Review rule: no SQL, no Supabase business calls, no prompts, no authorization in `ui/` (`STRUCTURE §7`).

**Verify:** manual register → verify → login → empty Home; `AppTest` smoke test; admin nav absent for USER; keyboard-only traversal of the shell.

---

### Phase 6 — Image pipeline → **PR 10** ✅
Covers `PROGRESS §6`, `FINAL §20`.

- `domain/services/images.py`: validate by **decoding with Pillow**, ≤10 MB, JPG/JPEG/PNG/WEBP; strip EXIF; honor orientation. Processed = 1600px long edge @ q85; thumbnail = 400px (A6).
- `infrastructure/storage/supabase_storage.py`: `plant-images/{user_id}/{plant_id}/{gallery|identification|health}/`; **5-minute signed URLs** — bucket stays private.
- `POST /v1/plants/{id}/images`; `DELETE …/{image_id}` → if `ai_used` hide (`user_visible=false`, `retention_reason`) else remove. **AI-used images are never physically deleted.**
- **[audit] `plants.main_image_id`**: first successful gallery upload sets it; a "set as main image" action on the gallery changes it; archiving never clears it.
- `ui/components/image_uploader.py` with preview/remove/add and guidance.

**Verify:** matrix — oversize, unsupported type, `.jpg` that is a PDF, corrupt bytes, 4-image cap; integration upload to DEV; user B cannot fetch user A's object.

---

### Phase 7 — Add Plant vertical slice → **PR 11** ✅
Covers `PROGRESS §10`, `§11` (non-AI half).

- `POST /v1/plants` → `PENDING_IDENTIFICATION`; `GET /v1/plants?status=&health_status=&q=`; `GET /v1/plants/{id}`; `PATCH`; `archive`; `restore`. No manual species selection.
- `domain/rules/plant_lifecycle.py` — explicit transition table; invalid transitions raise.
- `PUT/GET /v1/plants/{id}/environment`; every update also writes `system_events ENVIRONMENT_CHANGED` with old/new payload.
- UI: Add Plant step 1; My Plants grid + `plant_card`; search; health filter; empty/loading states.

**Verify:** full transition matrix incl. rejections; API tests; `AppTest` for grid + empty state.

---

### Phase 8 — AI Gateway + Identification Agent → **PRs 12–13** — ✅
Covers `PROGRESS §19`, `§11` (AI half).

**PR 12 — AI infrastructure**
- `AIProvider` protocol (`text_generation`, `vision_analysis`, `structured_output`, `verify_wikipedia_page`, `retrieve_source`); `AnthropicProvider` (consult the `claude-api` skill for current model IDs) + `MockProvider`.
- `gateway.py` — per-agent model from `IDENTIFICATION_MODEL`/`KNOWLEDGE_MODEL`/`CARE_MODEL`/`HEALTH_MODEL`; timeouts; **schema validation with at most 2 retries** then graceful failure; writes `agent_executions` via an explicit allow-list so **no chain-of-thought is persisted**. **[audit] plant ID** is required by `FINAL §23` and is reachable via `agent_request_id → agent_requests.plant_id`; the admin view joins it — record that resolution in the spec.
- `prompts/<agent>/<name>.v001.md` loader; loaded version lands in `agent_executions.prompt_version`.
- `agents/base.py` — agents get a pre-assembled context object and the gateway; never repositories, never each other (import-boundary test lands here).
- `agent_requests` lifecycle; `GET /v1/agent-requests/{id}` with stage (`IMAGES_RECEIVED → CONTEXT_LOADED → ANALYZING → PREPARING_RESULT → COMPLETE`).
- `AgentExecutor` interface + `BackgroundTasksExecutor` — the 202/poll pattern of `FINAL §24`, swappable for a worker **without changing agent contracts**.
- **[audit] `Idempotency-Key` semantics (A24):** identical payload replays the original `202` with the same `agent_request_id`; same key + different payload → `409`.

**PR 13 — Identification Agent**
- `IdentificationAgent.identify()` → primary + up to 2 alternatives, confidence, image quality, `request_more_photos`; `SUCCESS | NEEDS_MORE_INFORMATION | FAILED`. **Does not mutate `plants`.**
- **[audit] Confidence (A18):** `confidence_score` is 0.0–1.0; `confidence_level` derived **in Python** (HIGH ≥ 0.85, MEDIUM ≥ 0.60, else LOW), never taken from the model.
- `verify_wikipedia_page()` → `GET https://{locale}.wikipedia.org/api/rest_v1/page/summary/{title}`; URL returned **only** on HTTP 200 with a matching title. No URL ever comes from model output.
- **[audit] Species normalization (A23):** pure `normalize_scientific_name()` (strip authorship, collapse whitespace, fixed casing) feeding `species.normalized_name`; the upsert keys on it, so `Monstera deliciosa` / `monstera deliciosa` / `Monstera deliciosa Liebm.` resolve to one lineage.
- `POST /v1/plants/{id}/identification-runs` → 202; `GET /v1/identifications/{id}`; `POST …/confirm {candidate_id}`; `POST …/correct` (A13).
- Confirm workflow: upsert species → published knowledge for `(species_id, language)`? **yes** → `ACTIVE` + queued `INITIAL_PLAN` proposal; **no** → draft + queued research + `KNOWLEDGE_PENDING`.
- **[audit] Re-identification of an already-ACTIVE plant (A21):** the plant **stays `ACTIVE` on its existing plan** while the new species' draft runs — it does not regress to `KNOWLEDGE_PENDING` and live tasks are not cancelled; a `RE_IDENTIFICATION` proposal is raised on publication.
- UI: processing stages; confirmation screen with alternatives and Wikipedia link when present.

**Verify:** with `MockProvider` — valid accepted; malformed JSON / schema-invalid / missing-field each retried exactly twice then `FAILED`; confidence thresholds; **failure asserts `plants.species_id` is *unchanged* [audit — was wrongly asserted NULL, which is false on re-identification]**; identification history retained.

---

### Phase 9 — Species / Knowledge workflow → **PRs 14–15** — ✅
Covers `PROGRESS §12`.

**PR 14 — Knowledge Agent + deterministic source verification**
- `KnowledgeAgent.generate()` → all 14 sections in Hebrew. **Never publishes.**
- `retrieve_source()` uses provider-native search/grounding (`FINAL §23` resolved).
- **`domain/services/source_verification.py` — authoritative, in Python:** fetch each returned URL, require HTTP 200, check relevance, classify `APPROVED` on enabled-domain match else `EXTERNAL_UNAPPROVED`; unsupported claims → `AI_GENERATED_REQUIRES_VERIFICATION`. **No `knowledge_sources` row from unverified model output.**
- **[audit] `domain/rules/knowledge_lifecycle.py`** — explicit `knowledge_draft_status` transition table with its own unit tests (`TESTING §3` names "knowledge status transitions"; the first draft covered only plant lifecycle).
- Research runs on the 202/poll executor.

**PR 15 — Admin review, publication, fan-out**
- Admin draft routes (list/detail/approve/reject/retry), `knowledge-versions/{species_id}`, `approved-sources` CRUD + disable.
- Approval in one RPC: insert immutable version (`version_number = max+1`), flip `is_current`, write `admin_audit_log`.
- **Fan-out on publish:** every `KNOWLEDGE_PENDING` plant for that species → `ACTIVE` + queued `INITIAL_PLAN` proposal (A4).
- **[audit] Reject / FAILED path (A17):** plants stay `KNOWLEDGE_PENDING` with an explicit "in review" message; the draft remains retriable so the fan-out eventually fires. Plants never strand silently.
- `GET /v1/species/{id}/knowledge`; `POST /v1/species/{id}/knowledge-reports`.
- Admin UI: Drafts / Published Knowledge / Sources with source inspection.

**Verify:** UPDATE/DELETE on a published version raises; concurrent publish cannot yield two `is_current` rows; USER role denied every knowledge write; **admin can read non-current versions [audit]**; draft-status transition tests.

---

### Phase 10 — Care Agent + Care Plan → **PR 16** — ✅
Covers `PROGRESS §13`.

- `orchestration/services/care_context.py` assembles knowledge version + plant + environment + current health + health history + care history + preferences. **The agent never queries the DB.**
- `CareAgent.generate_plan()` → `professional_recommendations` + proposed `care_rules`.
- **[audit] `action_type` is a closed enum (A19):** `WATERING | FERTILIZING | REPOTTING | PRUNING | MISTING | ROTATING | INSPECTION`; an out-of-vocabulary value fails schema validation at ingest.
- **[audit] `domain/rules/care_rule_validation.py`** — interval bounds, action type, time format, weekday coherence, validated separately from the recurrence math (`FINAL §34` "Care Rule validation").
- **[audit] Missing-context handling (A20):** MVP implements the **qualify** branch only — a `missing_context[]` block rendered on the proposal card. There is no interactive question/answer loop, because no status, table or endpoint exists to carry one; record this scoping decision per `FINAL §37`.
- Endpoints: `GET /v1/plants/{id}/care-plan` **[audit]**, `POST …/care-plan/proposals {reason}` → 202, `GET …/proposals`, `POST /v1/care-plan-proposals/{id}/{approve,reject}`, `POST /v1/care-plan-versions/{id}/operational-adjustment`, `POST /v1/plants/{id}/care-plan/adjustment-proposals {health_assessment_id, reason}` **[audit]**.
- Operational adjustment creates a new version with `change_summary`, copying `professional_recommendations` **verbatim**.
- Environment change and health findings produce **proposals only**.
- Activation transaction: new → `ACTIVE`, previous → `SUPERSEDED`, outstanding `PENDING` tasks from the old version → `CANCELLED` (A5).
- UI `proposal_card` per the wireframe.

**Verify:** operational adjustment cannot alter `professional_recommendations`; version chain (v1 ACTIVE → v2 ACTIVE, v1 SUPERSEDED, v1 content intact); AI failure leaves no version row; care-rule validation matrix.

---

### Phase 11 — Scheduler, Care Tasks & Home Dashboard → **PRs 17–18** — ✅
Covers `PROGRESS §14` and **`§9` [audit — the Home Dashboard was absent from the first draft entirely]**.

**PR 17 — Deterministic scheduling**
- `domain/rules/recurrence.py` — pure, no I/O, no LLM, no `datetime.now()` (time is a parameter):
  - `next_due(rule, anchor_utc, tz)` from `interval_days` + `preferred_time_local` via `zoneinfo`; `preferred_weekday` honored **only when `interval_days % 7 == 0`** (A7).
  - **DONE anchors on actual `event_at`; SKIP anchors on original `due_at`** (A8).
- Materialization: at most **one PENDING task per active rule**, 14-day horizon, idempotent.
- Overdue: past due → `OVERDUE` + `overdue_since`; after `min(interval_days, 14)` days → `MISSED` event, task `CANCELLED`, next recurrence still scheduled (A9).
- `GET /v1/care-tasks?date=today&status=pending`; `POST /v1/care-tasks/{id}/{done,skip}` → immutable `care_event` + advance; **duplicate → 409**.
- `GET /v1/dashboard` — one aggregate call: `today_care`, `plants_needing_attention`, `my_plants`, `counts`.
- **[audit] Overdue summarization (`FINAL §13`, `PROGRESS §14`):** `summarize_overdue(tasks)` groups multiple overdue items into one summary line per plant, consumed by both the dashboard and the digest.
- `POST /v1/internal/tick` — shared secret, service-role; materialize + overdue sweep.

**PR 18 — Home Dashboard [audit]**
All twelve `PROGRESS §9` items against the `UI_DESIGN_TOKENS` "Home Dashboard" wireframe: personalized greeting, plant count, today's-task count, needs-attention count, Today's Care with Done/Skip, **upcoming care**, Plants Needing Attention, **Quick Health Check**, My Plants preview, Add Plant CTA, **all-caught-up state**, loading/error states. Adds `ui/components/care_task_card.py` **[audit]**. Renders from the single `GET /v1/dashboard` call.

**Verify:** table-driven recurrence tests including an Asia/Jerusalem DST crossing both directions; overdue-cap proof; duplicate `done` → 409; done-vs-skip anchoring; tick is idempotent; `AppTest` for Home in populated, empty and all-caught-up states.

---

### Phase 12 — Notifications → **PR 19** — ✅
Covers `PROGRESS §15`, `FINAL §14, §30`.

- `notifications/service.py` → `EmailProvider` protocol → `ResendProvider` + `NullProvider` (CI default; tests never send mail).
- `GET/PUT /v1/notification-preferences`; `GET /v1/notification-deliveries`.
- Send window = user's `preferred_time_local` in their timezone (A10: care rule governs *due* time, notification preference governs *send* time).
- **[audit] `daily_digest` is honored as a preference (contradiction fix):** `true` → one digest email; `false` → per-task emails. The first draft chose by task count, which made the user's setting inert.
- **Duplicate prevention via `dedupe_key`** (`"{user_id}:{local_date}:digest"` / `"task:{id}:reminder"`), unique-indexed — a duplicate insert fails **before** any provider call.
- In-app reminders and the overdue summary render from the same task query as the dashboard.

**Verify:** tick twice → exactly one delivery row and one provider call; a user in another timezone receives at their local 08:00; `daily_digest=false` yields per-task sends; provider failure records `FAILED` without losing the task.

---

### Phase 13 — Plant Dashboard + History → **PR 20** — ✅
Covers `PROGRESS §17`, `FINAL §17, §19`.

- `GET /v1/plants/{id}` — full view model (gallery + signed URLs, species, health, upcoming tasks, active plan, latest assessment + trend, environment).
- Timeline merged from `system_events` + `care_events` + `identifications` + `health_assessments` + `care_plan_versions`, `created_at desc`, paginated, keyed on the **`system_event_type` enum [audit — A22]** covering all ~11 kinds in `FINAL §19`. Append-only; corrections are corrective entries.
- Manual/custom history event endpoint (repot, move, prune, note).
- UI per the wireframe: hero image, action row, upcoming-care and care-plan cards, health section, timeline, Report Knowledge Error, archive/restore.

**Verify:** ordering and pagination; archived plant absent from `status=ACTIVE` but history intact and restorable.

---

### Phase 14 — Health Agent → **PR 21** — ✅
Covers `PROGRESS §16`, `FINAL §16`.

- `HealthAgent.assess()`; **1–4 images enforced server-side**, ≥1 required, images must belong to the plant/user.
- **[audit] Image-quality gate (A25):** pure `assess_image_quality()` on minimum decoded dimensions plus a blur floor, run **before** the model call; it **warns rather than hard-rejects**, so weak evidence still reaches the documented `UNKNOWN` outcome instead of being blocked.
- One transaction: `health_assessments` + images + observations + issues + recommendations + **`health_assessment_sources` [audit — `FINAL §16` requires `sources`; the first draft and the schema both omitted it]**, then update `plants.current_health_status`. Prior assessments never touched.
- Insufficient evidence → `UNKNOWN` + `insufficient_information_reason`, still saved.
- **Trend computed in Python** from prior statuses (A11); never claimed without sufficient history.
- Possible-issue language throughout ("ייתכן", "סימנים שעשויים להעיד") — never a definitive diagnosis.
- `requires_care_plan_adjustment` → `HEALTH_DRIVEN` proposal via the Care Agent's `adjustment-proposals` route. The Health Agent cannot touch the plan.
- **[audit] Spec conflict (A28):** `FINAL §16`'s flow diagram orders "proposal → approval → assessment saved", contradicting its own prose ("every successful Health Check updates status"). The plan follows the **prose** — the assessment is saved on every successful check regardless of any proposal — and the diagram is corrected in the spec per `FINAL §37`.
- Endpoints `GET /v1/health-assessments/{id}` and `GET /v1/plants/{id}/health-history` **[audit]**.
- UI: health check upload + note, `health_card` **[audit]**, results per the wireframe.

**Verify:** 0 and 5 images both rejected; sparse evidence → `UNKNOWN`; failure leaves `current_health_status` unchanged and writes no row; prior assessments byte-identical; trend unit tests; quality gate warns without blocking.

---

### Phase 15 — Admin Panel completion → **PR 22** — ✅
Covers `PROGRESS §18`, `FINAL §29`.

- Admin dashboard; AI monitoring over `agent_executions`/`agent_requests` exposing model, prompt version, duration, tokens, cost — **never chain-of-thought**; `knowledge-reports` review → trigger draft; `notification-deliveries`; audit-log view.
- Admin access to retained AI-used hidden images.
- Account anonymization: disable access, clear identifying fields, set `anonymized_at`, preserve history, Admin-only. **[audit] Initiation path (A26):** MVP has no self-service deletion control; deletion is an out-of-band request executed by an admin — record that scoping decision in `FINAL §21` rather than leaving it silently unreachable.
- Every consequential admin action writes `admin_audit_log`.

**Verify:** parametrized test over the admin router table asserting 403 for a USER on **every** route; one audit row per approve/reject/disable/anonymize.

---

### Phase 16 — Integration & E2E testing → **PR 23** — ✅
Covers `PROGRESS §20`, `TESTING`.

- `tests/e2e/` for the eight journeys in `PROGRESS §20` **plus the Knowledge-error reporting journey from `TESTING_STRATEGY §9` [audit]** (user reports → admin sees → draft/research → new published version) — nine total, driven through the API with `MockProvider` fixtures (valid, malformed, timeout, schema-invalid). **No test depends on a live LLM.**
- `tests/security/test_rls_matrix.py` — parametrized over every user-owned table × {read own, read other, write own, write other, anonymous}.
- `tests/agents/test_no_authoritative_record.py` — one case per agent.
- CI: unit + api + agents on every PR; integration + e2e against DEV on merge to `dev`; full suite green before `main`.

**Verify:** `uv run pytest -m "not live"` green; coverage on `app/domain` and `app/orchestration`.

---

### Phase 17 — Production deployment → **PR 24** — next
Covers `PROGRESS §21, §22`, `DEPLOYMENT`.

- Dockerfiles; Railway services `plantcare-api`, `plantcare-ui`, plus a **cron service calling `/internal/tick`** every 15 min; private networking between UI and API.
- PROD Supabase provisioned; **PROD Auth and PROD Storage configured as distinct steps [audit — `PROGRESS §4` lists them separately]**; migrations applied through a reviewed CI step, never manually.
- Secrets only in Railway's manager; backups; health checks.
- **[audit] Storage operations monitoring (`DEPLOYMENT §7`)**: upload failures, invalid files, processing failures, storage growth, access-denied events.
- Alerts — **all seven** from `DEPLOYMENT §10` including **storage processing failure [audit, previously dropped]**: sustained 5xx, repeated AI failures, migration failure, DB connectivity, AI cost spike, notification-provider failure, storage processing failure.
- `docs/RUNBOOK.md`: deploy, rollback (previous known-good image; forward-fix migrations, never blind reversal), incident procedure.
- Walk `PROGRESS §22` item by item.

**Verify:** DEV deploy → smoke journey → promote to `main`; PROD credentials absent from every local `.env`; deliberately break a deploy and roll back.

---

## Spec ambiguities — flagged, not guessed

A1–A16 from the first draft; **A17–A28 added by the audit**. **A19, A22, A23 and A27 are now resolved** (see "Schema additions" above) because they land in Phase 2 migrations, which are expensive to reverse — **24 remain open**, all with a working default that gets re-surfaced in the PR that implements it. A1–A5, A17 and A21 should be settled before their phase starts.

| # | Ambiguity | Recommendation | Due |
|---|---|---|---|
| A1 | No `/v1/auth/*` endpoints, but the UI must register/login/reset | Streamlit uses the Supabase anon client for auth only; FastAPI stays token-consuming | P3 |
| A2 | `plants.name` required before the user has named the plant | Nullable; required at confirmation | P2 |
| ~~A3~~ | Nothing says the initial Care Plan proposal is auto-generated | **✅ RESOLVED in PR 16** — an `INITIAL_PLAN` proposal is queued when a plant becomes ACTIVE, including via the knowledge fan-out. Deferred from PR 15 until the Care Agent existed, since a QUEUED request nothing could execute would have looked like a stuck job | — |
| ~~A4~~ | Fate of `KNOWLEDGE_PENDING` plants on publish | **✅ RESOLVED in PR 15** — publication moves every `KNOWLEDGE_PENDING` plant of that species to `ACTIVE`, inside the publishing transaction. `ARCHIVED` and already-`ACTIVE` plants are deliberately untouched. The care proposal follows in PR 16 | — |
| ~~A5~~ | Outstanding `PENDING` tasks when a version supersedes | **✅ RESOLVED in PR 16** — cancelled inside the activation transaction. DONE, SKIPPED and OVERDUE are untouched: they record what happened, and a new plan does not change the past | — |
| A6 | Processed/thumbnail dimensions unspecified | 1600px @ q85; 400px thumb | P6 |
| ~~A7~~ | `preferred_weekday` vs non-multiple-of-7 intervals | **✅ RESOLVED in PRs 16–17** — a CHECK constraint refuses the combination at write time, the rule validator refuses it before that, and `next_due()` ignores it if one ever arrived | — |
| ~~A8~~ | Next-due anchor after a late completion | **✅ RESOLVED in PR 17** — DONE anchors on `event_at`, SKIPPED on the original `due_at`, and MISSED on when it was written off. That third case was not in the plan and is the one that bites: anchoring a miss on its due date writes a MISSED event on every tick forever | — |
| ~~A9~~ | What writes `MISSED`, and when overdue stops being actionable | **✅ RESOLVED in PR 17** — the overdue sweep writes it after `min(interval_days, 14)` days and cancels the task; the next recurrence is still scheduled | — |
| ~~A10~~ | Two competing "preferred time" fields | **✅ RESOLVED in PR 19** — the rule's time is when a task is *due*, the preference's is when we may *write*. They answer different questions, and the Settings help text says which is which | — |
| ~~A11~~ | Who computes `trend` | **✅ RESOLVED in PR 21** — Python, comparing the new status with the previous *readable* one. `UNKNOWN` assessments are skipped rather than counted as a low point, or every blurred photograph would report a decline | — |
| A12 | Idempotency column and audit table both mandated, neither defined | Add `dedupe_key`, `admin_audit_log` | P2 |
| A13 | `POST …/correct` has no request body | `{candidate_id?, scientific_name?, note}`; history only | P8 |
| ~~A14~~ | "Rate-limit AI endpoints" with no numbers | **✅ RESOLVED in PR 8** — 10/user/hour, 3/min, configurable; keyed on the *verified* user id via a dependency rather than slowapi, whose decorator resolves its key before auth runs and would have keyed on an unverified `sub` | — |
| A15 | No E2E tooling named for Streamlit | httpx at API level + `AppTest`; no browser driver | P16 |
| ~~A16~~ | `knowledge_versions.content` has no field schema | **✅ RESOLVED in PR 14** — Pydantic `KnowledgeContent`: thirteen required prose sections each carrying its own confidence, sources recorded beside them rather than inside them, validated at draft and again at publish | — |
| ~~A17~~ | Fate of `KNOWLEDGE_PENDING` plants when a draft is **rejected or FAILED** — A4 covered only success, so plants strand | **✅ RESOLVED in PRs 14–15** — the draft lifecycle makes `REJECTED → RESEARCHING` and `FAILED → RESEARCHING` legal and `APPROVED` terminal; rejection changes no plant, and the retry route is the path out | — |
| ~~A18~~ | `confidence_score` has no scale and no thresholds mapping to `confidence_level` | **✅ RESOLVED in PR 13** — 0.0–1.0, derived in Python; `HIGH_CONFIDENCE`/`MEDIUM_CONFIDENCE` in the identification contract, never taken from the model | — |
| ~~A19~~ | `care_rules.action_type` untyped | **✅ RESOLVED** — closed enum, see Schema additions | — |
| ~~A20~~ | Spec says agents "ask the user" for missing context, but no status/table/endpoint can hold a question | **✅ RESOLVED in PR 16** — the qualify branch only. `missing_context[]` renders on the card as information, never as a question, and the plan is produced regardless. Pot size and drainage are not even columns on `plant_environments`, which is why the agent names them | — |
| ~~A21~~ | Re-identifying an **ACTIVE** plant onto a species with no published Knowledge has no defined outcome | **✅ RESOLVED in PR 13** — the plant stays ACTIVE on its existing plan while the new species is researched; live tasks are not cancelled | — |
| ~~A22~~ | `system_events.event_type` names one value | **✅ RESOLVED** — closed enum excluding dedicated-table kinds, see Schema additions | — |
| ~~A23~~ | `species` upsert has no normalization rule | **✅ RESOLVED** — `normalize_scientific_name()` + `normalized_name` index, see Schema additions | — |
| ~~A24~~ | Repeated `Idempotency-Key` behavior undefined though `TESTING §8` demands tests | **✅ RESOLVED in PR 13** — an identical payload replays the original 202 with the same request id and makes no second model call; asserted end to end in PR 23 | — |
| ~~A25~~ | Health image-quality gate undefined in kind and threshold | **✅ RESOLVED in PR 21** — decoded dimensions, contrast and a focus score, all measured rather than guessed. It **warns and never blocks**: §16 already defines `UNKNOWN` as the outcome for weak evidence, and refusing the upload would put it out of reach | — |
| ~~A26~~ | Account anonymization has no initiating path from the user | **✅ RESOLVED in PR 22** — an out-of-band request an administrator carries out, which is why the reason is required: it is the only record of why the account was closed | — |
| ~~A27~~ | No `notification_preferences` row created for a new user | **✅ RESOLVED** — signup trigger writes it, see Schema additions | — |
| ~~A28~~ | `FINAL §16` flow diagram contradicts its own prose on when an assessment is saved | **✅ RESOLVED in PR 21** — the prose wins and the diagram is corrected in the spec. The original order would have recorded a check only when the user agreed to a care change, and never when they declined one | — |

---

## Sizing and critical path

Rough relative effort, to make the shape of the schedule visible. **Phases 2 and 8 together are roughly a third of the build** — they are the two places to slow down and review carefully.

| Phase | PRs | Size | Notes |
|---|---|---|---|
| 0 Repo/tooling | 1 | S | Mechanical, but everything downstream inherits it |
| 1 Supabase DEV | 2 | S | Mostly console work; little code |
| **2 Migrations + RLS** | **3–6** | **XL** | The single largest phase. PR 6 alone touches 13 tables. Every later phase depends on it |
| 3 Auth | 7 | M | PR 7 is where the user-JWT/RLS assumption gets proven |
| 4 API structure | 8 | S | Thin; unblocks everything after it |
| 5 Streamlit shell | 9 | M | RTL/tokens/responsive/a11y is more work than it looks |
| 6 Image pipeline | 10 | M | Self-contained; parallelizable with 7 |
| 7 Add Plant slice | 11 | M | First end-to-end vertical; validates the layering |
| **8 AI Gateway + Identification** | **12–13** | **XL** | PR 12 is foundational for Phases 9, 10 and 14 — the second bottleneck |
| 9 Knowledge workflow | 14–15 | L | Source verification is the hard part, not the agent |
| 10 Care Agent | 16 | L | Depends on 8 and 9 |
| 11 Scheduler + Home | 17–18 | L | PR 17 is pure logic and heavily tested; PR 18 is UI |
| 12 Notifications | 19 | M | Small once 11 exists |
| 13 Plant Dashboard | 20 | M | Mostly assembly of existing pieces |
| 14 Health Agent | 21 | L | Structurally parallel to Phase 10 |
| 15 Admin Panel | 22 | L | Broad but shallow; lots of small screens |
| 16 Testing | 23 | M | Continuous throughout; this PR closes gaps |
| 17 Deployment | 24 | M | Front-load the Railway spike if hosting is unfamiliar |

**Critical path:** `0 → 1 → 2 → 3 → 4 → 8(PR 12) → {9, 10, 14}`. Phases 5, 6 and 7 can proceed in parallel with 3–4 once migrations land. Phases 10 and 14 are independent of each other and both wait on PR 12. Nothing after Phase 2 can start until Phase 2 is stable, which is the strongest argument for reviewing PRs 3–6 slowly.

**Two assumptions get proven early rather than spiked separately:** that `supabase-py` applies RLS with a per-request user JWT (PR 7), and that Streamlit can read the browser's IANA timezone (PR 9). Both are load-bearing for decisions 1 and 4; if either fails, it surfaces before any agent work begins.

---

## Verification (end to end)

1. `uv run ruff check . && uv run mypy app && uv run pytest -m "not live"` — green.
2. `supabase db reset && uv run pytest tests/security` — RLS matrix and immutability triggers pass against a real DEV database.
3. Run API + UI and walk the `FINAL §34` smoke path in the browser: register → verify → login → add plant → upload → identify → confirm → knowledge → approve plan → today's task → done → health check → status → history.
4. Repeat for a species with **no** published knowledge: `KNOWLEDGE_PENDING` → admin approves → plant flips `ACTIVE` with a proposal waiting. Then repeat with a **rejected** draft and confirm the plant does not strand (A17).
5. `POST /v1/internal/tick` twice — exactly one `notification_deliveries` row and one Resend call. Flip `daily_digest` and confirm per-task sends.
6. As a second user, attempt to read user A's plant, image URL and care task — denied at the database, not just the API.
7. Point `AI_PROVIDER` at the failing mock; re-run add-plant and health-check — no `identifications`, `care_plan_versions` or `health_assessments` row created, graceful Hebrew error shown.
8. Walk the `PROGRESS §22` MVP release checklist.

---

## Working rules for every PR

Per `FINAL §37`: any new requirement or deviation is (1) added to the spec, (2) classified MVP or Future, (3) recorded with rationale, (4) reflected in `DEVELOPMENT_PROGRESS.md` checkboxes **in the same PR**, and (5) never silently overwrites an architectural decision. Unresolved choices are marked `[~]` pending, not invented.

**Spec documents this plan will amend:** `DATABASE_SCHEMA_V1.md` (9 additions), `API_CONTRACTS_V1.md` (confirm payload, correct payload, idempotency semantics), `PROJECT_STRUCTURE.md` (migrations directory), `PlantCare_AI_FINAL_SPECIFICATION_V1.md` (§16 diagram fix, §21 deletion path, §23 plant-ID resolution), `PlantCare_AI_DEVELOPMENT_PROGRESS_V1.md` (checkboxes, continuously).

---

## Amendments during implementation

Per `FINAL_SPECIFICATION §37`, no deviation from the plan or the specification is
made silently. Each entry below is also recorded in the spec document it affects.

### Deviations from this plan

| PR | Change | Reason |
|---|---|---|
| 3 | `notification_preferences` created in the foundation migration, not with the notification tables | The signup trigger populates it (A27); a user must never exist without preferences, or `GET /v1/notification-preferences` and the scheduler tick are undefined for a new account |
| 4 | `species` moved into the plants migration, not the knowledge one | `plants`, `identifications` and `identification_candidates` all reference it; leaving it later meant three forward-declared foreign keys. Only the taxonomy entity moved |
| 5 | `knowledge_versions` is **content**-immutable, not row-immutable | `is_current` must flip when a newer version publishes. A row-immutable table could never demote its predecessor, making publication impossible. Same correction the audit made for `care_plan_versions` — repeated here, and caught only when the SQL had to run |
| 8 | Rate limiting is a dependency, not slowapi | slowapi resolves its key before the dependency graph runs, so per-user keying would read `sub` from an **unverified** token. A forged `sub` would let a caller choose which bucket to spend |
| 9 | Pages live in `app_pages/`, not `pages/` | Streamlit reserves `pages/` beside the entry script for legacy auto-discovery, which competes with explicit `st.navigation` |
| 9 | Design tokens in `.streamlit/config.toml`, not injected CSS | Streamlit theming covers colours, fonts, radii and the heading scale natively. CSS written against Streamlit's internal class names breaks silently on upgrade, so the custom-CSS surface is now RTL only — the one thing theming cannot express |
| 9 | Timezone detection needs no JS component | `st.context.timezone` exposes the browser's IANA zone natively (`FINAL §15`) |
| 10 | Image endpoints deferred to PR 11 | `POST /v1/plants/{id}/images` needs a plant to exist, and plants CRUD is PR 11 |
| 12 | `verify_wikipedia_page()` and `retrieve_source()` are not on the `AIProvider` protocol | Neither is a model call. Putting them there would force every provider to carry identical HTTP code, and would blur the line between what the model said and what we verified — the line `§23` draws when it makes verification authoritative |
| 13 | The agent returns raw names; `species` rows are created at **confirm**, not at identification | Materialising a species per candidate would let every low-confidence hallucinated binomial permanently enter a taxonomy table shared by all users, and two of three candidates are wrong by construction. Recorded in `API_CONTRACTS`, which specified `confirmed_species_id` |
| 13 | The model is never asked for a Wikipedia URL | There is then none to discard. The link is resolved and verified separately against Wikipedia's REST API — and a 200 is not enough, since Wikipedia redirects generously: the returned title must actually name the same species. A confident link to the wrong plant is worse than no link |
| 13 | `IdentificationAgent` re-sorts and de-duplicates its own candidates, and downgrades an empty `SUCCESS` | The model is asked for descending confidence and usually obliges, but a UI that trusts `candidates[0]` must not depend on that. A `SUCCESS` carrying nothing would render an empty confirmation screen inviting the user to confirm air |
| 14 | `source_verification.py` defines its own `SourceClaim` input rather than taking the agent's `ProposedSource` | The domain must not depend on an agent, and PR 21 verifies health-assessment sources through this same module with a different agent contract on the other side. Importing one agent's Pydantic class to cite a web page would have made the second caller depend on the first agent's package |
| 14 | A draft's sources live inside `knowledge_drafts.content`, not in `knowledge_sources` | Those rows reference a *published version* and are immutable. Writing them at draft time would freeze a draft's provenance while the draft is still being revised; they are created at approval |
| 14 | A research failure raises rather than returning a degraded result, unlike identification | There is no useful partial answer to a research request. An empty draft is not knowledge, and swallowing the error would leave an administrator reviewing a blank one instead of a draft marked FAILED and retriable |
| 14 | RUF001 (ambiguous-unicode) is configured with the Hebrew alphabet allowed rather than worked around | The rule fires on ordinary Hebrew product copy, and only on *some* letters — making it a lottery on wording rather than a check on anything. Left enabled for its real purpose (a Cyrillic lookalike in an identifier) with Hebrew excluded, so nobody reaches for a worse Hebrew word to satisfy a linter |
| 15 | Publication is one SQL function, not a sequence of API calls | The partial unique index on `(species_id, language) where is_current` forces demote-then-insert, and a failure between the two would leave a species with **no** current version — every plant of that species unable to find its knowledge. Six round trips have no transaction around them; one function does |
| 15 | `publish_knowledge_draft()` is `SECURITY DEFINER`, guarded by `is_admin()` inside | The fan-out updates *other users'* plants, which no admin JWT can do through RLS — and should not be able to in general. The privilege is granted to the one operation rather than to the person |
| 15 | The fan-out does **not** queue the `INITIAL_PLAN` care proposal A3 calls for | The Care Agent lands in PR 16. A `QUEUED` agent request nothing can execute is worse than none: it would sit in the admin monitoring view forever looking like a stuck job. PR 16 adds it at this same point and backfills plants released before it existed |
| 15 | An approved source's `domain` is not editable | Changing it would silently reclassify every `knowledge_sources` row pointing at it — rows that are immutable precisely so a published version's provenance cannot be rewritten. A different domain is a different source |
| 16 | An implausible rule is dropped, and the plan keeps its other rules | A rule that reaches the database fails a CHECK and takes the whole insert with it, losing six good rules alongside one bad one. A plan with three sensible rules is worth keeping; a plan with none is a failure, and is treated as one |
| 16 | An operational adjustment makes no model call at all | It is a deterministic edit of parameters. Routing it through the agent would cost money *and* give the model the chance to rewrite advice the user is explicitly not allowed to edit |
| 16 | An adjustment produces a PROPOSED version the user must still approve | The version chain is the audit trail. Letting an operational tweak be the one way to change the active plan without saying yes to it would put a hole in it |
| 16 | Only one open proposal per plant | Two is a choice the user did not ask to make, and approving one would silently orphan the other |
| 16 | `activate_care_plan_version()` is SECURITY **INVOKER**, unlike the knowledge publisher | Everything it touches belongs to the calling user, so RLS should apply in full. A definer function would bypass exactly the checks that make it safe — the knowledge one is a definer precisely because it writes *other* users' rows |
| 17 | Recurrence does day arithmetic in the user's timezone rather than adding seconds to a UTC instant | The obvious implementation passes every test except the two DST ones, and then silently moves every reminder by an hour twice a year. Israel changes its clocks, and Asia/Jerusalem is the MVP default |
| 17 | A newly activated rule uses `first_due()`, not `next_due()` from activation | A user who approves a nine-day watering plan should not wait nine days to hear anything — an approved plan that says nothing reads as broken |
| 17 | `catch_up()` advances any stale occurrence before it is materialised | A safety net, not the main path: materialising something the sweep retires on sight is a loop that writes junk history on every tick. Advancing by whole intervals rather than to "now plus one" keeps a Monday-morning watering on Monday morning |
| 17 | The tick's `403` is the generic forbidden error, with no mention of the secret | An endpoint that says "wrong secret" has told a prober it found the right endpoint |
| 18 | "All caught up" and "no plants yet" are separate states, not one empty box | One is an achievement and the other an invitation. Sharing a component would waste the single moment the product gets to say well done, and would read as though the plants had disappeared |
| 18 | Upcoming care is collapsed rather than listed inline | FINAL §5 asks for it on the page and also says the user should understand *what needs attention today* in seconds. Inline, it pushes today's work down — the tests assert the ordering rather than mere presence |
| 19 | The delivery row is reserved **before** the provider call, not after | Look-send-record leaves a window two ticks can both pass through, and the user gets two emails. Reserving first makes the worst case a row stuck in `QUEUED` |
| 19 | Resend is called over plain HTTP rather than through its SDK | The API is one POST; the dependency would exist solely to build that request, and every package in the deployment is one more to keep current |
| 19 | A task reminder's dedupe key carries no date | A task overdue for a week belongs in the digest, not in a fresh email every morning. `FINAL §14` lists missed-reminder emails as Future, and a dateless key is what keeps that promise |
| 19 | A failed send is not retried the same day | Hammering a provider that is refusing is a good way to lose an account. The task is untouched and the digest returns tomorrow |
| 20 | The timeline is merged on **read** from five tables rather than mirrored into `system_events` | Mirroring means two writes per action across one transaction boundary, and eventually a care event with no timeline entry or an entry for a care event that never happened. Five queries cannot drift |
| 20 | History pages on a timestamp cursor, not an offset | An append-only timeline grows at the head, so offset page-two drifts as entries arrive and the user sees an entry twice or not at all |
| 20 | The dashboard is its own route, not a fatter `GET /v1/plants/{id}` | That endpoint serves the grid, the scheduler and the workflows, none of which want a gallery, a plan and a timeline attached. A view model is for a view |
| 20 | A user may log only `REPOTTED`, `MOVED`, `PRUNED` and `CUSTOM_NOTE` | The rest are written by the actions that cause them. Letting a client pick any `system_event_type` would make the timeline a place where anything can be claimed |
| 21 | An `UNKNOWN` result is stripped of its issues and recommendations | A verdict that could not tell what it was looking at cannot also list what might be wrong. Showing both would let a user act on findings the verdict itself disowns. Observations survive — "the lower leaves are yellow" stays true even when what it means is not |
| 21 | An `UNKNOWN` does not overwrite the plant's status | It records that we could not tell, not that the plant declined. Overwriting a real finding with an absence of one loses information the user already had |
| 21 | The blur threshold was measured, not chosen | The first guess (40) passed a heavily blurred image at 62. Measuring also exposed that `FIND_EDGES` paints a border artefact which made a *flat grey rectangle* score higher than a blurred photograph — the measure was non-monotonic, and a threshold on it meant nothing |
| 21 | A trend shown beside an `UNKNOWN` verdict says where it came from | The trend is computed from earlier *readable* checks and survives an inconclusive one, which is right — but placed next to "we could not tell" it reads as this check's own conclusion. Found by looking at the two badges side by side |
| 22 | Anonymisation is one SQL function, not a sequence of updates | Half of it is worse than none: an account with its email cleared but access still enabled is a user locked out of a login they can still perform, and one disabled but not anonymised is a deletion request that did nothing |
| 22 | The anonymisation audit entry records no email and no display name | An audit trail that preserved what was erased would defeat the operation it describes |
| 22 | Triaging a knowledge report does not itself start research | Acting on a report is the retry route, which may already be in flight. Coupling them would let a status imply a research run that never happened |
| 22 | An administrator cannot anonymise their own account | It would revoke the role needed to undo it, and remove an administrator by accident |
| 23 | The nine journeys drive the HTTP API, not the service layer | A journey that called workflows directly would skip authentication, RLS and response models - which is exactly where both of this PR's defects were |
| 23 | `tests/e2e/` holds the per-agent no-authoritative-record cases, not `tests/agents/` | The plan put them under `tests/agents/`; they need the journey harness (a real database, a real request, four scripted providers), and duplicating that harness to honour a directory name would be worse than moving the file |
| 23 | Journeys call the scheduler scoped to one user rather than `/v1/internal/tick` | The tick is global by design and takes ~25s against a DEV database holding a thousand plants. The route's own authentication and idempotency are covered in `test_scheduler.py` |
| 23 | The AI rate limit is raised inside the journey harness | A journey compresses days of user actions into seconds and would otherwise hit A14's 3/minute. The limiter has its own unit tests |

### Amendments to the specification

| Document | Change |
|---|---|
| `DATABASE_SCHEMA` | The `knowledge_drafts.content` shape recorded in PR 14 (A16): thirteen prose sections each with its own confidence, sources beside them rather than inside them, and why every section is required. Plus nine additions, each with its reasoning: `care_rule_action_type` and `system_event_type` enums, `species.normalized_name`, `notification_preferences` defaults, `health_assessment_sources`, `admin_audit_log`, `notification_deliveries.dedupe_key`, `language` columns, nullable `identification_candidates.species_id` and `plants.name`. Plus the constraints that turn spec rules into database guarantees |
| `PROJECT_STRUCTURE` | §12 records `migrations/` → `supabase/migrations/` (Supabase CLI constraint); §13 records `pages/` → `app_pages/`; §14 records where UI styling lives |
| `FINAL_SPECIFICATION` | §7 records how a restored plant's status is determined; §11 records that research is queued automatically at confirmation and what a draft's lifecycle permits (A17) |
| `API_CONTRACTS` | Identification amended in PR 13: `confirm` takes `candidate_id` (not `confirmed_species_id`); `correct` gains the request body it never had (A13); confidence scale and thresholds recorded (A18); re-identification of an ACTIVE plant defined (A21); confirmation documented as passing **through** `IDENTIFIED` |
| `DEVELOPMENT_PROGRESS` | Checkboxes updated in the PR that completed each item, with `[~]` for anything blocked and the reason |

### Bugs found by running the code rather than reading it

Recorded because each is a pattern worth remembering, not only an incident.

| Found in | Bug | How it surfaced |
|---|---|---|
| PR 2 | `profiles_guard_privileged_columns()` blocked the `postgres` role too — and being `SECURITY DEFINER`, its `current_user` check was meaningless from the start | Applying the migration and running the tests |
| PR 7 | Clock skew: tokens issued seconds ago were rejected as "not yet valid", which in production is intermittent 401s on a host whose clock looks fine | Live auth tests against DEV |
| PR 8 | Layered rate limits leaked: counting pruned the shared event log by the *shortest* window, so requests 70s apart defeated the hourly limit entirely | A test of the layered case, which no single-rule test could have caught |
| PR 9 | The theme silently did not apply — a Google Fonts URL with two families makes Streamlit reject the **whole** `[theme]` block and report it only in the server log | Opening a browser and looking at it |
| PR 11 | PostgREST rewrites `*` to the SQL wildcard, so searching `*` returned every plant; neutralising it to empty then meant "no filter", which returned everything again | An integration test asserting that pattern syntax cannot alter a filter |
| PR 12 | The SDK exposes parsed output as `parsed_output`, not `parsed` — every mocked test passed while every real agent call would have failed | One live call against the real API |
| PR 13 | `agent_requests` had a SELECT policy for the owner and an ALL policy for admins, but **no INSERT policy** — so no user could start an AI request at all. Every AI-triggering endpoint would have failed at its first write | Wiring identification end to end. Nothing before it had created one of those rows through a user's client |
| PR 13 | The repository helpers assumed PostgREST always returns a list. An RPC returning a single composite returns a bare dict, so `first_row()` raised `KeyError: 0` and confirmation failed | The first RPC call made through the repository layer |
| PR 13 | The confirm workflow moved a plant straight from `PENDING_IDENTIFICATION` to `ACTIVE`, which my own lifecycle table refuses — and was right to refuse | An integration test against DEV, contradicting a unit test I had written myself asserting the skip is illegal |
| PR 13 | The binomial validator accepted any two words, so `"unknown plant"` or a whole sentence would have created a species row | Adversarial contract tests written against the validator rather than against the happy path |
| PR 14 | `_normalise()` filtered to `[a-z0-9 ]`, which deletes Hebrew outright — so the common-name relevance fallback was dead code in the one language this application writes | A test written with a Hebrew common name rather than an English one. Every English test passed |
| PR 14 | A second `start_research` on an already-running draft was refused, and reported as "already approved" | An integration test asserting that two confirmations of the same new species join one research run rather than billing twice |
| PR 14 | Six agent tests read configuration without the `env` fixture. They passed locally and failed on push: a developer's `.env` silently satisfies pydantic-settings for any test that forgot it | CI, which has no `.env`. `scripts/check.sh` now runs the CI selection from a directory that has none, so the local gate and CI ask the same question |
| PR 15 | `admin_audit_log` had an admin **read** policy and no INSERT policy — the same gap `agent_requests` had in PR 13, found the same way | An administrator's own client recording a source change. Publication and rejection were unaffected, because their `SECURITY DEFINER` functions bypass RLS — so the gap hid behind the two paths that did not use it |
| PR 15 | PR 14's integration tests named species `Testus {hex}ensis`. `normalize_scientific_name()` strips digits, so those collapse to about a dozen values (`testus a`, `testus b`, …) — and unlike a rolled-back transaction these rows are **committed** against DEV and outlive the run. Seventeen of them silently occupied the name space an older test file drew from, and seventeen previously-green tests began failing | Running the whole integration suite rather than only the new file. `unique_species_name()` existed for exactly this and had been written in PR 6 after the same mistake |
| PR 15 | Every admin action wrote its confirmation with `st.success()` and then called `st.rerun()`, which discards it — so approving published the version, released the plants, and showed the administrator nothing at all. The fan-out count, the part they most need confirmed, was never visible | Clicking the button in a browser. `AppTest` asserts what a run renders, not what survives the rerun a click triggers, so seven green UI tests had nothing to say about it |
| PR 16 | The care context selected five `plant_environments` columns that do not exist — pot material, pot diameter, drainage, soil type, distance from window. Every proposal failed at the first query | The first integration run. The columns were plausible enough to write from memory and are genuinely absent from the schema, which is why the agent's `missing_context` names exactly those facts |
| PR 16 | `list_for_user()` never filtered on `user_id`, leaning entirely on RLS — but `plants_select_admin` deliberately grants administrators read-all, so an admin's own **My Plants** page listed every user's plants, names included | Logging in as an administrator and looking at the page: 590 plants where there should have been one. Every user-facing plant read now scopes to the caller explicitly, and `owner_id` is a required argument so no call site can omit it |
| PR 16 | `my_plants.py` rendered each card without an open action, so the plant dashboard — and with it every screen PR 16 built — was unreachable from the interface | Trying to click through to it. The component supported `on_open` and the page simply never passed it; everything worked and nothing could be got to |
| PR 17 | A missed task was anchored on its own due date, so the next occurrence landed in the past, was retired as expired too, and the scheduler wrote a **MISSED event on every tick** — junk history for as long as the cron kept firing | An integration test asserting FINAL §13's "the next recurrence remains scheduled", which found zero pending tasks. The unit tests could not have caught it: the arithmetic was individually correct, and the loop only exists once materialisation and the sweep run against each other |
| PR 18 | An expired session left the user on a signed-in-looking page with a red banner and no way forward but guessing to reload. `ApiError.is_auth_error` had existed since PR 9 and nothing acted on it | Leaving a browser tab open for two hours while testing. The sequencing is the bug: `access_token()` does clear the session when a refresh fails, but the shell has already routed for that run, so only a rerun sends the next pass to sign-in |
| PR 18 | Upcoming care omitted the action type, so three rules on one plant rendered three word-for-word identical lines — "the monstera · tomorrow at 08:00", three times | Looking at the expanded section in the browser. Every assertion about upcoming care passed: the data was right, the line just did not say which of the three it was |
| PR 20 | **Found before it could bite:** an assessment and its images cannot be written through two PostgREST calls. The 1–4 image constraint is `DEFERRABLE INITIALLY DEFERRED` and therefore checked at commit, and every REST call is its own transaction — so the first commits with zero images and fails. PR 21's Health Agent must use a single RPC | Building a history fixture that needed a health assessment. Recorded in `DATABASE_SCHEMA`, because meeting this while building PR 21 would have looked like a broken constraint rather than a requirement of the design |
| PR 20 | The plant dashboard did not decorate its tasks, rendering **`**** · my plant`** where a reminder belonged — bold-empty is four literal asterisks on screen | Opening the page. The decoration lived in one router and the other never called it; it now lives in the scheduler service, and the card is defensive about a missing label regardless of who forgets |
| PR 20 | Knowledge published before A16 stores sections as plain strings, and `care_context._sections()` required a dict — so **a care plan for any seeded species was built with no knowledge at all**, silently. `knowledge_versions` is content-immutable, so those rows can never be migrated | Expanding the knowledge section on the dashboard and finding it empty. The UI bug was cosmetic; the Care Agent one was not, and nothing had failed loudly enough to notice |

The pattern: **mocks confirm the shape you assumed.** Twenty of these twenty-four were only
findable by executing against the real thing — a live database, a real browser, a
real API — which is why each phase applies its migrations to DEV, and why one
live provider test is kept despite costing money to run.

