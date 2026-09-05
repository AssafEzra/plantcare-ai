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
- [~] Create local `.env` — blocked until the DEV Supabase project exists (§4)
- [-] Document environment variables — `.env.example` + README done; `docs/ENVIRONMENTS.md` lands with §4
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
- [-] Create DEV database schema — foundation migration applied; remaining tables follow
- [x] Configure DEV Auth — email confirmation on, min password length 8, OTP length 8, 60s email throttle, redirect URLs for Streamlit. Version-controlled in `supabase/config.toml` and applied with `supabase config push`
- [x] Configure DEV Storage — private `plant-images` bucket, 10 MiB cap, JPEG/PNG/WEBP allow-list, 5 owner/admin policies (migration 0003)
- [~] Configure DEV AI credentials — deferred by decision; `.env` holds a placeholder. Needed before Phase 8
- [x] Seed fake/test data
- [x] Verify no PROD credentials are used locally — no PROD project exists yet; `.env` is git-ignored and points at DEV

## PROD

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
- [-] Create migrations — 0001 foundation + 0002 corrective applied to DEV; plants/identification, knowledge, care/health/system to follow
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
- [ ] `care_plan_versions` (source_type covers version provenance — no separate care_plan_changes table)
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
- [-] Define constraints/enums — all 24 enums created; per-table constraints land with their tables
- [-] Define RLS policies — `profiles` and `notification_preferences` done; `is_admin()` helper available to all later migrations
- [x] Define immutable/versioned records
- [-] Define archive/anonymization behavior - archive constraints in place; anonymisation lands with the admin panel
- [x] Seed reference/test data - 6 approved sources, 3 species, 2 published Hebrew versions, 1 species left bare for the draft workflow

---

# 6. Storage

- [x] Create Supabase Storage bucket(s) — `plant-images`, private, created by migration so PROD is identical
- [x] Implement image validation - decodes with Pillow; declared type and extension are never trusted
- [-] Enforce 10 MB maximum — bucket-level cap in place; application-level validation lands in Phase 6
- [-] Support JPG/JPEG/PNG/WEBP — bucket MIME allow-list in place; Pillow-based content validation lands in Phase 6
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
- [-] Responsive layout - 1280px max width and native containers; card grids land with the plant list
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
- [x] Done/Skip - both always offered; the schedule treats a skip differently from silence
- [x] Upcoming care - collapsed, so it never competes with today's work
- [x] Plants Needing Attention
- [~] Quick Health Check - the button is on Home and routes to the plant; the check itself is the Health Agent (PR 21)
- [x] My Plants preview
- [x] Add Plant CTA
- [x] All-caught-up state - distinct from "no plants yet": one is an achievement, the other an invitation

---

# 10. My Plants

- [x] Plant grid
- [x] Plant card
- [x] Main image - first gallery upload becomes the main image
- [x] Plant Name
- [ ] Species
- [x] Health status
- [ ] Nearest task
- [ ] Attention indicator
- [x] Search - pattern syntax neutralised so a wildcard cannot match everything
- [-] Basic sort/filter - health filter done; sort follows with the scheduler
- [ ] Click → Plant Dashboard
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
- [x] Identification review - confirmation screen with processing stages
- [x] Wikipedia link validation - verified against Wikipedia's REST API; a redirect to a different subject is rejected
- [x] User confirmation - the only point at which a species becomes authoritative
- [x] Re-identification - an ACTIVE plant stays active while the new species is researched (A21)
- [x] Identification history - append-only; a correction adds a row
- [x] New Species creation - at confirm, from the chosen candidate
- [x] Knowledge Pending state - research draft opened, plant remains usable
- [x] Existing Knowledge lookup - published knowledge activates the plant immediately
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
- [x] Environment-change proposal - proposal only, per the §12 flow
- [x] Health-driven proposal - endpoint ready; the Health Agent that calls it lands in PR 21
- [x] Preserve previous versions - content-immutable, asserted by comparing the stored blobs

---

# 14. Schedule & Care Tasks

- [x] Schedule domain model - `domain/rules/recurrence.py`, pure: no clock, no database, no model
- [x] Recurring Rule schema
- [x] Care Task schema
- [x] Care Event schema
- [x] Deterministic recurrence engine - day arithmetic in the user's zone, so DST cannot move a reminder
- [x] Upcoming task calculation - 14-day horizon, at most one PENDING task per rule
- [x] Completed state - immutable event; next occurrence anchored on when it actually happened (A8)
- [x] Skipped state - anchored on the original due date, so repeated skipping cannot push the schedule out
- [x] Overdue state
- [x] Overdue summary - one line per plant, most overdue first (FINAL §13)
- [x] Next recurrence handling - still scheduled after a miss, and anchored so it lands in the future
- [x] Avoid infinite backlog - A9 expiry, the one-PENDING-per-rule index, and `catch_up()` against stale occurrences
- [~] Schedule UI - the Home dashboard is PR 18; `GET /v1/dashboard` and `GET /v1/care-tasks` are ready for it
- [x] Done/Skip actions - duplicates refused with 409 by a unique index, not a read-then-check
- [~] Care History integration - events are written; the merged timeline is PR 20
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
- [x] Delivery logging - user-visible, so "we did email you" is checkable rather than trusted
- [x] Duplicate-send prevention - the row is reserved *before* the provider call, so a second tick dies on the unique index with nothing in flight
- [x] Timezone-aware sending - the dedupe key carries the user's local date, so changing zone cannot produce two digests on one of their days

---

# 16. Health Agent

- [ ] Health Agent contract
- [ ] 1–4 image input
- [ ] Image quality validation
- [ ] Optional note
- [ ] Context assembly
- [ ] Structured HealthAssessment
- [ ] Overall status
- [ ] Observations
- [ ] Possible issues
- [ ] Severity
- [ ] Confidence
- [ ] Recommendations
- [ ] Sources
- [ ] UNKNOWN handling
- [ ] Update Plant current status
- [ ] Immutable assessment history
- [ ] Basic trend
- [ ] Care adjustment proposal
- [ ] Health disclaimer
- [ ] Follow-up questions where necessary

---

# 17. Plant Dashboard & History

- [ ] Overview
- [ ] Species
- [ ] Personal name
- [ ] Health status
- [ ] Environment
- [ ] Care summary
- [ ] Gallery
- [ ] Care section
- [ ] Schedule section
- [ ] Health section
- [ ] History section
- [ ] Health Check CTA
- [ ] Environment update
- [ ] Knowledge error report
- [ ] Archive/restore
- [ ] Manual history event
- [ ] Timeline UI

---

# 18. Admin

- [ ] Admin authentication/role
- [ ] Admin dashboard
- [ ] Knowledge Drafts
- [ ] Draft sources
- [ ] Approve/reject
- [ ] Admin notes
- [ ] Published Knowledge
- [ ] Version history
- [ ] Approved Sources
- [ ] Reported Errors
- [ ] AI/Agent Monitoring
- [ ] Agent execution logs
- [ ] Audit Log
- [ ] Admin action logging
- [ ] Appropriate access to retained AI-used images
- [ ] Anonymized-account administration

---

# 19. AI Infrastructure

- [x] Wikipedia-link verification mechanism — resolved: Wikipedia's own public REST API, no vendor decision needed
- [x] `retrieve_source()` mechanism for Knowledge Agent research — resolved: provider-native search/grounding (Claude/GPT/Gemini all support it), no separate search-API vendor for MVP
- [ ] Implement deterministic source-verification step (fetch URL, check HTTP 200 + relevance, classify APPROVED/EXTERNAL_UNAPPROVED by domain match against `approved_sources`) before any `knowledge_sources` row is persisted
- [x] AIProvider interface
- [x] AI Gateway
- [x] Provider configuration
- [x] Per-Agent model configuration
- [x] Structured output validation - schema-validated via messages.parse
- [x] Retry policy (max 2) - only schema failures retried; ceiling asserted in config, tests and a CHECK constraint
- [x] Timeout policy - configurable; a timeout is not retried
- [x] Error handling
- [x] Prompt versioning - prompts/<agent>/<name>.vNNN.md, version recorded per execution
- [x] Agent execution logging
- [x] Token/cost metadata
- [x] Latency metadata
- [x] No chain-of-thought persistence - the execution record has no field that could hold it
- [x] Async/background-compatible architecture - AgentExecutor seam; swapping in a worker changes one file

---

# 20. Testing

## Unit

- [ ] Schedule recurrence
- [ ] Overdue calculation
- [ ] Care Rule validation
- [ ] Health status
- [ ] Versioning
- [ ] Permissions
- [ ] Image validation
- [ ] AI schema validation

## Integration

- [ ] Authentication
- [ ] Add Plant
- [ ] Identification
- [ ] Knowledge lookup
- [ ] Knowledge Draft
- [ ] Care Plan
- [ ] Schedule
- [ ] Health Check
- [ ] Care adjustment
- [ ] Notifications
- [ ] Admin workflow

## E2E

- [ ] New user → Add Plant → Confirm ID → Knowledge → Care Plan → Schedule
- [ ] Existing species → reuse published Knowledge
- [ ] New species → Draft → Admin approval → Active plant
- [ ] Health Check → status update
- [ ] Health Check → Care proposal → approval
- [ ] Overdue task → completion → history
- [ ] User isolation / RLS
- [ ] AI failure → no authoritative record

---

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

