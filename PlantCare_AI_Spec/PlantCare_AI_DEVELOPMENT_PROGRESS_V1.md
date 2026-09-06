# PlantCare AI — Development Progress

> **Status:** Ready for implementation  
> **MVP:** Core product + scheduling/reminders + health + admin  
> **Language:** Hebrew / RTL  
> **Frontend:** Streamlit  
> **Backend:** FastAPI  
> **Database/Auth/Storage:** Supabase / PostgreSQL / Supabase Storage

## Status legend

- `[ ]` Not started
- `[-]` In progress
- `[x]` Done
- `[~]` Blocked / pending decision

---

# 1. Product Decisions

All major product decisions are closed.

- [x] MVP scope defined
- [x] Hebrew RTL MVP
- [x] Streamlit frontend
- [x] FastAPI backend
- [x] Supabase Auth/PostgreSQL/Storage
- [x] Four-Agent architecture
- [x] User confirmation of identification
- [x] Species-only MVP model
- [x] Knowledge Draft → Admin Review → Published Knowledge
- [x] Care Plan approval and versioning
- [x] Health Assessment and status model
- [x] Deterministic Python scheduling
- [x] Care Rules vs Care Tasks
- [x] Overdue handling
- [x] Internal + Email reminders
- [x] User timezone handling
- [x] Environment change → Care adjustment proposal
- [x] Health-driven Care adjustment → proposal + approval
- [x] Archive instead of normal plant deletion
- [x] AI image retention/hidden-user policy
- [x] Account anonymization on deletion
- [x] DEV/PROD separation
- [x] GitHub main/dev workflow
- [x] Async-style AI UX
- [x] °C / % units
- [x] Minimal onboarding
- [x] Testing / Acceptance Criteria
- [x] Care Level excluded from MVP
- [x] Social Login excluded from MVP

---

# 2. Documentation

- [x] Product vision
- [x] MVP scope
- [x] User flows
- [x] Identification rules
- [x] Knowledge rules
- [x] Care rules
- [x] Health rules
- [x] Schedule rules
- [x] Notification rules
- [x] Privacy/security rules
- [x] Admin permissions
- [x] AI architecture
- [x] Environment handling
- [x] Image storage/retention
- [x] Testing strategy
- [x] Future feature list
- [x] Final specification

Remaining implementation documentation:
- [ ] Final technical DB schema
- [ ] Final API endpoint contracts
- [ ] Exact UI wireframes/design tokens

---

# 3. Repository & Engineering Setup

- [x] Create GitHub repository — `AssafEzra/plantcare-ai` (public); default branch `dev`
- [x] Create `main`
- [x] Create `dev`
- [x] Protect `main` — PR required (0 approvals, solo project), both CI checks required and must be up to date, linear history, no force pushes, no deletion. Required the repository to be public: branch protection and rulesets are both Pro-only on private repos.
- [x] Define PR workflow — `CONTRIBUTING.md` + `.github/pull_request_template.md`
- [x] Add README
- [x] Add CONTRIBUTING.md
- [x] Add issue templates — bug report + spec ambiguity
- [x] Add `.gitignore`
- [x] Add `.env.example`
- [x] Create local `.env` — git-ignored, points at DEV only
- [x] Document environment variables — `.env.example`, README and `docs/ENVIRONMENTS.md`
- [x] Define Python version — 3.12+, pinned to 3.13 via uv
- [x] Define dependency management — uv + `pyproject.toml`
- [x] Add formatter/linter — ruff (format + lint), mypy
- [x] Add pytest — with `pytest-asyncio`, `pytest-cov`, `freezegun`, `respx`
- [x] Add CI checks — `.github/workflows/ci.yml`: ruff → format → mypy → tests, plus a tracked-`.env` guard. Triggers on push, PR and manual dispatch.

> **Gotcha worth remembering:** a repository created with `gh repo create` can have Actions disabled while `GET /actions/permissions` still reports `enabled: true`. Symptom: zero check-suites are created for pushes and PRs, and only `workflow_dispatch` runs. Fix: `gh api -X PUT repos/<owner>/<repo>/actions/permissions -F enabled=true -f allowed_actions=all`, or click **Enable Actions** on the repository's Actions tab.
- [x] Define logging conventions — `app/config/logging.py`, structlog JSON with secret/chain-of-thought redaction
- [x] Define error-handling conventions — `app/common/errors.py`, `AppError` → API error envelope

---

# 4. Environments

## DEV

- [x] Create DEV Supabase project — `plantcare-dev`, eu-central-1, org `plantcare`
- [x] Create DEV database schema — fifteen migrations applied to DEV
- [x] Configure DEV Auth — email confirmation on, min password length 8, OTP length 8, 60s email throttle, redirect URLs for Streamlit. Version-controlled in `supabase/config.toml` and applied with `supabase config push`
- [x] Configure DEV Storage — private `plant-images` bucket, 10 MiB cap, JPEG/PNG/WEBP allow-list, 5 owner/admin policies (migration 0003)
- [x] Configure DEV AI credentials — a live key is configured; one live provider test exercises it, excluded from CI
- [x] Seed fake/test data
- [x] Verify no PROD credentials are used locally — no PROD project exists yet; `.env` is git-ignored and points at DEV

## PROD

Not started, deliberately: an empty production project is a live set of credentials
nobody is watching, so it is created at the start of PR 24 rather than held open
through the build. Decided before PR 24: org `plantcare`, region `eu-central-1` to
match DEV, **Free plan** - see `DEPLOYMENT_AND_OPERATIONS §13` for what that costs
in recoverability, and the release-checklist item it creates.

- [ ] Create PROD Supabase project
- [ ] Create PROD database schema
- [ ] Configure PROD Auth
- [ ] Configure PROD Storage
- [ ] Configure production secrets
- [ ] Configure backups
- [ ] Configure monitoring
- [ ] Configure deployment
- [ ] Configure rollback
- [ ] Verify DEV/PROD isolation

---

# 5. Database

- [x] Finalize schema
- [x] Create migrations — 0001 through 0015, all applied to DEV
- [x] `profiles` — plus `notification_preferences`, which the signup trigger populates
- [x] `plants`
- [x] `plant_images`
- [x] `plant_environments`
- [x] `identifications`
- [x] `identification_candidates`
- [x] `species` - taxonomy only; knowledge tables follow next
- [x] `knowledge_versions`
- [x] `knowledge_sources`
- [x] `approved_sources`
- [x] `knowledge_drafts`
- [x] `knowledge_reports`
- [x] `care_plans`
- [x] `care_plan_versions` (source_type covers version provenance — no separate care_plan_changes table) - migration 0007
- [x] `care_rules`
- [x] `care_tasks`
- [x] `care_events`
- [x] `health_assessments` - plus health_assessment_images and health_assessment_sources
- [x] `health_observations`
- [x] `health_issues`
- [x] `health_recommendations`
- [x] `agent_executions`
- [x] `agent_requests`
- [x] `system_events` - plus admin_audit_log and notification_deliveries
- [x] Define foreign keys
- [x] Define indexes
- [x] Define constraints/enums — all enums and per-table constraints
- [x] Define RLS policies — every user-owned table, proved table by table by the PR 23 matrix
- [x] Define immutable/versioned records
- [x] Define archive/anonymization behavior - archive constraints, and `anonymize_account()` in migration 0015
- [x] Seed reference/test data - 6 approved sources, 3 species, 2 published Hebrew versions, 1 species left bare for the draft workflow

---

# 6. Storage

- [x] Create Supabase Storage bucket(s) — `plant-images`, private, created by migration so PROD is identical
- [x] Implement image validation - decodes with Pillow; declared type and extension are never trusted
- [x] Enforce 10 MB maximum — bucket cap and application validation
- [x] Support JPG/JPEG/PNG/WEBP — bucket allow-list, plus Pillow decoding so the bytes decide, not the declared type
- [x] Process/resize/compress - 1600px long edge at q85
- [x] Generate thumbnail - 400px long edge
- [x] Store original + processed + thumbnail - original byte-for-byte, derivatives EXIF-free
- [x] Implement logical paths — `{user_id}/{plant_id}/{gallery|identification|health}/`, enforced by policies on the first path segment
- [x] Implement owner-only access — select/insert/update/delete scoped to the owner; admins read-only across owners for retained AI images
- [x] Implement hidden retention for AI-used images
- [x] Implement metadata persistence
- [x] Test Storage RLS/access behavior — 13 integration tests covering cross-user read/write denial, anonymous denial and admin read

---

# 7. Authentication & Authorization

- [x] Supabase Auth setup
- [x] Email/password registration
- [x] Email verification - enable_confirmations on, version-controlled in supabase/config.toml
- [x] Email/password login
- [x] Password reset - response is identical for known and unknown addresses
- [x] Logout
- [x] Session handling - JWKS-verified access tokens with clock-skew leeway
- [x] Session survives a browser refresh (PR 32) - the refresh token is kept in a `SameSite=Lax` cookie and the session rebuilt from it before routing. Held only in `st.session_state`, which lives for one Streamlit session, F5 was indistinguishable from signing out (FINAL §22)
- [x] User profile - GET and PATCH /v1/me
- [x] Admin role - require_admin reads profiles.role server-side, never from the token
- [x] RLS policies - proven end to end: a client built from the caller's JWT is scoped by RLS
- [x] Authorization tests - 17 live tests plus 20 cryptographic token tests
- [x] Auth error states - 401/403/422 envelopes, no internal detail leaked

---

# 8. Application Shell

- [x] Streamlit shell - st.navigation, app_pages/, sign-in gate
- [x] RTL
- [x] Hebrew UI
- [x] Sidebar navigation - Material Symbols icons, admin entry hidden for non-admins
- [x] Shared components - status badges, page header, empty state, guarded loading
- [x] Natural/Premium design direction - design tokens applied via .streamlit/config.toml
- [x] Responsive layout - 1280px max width, native containers, and the card grid
- [x] Loading states
- [x] Error states - API error envelope translated to Hebrew in one place
- [x] Empty states
- [x] Settings - name and timezone; notification preferences pending their endpoints
- [x] Admin route visibility

---

# 9. Dashboard

- [x] Greeting - personalised and time-aware; "good morning" at ten at night makes a page feel unattended
- [x] Plant count
- [x] Today's task count
- [x] Needs Attention count
- [x] Today's Care - first on the page, because it is the only thing the user can act on now
- [x] Done/Skip - both always offered; the schedule treats a skip differently from silence. **Reachable only from PR 32**: the endpoints declared a required request body and both screens send none, so every press returned 422 before the scheduler was reached - no event, no status change, the card unchanged
- [x] Upcoming care - the next three on the page from PR 32, the rest behind an expander. Collapsed entirely, it never competed with today's work because nobody saw it
- [x] Plants Needing Attention
- [x] Quick Health Check - routes to the plant, where the check runs (PR 21)
- [x] My Plants preview
- [x] Add Plant CTA
- [x] All-caught-up state - distinct from "no plants yet": one is an achievement, the other an invitation

---

# 10. My Plants

- [x] Plant grid
- [x] Plant card
- [x] Main image - first gallery upload becomes the main image
- [x] Plant Name - set at confirmation from the chosen candidate when the user does not type one (PR 28; A2 said so in PR 2 and nothing implemented it, so every card read "ללא שם")
- [x] Species - common name where there is one, the binomial otherwise (PR 25)
- [x] Health status
- [x] Nearest task - the earliest open task, in the same words the task card uses (PR 25)
- [x] Attention indicator - the health badge, plus an explicit caption while a plant waits for identification or knowledge; a plant whose identification is finished says it is waiting on the *user* (PR 28)
- [x] Search - pattern syntax neutralised so a wildcard cannot match everything
- [~] Basic sort/filter - status and health filters and search are done; **sort is still not built**
- [x] Click → Plant Dashboard - delivered in PR 16; the checkbox was missed
- [x] Empty state - distinguishes an empty search from an empty account
- [x] Loading state

---

# 11. Add Plant & Identification

- [x] Add Plant flow - step 1: create plant, upload identification photos
- [x] 1-4 identification photos
- [x] Photo preview
- [x] Remove/add photo
- [x] Photo guidance
- [x] Optional user note
- [x] Identification Agent contract
- [x] Multimodal model integration - vision verified against the real API
- [x] Structured output
- [x] Confidence - 0.000-1.000, level derived in Python (HIGH >= 0.85, MEDIUM >= 0.60)
- [x] Alternatives - up to two, re-sorted by confidence, duplicates collapsed
- [x] Image quality
- [x] Identification review - confirmation screen with processing stages; reachable from the plant's own dashboard as well as from the wizard (PR 28). The stage display is shared by all four agents from PR 30
- [x] Wikipedia link validation - verified against Wikipedia's REST API; a redirect to a different subject is rejected
- [x] User confirmation - the only point at which a species becomes authoritative, and the point at which the plant is named (PR 28)
- [x] Re-identification - an ACTIVE plant stays active while the new species is researched (A21)
- [x] Identification history - append-only; a correction adds a row, and from PR 31 a user can actually file one (A13; the endpoint had no caller)
- [x] New Species creation - at confirm, from the chosen candidate
- [x] Knowledge Pending state - research draft opened, plant remains usable
- [x] Existing Knowledge lookup - published knowledge activates the plant immediately, and from PR 31 queues its first care proposal too (A3). Until then this road into ACTIVE produced a plant with no plan at all
- [x] Graceful failure states - FAILED and NEEDS_MORE_INFORMATION both surface without an authoritative record

---

# 12. Knowledge Agent & Knowledge Base

- [x] Species entity
- [x] Knowledge Version entity
- [x] Immutable published versions - content-immutable, `is_current` mutable; DELETE refused outright
- [x] Knowledge lookup - at confirmation, keyed on `(species_id, language)`
- [x] Knowledge Draft entity
- [x] Knowledge Agent contract - the 14 sections as a validated schema (A16)
- [x] Web research mechanism - provider-native grounding, then deterministic verification in Python
- [x] Approved Source policy - label-boundary domain match against the enabled allow-list
- [x] Source provenance - class, URL and publisher recorded per source, decided by Python not by the model
- [x] External/unapproved source marking - permitted, marked, and flagged for extra admin attention
- [x] Draft retry - a rejected or failed draft stays retriable (A17); an approved one is terminal
- [x] Admin review - weak sections surfaced first, unverified sources shown before approval
- [x] Approve/reject - a rejection must carry a reason, and leaves the species retriable (A17)
- [x] Publish Knowledge Version - one transaction: demote, insert, sources, draft, fan-out, audit
- [x] User read-only access - current version only; writes refused by RLS, not only by the API
- [x] User error report - records the version being complained about, so it stays legible later
- [x] Approved Sources management - add, edit, disable; the domain itself is not editable
- [x] Version history - admin-only, via the read-all policy added in migration 0006
- [x] Admin audit logging - publication and rejection audit inside their own transaction

---

# 13. Care Agent & Care Plans

- [x] Care Agent contract
- [x] Input schema - the seven §12 inputs as `CareContext`, and nothing else the agent can reach
- [x] Output schema - recommendations and rules as separate fields, which is what makes "advice is not editable" enforceable
- [x] Context assembly - `orchestration/services/care_context.py`, read through the caller's client so RLS applies
- [x] Use Knowledge Version - the plan-relevant sections only; the version id is recorded on the plan
- [x] Use Plant
- [x] Use Environment
- [x] Use Health state/history
- [x] Generate Care Plan proposal - always a proposal; nothing here can activate a plan
- [x] Structured Care Rules - closed action enum (A19), bounded intervals, A7 weekday coherence
- [x] Validate output - `domain/rules/care_rule_validation.py`; an implausible rule is dropped, not fatal to the plan
- [x] User approval - the only path to ACTIVE
- [x] Persist Care Plan
- [x] Version Care Plans - one transaction: supersede, activate, repoint, cancel old pending tasks (A5)
- [x] Change Summary - required on every version after the first, by CHECK constraint
- [x] Operational preference editing - no model call; recommendations copied byte-identical
- [x] Environment-change proposal - proposal only, per the §12 flow; requested by the environment form from PR 30, which is what finally makes the first arrow of that flow exist
- [x] Health-driven proposal - endpoint ready; the Health Agent that calls it lands in PR 21
- [x] Preserve previous versions - content-immutable, asserted by comparing the stored blobs

---

# 14. Schedule & Care Tasks

- [x] Schedule domain model - `domain/rules/recurrence.py`, pure: no clock, no database, no model
- [x] Recurring Rule schema
- [x] Care Task schema
- [x] Care Event schema
- [x] Deterministic recurrence engine - day arithmetic in the user's zone, so DST cannot move a reminder
- [x] Upcoming task calculation - 14-day horizon, at most one PENDING task per rule. **Actually invoked from PR 32**: `materialise` was called only by `/v1/internal/tick`, which nothing called, so an approved plan produced zero tasks. Approving now materialises, and the API runs the sweep on its own timer
- [x] Completed state - immutable event; next occurrence anchored on when it actually happened (A8)
- [x] Skipped state - anchored on the original due date, so repeated skipping cannot push the schedule out
- [x] Overdue state
- [x] Overdue summary - one line per plant, most overdue first (FINAL §13)
- [x] Next recurrence handling - still scheduled after a miss, and anchored so it lands in the future
- [x] Avoid infinite backlog - A9 expiry, the one-PENDING-per-rule index, and `catch_up()` against stale occurrences
- [x] Schedule UI - the Home dashboard (PR 18)
- [x] Done/Skip actions - duplicates refused with 409 by a unique index, not a read-then-check
- [x] Care History integration - events are written and the merged timeline renders them (PR 20)
- [x] User timezone handling - "today" is the user's calendar day; an unknown zone degrades to UTC rather than failing the tick

---

# 15. Notifications

- [x] Notification model
- [x] In-app reminders - rendered from the same task query as the dashboard, so email and screen cannot disagree
- [x] EmailProvider abstraction - `NullProvider` is the default, so an unconfigured deployment sends nothing rather than crashing
- [x] Resend provider - plain HTTP; the SDK would exist only to build one POST
- [x] Email on/off - respected before a message is built, not by discarding one afterwards
- [x] Preferred reminder time - A10: this governs when we may *write*, not when a task is due
- [x] Daily digest - honoured as a preference; the plan's first draft chose by task count, which made the setting inert
- [x] Delivery logging - user-visible from PR 31, in Settings. The claim was written in PR 19 and was false until then: the endpoint existed and no screen called it
- [x] Duplicate-send prevention - the row is reserved *before* the provider call, so a second tick dies on the unique index with nothing in flight
- [x] Timezone-aware sending - the dedupe key carries the user's local date, so changing zone cannot produce two digests on one of their days

---

# 16. Health Agent

- [x] Health Agent contract
- [x] 1–4 image input - bounded in the request model and re-checked in the workflow; delivered in PR 21
- [x] Image quality validation - A25: warns, never blocks, so the UNKNOWN outcome stays reachable
- [x] Optional note - framed to the model as the user's description, not a finding
- [x] Result and status shown when the run ends (PR 30) - the check was fired and never polled, so neither a result nor a failure ever reached the user
- [x] Context assembly - the seven §16 inputs; the agent reaches no database
- [x] Structured HealthAssessment
- [x] Overall status
- [x] Observations - kept separate from issues, because one is far more reliable than the other
- [x] Possible issues - each must carry the evidence it rests on; there is no field for a diagnosis
- [x] Severity - separate from overall status, as §16 requires
- [x] Confidence - forbidden on an UNKNOWN, by schema and by CHECK constraint
- [x] Recommendations
- [x] Sources - the table and the write path exist; the agent is not yet asked to cite
- [x] UNKNOWN handling - saved with its reason, stripped of findings, and does not overwrite a real status
- [x] Update Plant current status - inside the same transaction as the assessment
- [x] Immutable assessment history - the trigger refuses even the service role
- [x] Basic trend - A11: computed in Python, skipping UNKNOWN rather than counting it as a decline
- [x] Care adjustment proposal - a HEALTH_DRIVEN proposal the user approves; the agent cannot touch the plan
- [x] Health disclaimer - findings are presented as possibilities in the interface, not only in the prompt
- [~] Follow-up questions where necessary - same scoping as A20: no status, table or endpoint can carry a question, so the agent says what would help and produces a result anyway

---

# 17. Plant Dashboard & History

- [x] Overview - one `GET /v1/plants/{id}/dashboard`; the §17 sections would otherwise be eight round trips
- [x] Species
- [x] Personal name - and editable from PR 31: `PATCH /v1/plants/{id}` shipped in PR 11 and no screen ever called it, so a plant kept whatever name confirmation gave it forever
- [x] Health status - with trend, from the latest assessment
- [x] Environment
- [x] Care summary - due tasks are completable here from PR 31; `care_task_card` draws Done/Skip only when given the callbacks and this page gave none, so the same task was actionable on Home and read-only on the plant
- [x] Gallery - signed as the caller, short-lived; the bucket stays private. Images can be removed from PR 31, with FINAL §20's hide-vs-delete outcome reported to the user
- [x] Care section
- [x] Schedule section
- [x] Health section - findings, evidence, and the UNKNOWN path (PR 21)
- [x] History section - merged from five tables on read, so the timeline cannot drift from the data
- [x] Health Check CTA - opens a dialog from PR 32: photographs taken now *and* existing gallery images. It shipped as an inline chooser over the gallery alone, which is the wrong shape - a check is prompted by something just noticed, and an empty gallery was a dead end
- [x] Environment update - editable from the plant dashboard, every field optional; a save requests an ENVIRONMENT_CHANGE proposal when the plant has a plan (PR 30 - shipped read-only in PR 20, and the note promising a plan review was the only part that worked)
- [x] Knowledge display with provenance (PR 31) - version, publication date and the verified sources. The endpoint always returned them; only the prose was ever rendered
- [x] Knowledge error report - report, never edit (FINAL §10)
- [x] Archive/restore - history survives both
- [x] Manual history event - the four user-created kinds only; the rest are written by the actions that cause them
- [x] Timeline UI - one shape per entry whatever table it came from

---

# 18. Admin

- [x] Admin authentication/role - read from the database per request, never from the token
- [x] Admin dashboard - ordered by what would make someone act: failures, then queues, then volume
- [x] Knowledge Drafts
- [x] Draft sources - unverified citations shown first, above the approve button
- [x] Approve/reject
- [x] Notification deliveries (PR 31) - what was actually sent, and what failed
- [x] Admin notes
- [x] Published Knowledge - browsable from PR 32: every species with a current version, searchable by name, each opening the full text and its sources. It shipped as a box asking for a species UUID, so on 857 species none of it was reachable
- [x] Version history
- [x] Approved Sources
- [x] Reported Errors - triage is recorded; acting on one is the separate retry route, so a status cannot imply research that never ran
- [x] AI/Agent Monitoring - model, prompt version, duration, tokens, cost; plus the agent *requests* those executions belong to (PR 31), because the two can disagree and that gap is exactly how PR 30's regression hid
- [x] Agent execution logs - no column exists for prompts or reasoning, so the view cannot leak them however it is queried
- [x] Audit Log - append-only; the table refuses UPDATE and DELETE for everyone, and from PR 31 an administrator can read it. An audit log nobody can open records everything and proves nothing
- [x] Admin action logging - one entry per consequential action, asserted per action
- [~] Appropriate access to retained AI-used images - the rows are retained and flagged `ai_used`; the admin gallery view is Future, since nothing in the MVP needs to look at them
- [x] Anonymized-account administration - FINAL §21 in one transaction: identity cleared, access disabled, history kept, action audited without recording what was erased

---

# 19. AI Infrastructure

- [x] Wikipedia-link verification mechanism — resolved: Wikipedia's own public REST API, no vendor decision needed
- [x] `retrieve_source()` mechanism for Knowledge Agent research — resolved: provider-native search/grounding (Claude/GPT/Gemini all support it), no separate search-API vendor for MVP
- [x] Implement deterministic source-verification step (fetch URL, check HTTP 200 + relevance, classify APPROVED/EXTERNAL_UNAPPROVED by domain match against `approved_sources`) before any `knowledge_sources` row is persisted - `app/domain/services/source_verification.py`, delivered in PR 14
- [x] AIProvider interface
- [x] AI Gateway
- [x] Provider configuration
- [x] Per-Agent model configuration
- [x] Per-Agent timeout configuration (PR 29) - knowledge 600s, care and health 180s, identification 90s; one shared 90s budget killed the first real research run
- [x] Structured output validation - schema-validated via a streamed `messages.stream(...).get_final_message()`, so a long generation is measured chunk to chunk rather than end to end (PR 29)
- [x] Retry policy (max 2) - only schema failures retried; ceiling asserted in config, tests and a CHECK constraint
- [x] Timeout policy - configurable per agent; a timeout is not retried, which is why the budget has to be right the first time
- [x] Error handling
- [x] Prompt versioning - prompts/<agent>/<name>.vNNN.md, version recorded per execution
- [x] Agent execution logging
- [x] Token/cost metadata
- [x] Latency metadata
- [x] No chain-of-thought persistence - the execution record has no field that could hold it
- [x] Async/background-compatible architecture - AgentExecutor seam; swapping in a worker changes one file
- [x] Abandoned-run recovery (PR 31) - the tick fails any request past its agent's budget, because a restart kills in-flight background work and left the row PROCESSING forever

---

# 20. Testing

## Unit

- [x] Schedule recurrence - table-driven, including an Asia/Jerusalem DST crossing both ways
- [x] Overdue calculation
- [x] Care Rule validation
- [x] Health status - trend, and the UNKNOWN path
- [x] Versioning - content immutability, and the status transitions it must still permit
- [x] Permissions - JWT verification, role re-read server-side, admin dependency
- [x] Image validation
- [x] AI schema validation - two retries, then a graceful failure

## Integration

- [x] Authentication
- [x] Add Plant
- [x] Identification
- [x] Knowledge lookup
- [x] Knowledge Draft
- [x] Care Plan
- [x] Schedule
- [x] Health Check
- [x] Care adjustment
- [x] Notifications
- [x] Admin workflow

## E2E

Nine journeys, driven through the HTTP API against DEV with a scripted model per
agent. `tests/e2e/`. The ninth - a user reporting a knowledge error and an
administrator acting on it - comes from `TESTING_STRATEGY §9`, which lists it as a
scenario while this section omits it.


- [x] New user → Add Plant → Confirm ID → Knowledge → Care Plan → Schedule
- [x] Existing species → reuse published Knowledge - no second draft, no second version
- [x] New species → Draft → Admin approval → Active plant - the A4 fan-out, from the user's side
- [x] Health Check → status update
- [x] Health Check → Care proposal → approval - and the plan is untouched in between
- [x] Overdue task → completion → history - and the next recurrence stays scheduled
- [x] User isolation / RLS - through the API, plus a table-by-table matrix at the database
- [x] AI failure → no authoritative record - one case per agent

---


## What the journeys found

Two defects that every unit test passed over, both in seams between phases:

- `GET /v1/agent-requests/{id}` did not return `output_summary`, so a client that
  polled until COMPLETE had no way to reach the identification it had just paid
  for. The Add Plant flow dead-ended at "not found".
- `GET /v1/species/{id}/knowledge` returned 500 whenever `source_summary` was
  NULL - 131 of the 238 current versions in DEV, the seed included.

Both are recorded in `API_CONTRACTS_V1.md`.

# 21. Deployment

- [ ] Deploy DEV application
- [ ] Verify DEV database only
- [ ] Seed fake data
- [ ] Test migrations
- [ ] Test AI flows safely
- [ ] Production deployment
- [ ] Production secrets
- [ ] Monitoring/logging
- [ ] Backups
- [ ] Rollback
- [ ] Verify production isolation
- [ ] Validate Railway deployment direction
- [ ] Streamlit deployment
- [ ] FastAPI deployment
- [ ] Environment variables
- [ ] Health checks

---

# 22. MVP Release Checklist

- [ ] Critical E2E smoke test passes
- [ ] RLS tests pass
- [ ] No production credentials in DEV
- [ ] AI failures are graceful
- [ ] Admin permissions verified
- [ ] Image access verified
- [ ] Email duplicate prevention verified
- [ ] Timezone behavior verified
- [ ] Archive/anonymization behavior verified
- [ ] Backup/rollback verified
- [ ] README complete
- [ ] `.env.example` complete
- [ ] Final specification matches implementation
- [ ] Final UI matches approved direction

---

# 23. Future Features — Backlog

- [ ] Google Login
- [ ] Apple Login
- [ ] Other Social Login
- [ ] Care Level personalization
- [ ] Google Calendar
- [ ] Apple Calendar
- [ ] Push Notifications
- [ ] Advanced Email Notifications
- [ ] Smart Notification Timing
- [ ] Cultivar support
- [ ] Advanced Health Trends
- [ ] Before/After analysis
- [ ] Adaptive Care Plans
- [ ] Weather/environment integrations
- [ ] Smart watering insights
- [ ] ML plant-purchase recommendations
- [ ] Product recommendations
- [ ] Partnerships/affiliate commerce
- [ ] Community/sharing
- [ ] Expert Q&A
- [ ] Collections/tags
- [ ] IoT/smart devices
- [ ] Native mobile app
- [ ] English localization

---

# 24. Next Engineering Milestone

**Start implementation.**

Recommended order:

1. Repository + environment setup
2. Supabase DEV project
3. Database migrations + RLS
4. Auth
5. FastAPI application structure
6. Streamlit application shell
7. Image pipeline
8. Add Plant vertical slice
9. Identification Agent
10. Species/Knowledge workflow
11. Care Agent + Care Plan
12. Scheduler + Tasks
13. Notifications
14. Plant Dashboard + History
15. Health Agent
16. Admin Panel
17. Integration/E2E testing
18. Production deployment

