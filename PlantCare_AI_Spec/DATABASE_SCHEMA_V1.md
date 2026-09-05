# PlantCare AI — DATABASE_SCHEMA.md

## Database
Supabase PostgreSQL. UUID primary keys. `timestamptz` stored in UTC. RLS is mandatory on every application table. Supabase Auth owns identity; Supabase Storage owns image binaries.

## Lifecycle enums
```text
plant_status = PENDING_IDENTIFICATION | IDENTIFIED | KNOWLEDGE_PENDING | ACTIVE | ARCHIVED
identification_status = SUCCESS | NEEDS_MORE_INFORMATION | FAILED
identification_method = AI | USER_CONFIRMED | USER_CORRECTED
confidence_level = HIGH | MEDIUM | LOW
knowledge_draft_status = DRAFT | RESEARCHING | READY_FOR_REVIEW | REJECTED | FAILED | APPROVED
knowledge_source_class = APPROVED | EXTERNAL_UNAPPROVED | AI_GENERATED_REQUIRES_VERIFICATION
care_plan_version_status = PROPOSED | ACTIVE | SUPERSEDED | REJECTED
care_task_status = PENDING | DONE | SKIPPED | OVERDUE | CANCELLED
care_event_type = DONE | SKIPPED | MISSED | CORRECTED
health_status = HEALTHY | NEEDS_ATTENTION | CRITICAL | UNKNOWN
health_trend = IMPROVING | WORSENING | STABLE | UNABLE_TO_DETERMINE
agent_type = IDENTIFICATION | KNOWLEDGE | CARE | HEALTH
agent_request_status = QUEUED | PROCESSING | SUCCEEDED | FAILED | CANCELLED
notification_channel = EMAIL
notification_delivery_status = QUEUED | SENT | FAILED | SKIPPED
user_role = USER | ADMIN
care_plan_version_source_type = INITIAL_PLAN | OPERATIONAL_ADJUSTMENT | ENVIRONMENT_CHANGE | HEALTH_DRIVEN | RE_IDENTIFICATION
care_rule_action_type = WATERING | FERTILIZING | REPOTTING | PRUNING | MISTING | ROTATING | INSPECTION
system_event_type = PLANT_CREATED | PLANT_ARCHIVED | PLANT_RESTORED | PLANT_RENAMED | ENVIRONMENT_CHANGED | MAIN_IMAGE_CHANGED | REPOTTED | MOVED | PRUNED | CUSTOM_NOTE
image_context_type = gallery | identification | health
location_type = INDOOR | OUTDOOR | BALCONY | GREENHOUSE
light_level = LOW | MEDIUM | BRIGHT | DIRECT_SUN
light_direction = NORTH | SOUTH | EAST | WEST | UNKNOWN
weekday = MONDAY | TUESDAY | WEDNESDAY | THURSDAY | FRIDAY | SATURDAY | SUNDAY
```

**Added during implementation (MVP), per FINAL_SPECIFICATION §37:**

- `care_rule_action_type` — `care_rules.action_type` was previously untyped, yet the
  wireframe icons, notification copy and the Care Agent's structured output all depend
  on a fixed vocabulary. Kept minimal: `ALTER TYPE ... ADD VALUE` is cheap, removal is not.
- `system_event_type` — `system_events.event_type` previously named only
  `ENVIRONMENT_CHANGED` while §19 lists ~11 timeline kinds. This enum deliberately
  **excludes** care events, health checks, identifications and care plan versions, which
  have dedicated tables that the Plant History timeline merges; including them would
  double-write every care action. `REPOTTED`/`MOVED`/`PRUNED`/`CUSTOM_NOTE` are
  user-logged out-of-band actions, distinct from the same action arriving via a task.
- `image_context_type`, `location_type`, `light_level`, `light_direction`, `weekday` —
  vocabularies already fixed in prose by §18 and the `care_rules` note, now enforced by
  the database rather than by convention.

## Core tables

### `profiles`
`id uuid PK` (same as `auth.users.id`), `email`, `display_name`, `role` (`user_role`), `timezone`, `locale`, `is_active`, `anonymized_at`, `created_at`, `updated_at`.

`care_level` is explicitly excluded from MVP (see FINAL_SPECIFICATION §2, §36) and is intentionally not a column here. Do not reintroduce it without updating that decision.

### `plants`
`id`, `user_id FK`, `name nullable`, `species_id FK nullable`, `status`, `current_health_status`, `main_image_id nullable`, `notes`, `archived_at`, `created_at`, `updated_at`.

**Amended during implementation (MVP), per FINAL §37:** `name` is nullable until confirmation —
the Add Plant flow creates the plant before the user names it (§3 step 5 comes after confirm) —
with a CHECK rejecting a blank string, so "not yet named" is unambiguously null. CHECK
`plants_archived_at_matches_status` keeps `status = 'ARCHIVED'` and a non-null `archived_at` in
agreement in both directions. `species_id` uses ON DELETE RESTRICT so a species can never vanish
from under a user's plant. Users have no DELETE policy: archive is the normal action (§21).

Plant name is the user's personal name and is independent of Species.

### `plant_environments`
One current row per plant: `id`, `plant_id UNIQUE`, `location_type`, `light_level`, `light_direction`, `temperature_c`, `humidity_percent`, `room`, `notes`, timestamps.

### `plant_images`
Metadata only; binaries are in Storage:
`id`, `user_id`, `plant_id`, `storage_path_original`, `storage_path_processed`, `storage_path_thumbnail`, `mime_type`, `size_bytes`, `width`, `height`, `context_type`, `user_visible`, `ai_used`, `retention_reason`, `created_at`.

Allowed: JPG/JPEG/PNG/WEBP. Maximum 10 MB per image.

Storage path:
`plant-images/{user_id}/{plant_id}/{gallery|identification|health}/`

AI-used images requested for removal are hidden from the user but retained for history/audit and Admin access only.

## Identification
### `identifications`
`id`, `user_id`, `plant_id`, `agent_request_id`, `status`, `method`, `primary_species_id`, `confidence_score`, `confidence_level`, `image_quality`, `user_description`, `request_more_photos`, `wikipedia_url`, `raw_result`, `created_at`.

**Amended during implementation (MVP), per FINAL §37:**

- `method` (`identification_method`) added. The enum was already defined but no column used it;
  this is its natural home, distinguishing an AI result from a user confirmation or correction.
- `confidence_score` is `numeric(4,3)`, fixing the A18 scale at 0.000-1.000. A caller emitting a
  percentage (85 rather than 0.85) overflows the type and fails loudly instead of being silently
  truncated. `confidence_level` is derived from the score in Python, never from model output.
- CHECK `identifications_failure_carries_no_verdict`: a row whose `status` is not `SUCCESS`
  cannot carry `primary_species_id` or `confidence_level`. This makes §25 ("AI failure never
  creates an authoritative record") a database guarantee rather than a convention the
  orchestration layer must remember.
- CHECK `identifications_wikipedia_url_shape`: the URL must match `^https://<lang>.wikipedia.org/`,
  so an invented or relative value is rejected outright (§8: the URL must never be invented).
- Users have SELECT and INSERT only, no UPDATE or DELETE. Identification history is
  append-oriented; a correction creates a new row.

### `identification_candidates`
`id`, `identification_id`, `species_id nullable`, `scientific_name`, `common_name`, `rank` (1–3), `confidence_score`, `created_at`.

**Amended during implementation (MVP), per FINAL §37:** `species_id` is nullable and the raw
names are stored alongside it. Candidates come straight from model output, so materialising a
`species` row for each would let every low-confidence hallucinated binomial permanently pollute
the global taxonomy table. The species is created only at confirm time, from the candidate the
user actually chose. `UNIQUE (identification_id, rank)` enforces one primary plus at most two
alternatives.

Identification Agent never directly changes `plants.species_id`; confirmation is an application/orchestration action.

## Species & Knowledge
### `species`
`id`, `scientific_name`, `normalized_name UNIQUE`, `common_name`, `family`, `genus`, timestamps. MVP is Species-only; Cultivar is future.

**Amended during implementation (MVP), per FINAL §37:** uniqueness moved from `scientific_name`
to `normalized_name` (A23). `normalize_scientific_name()` lowercases, collapses whitespace,
strips parenthetical and trailing authorship, and preserves infraspecific ranks, so
`Monstera deliciosa`, `monstera deliciosa` and `Monstera deliciosa Liebm.` resolve to one row
and therefore one Knowledge lineage. Without this the "existing species reuses published
Knowledge" journey in §34 silently forks. A trigger computes the column, so a client cannot
supply its own value. `genus` is derived from the normalised name when not given.

Direct writes are admin-only. The confirm-identification workflow runs under the *user's* JWT
and creates species through `upsert_species(...)`, a SECURITY DEFINER function that normalises,
deduplicates and returns the existing row when the name is known. It fills missing details but
never overwrites existing ones. The alternative — granting authenticated users blanket INSERT
on a global taxonomy table — would have let any client write arbitrary rows.

### `knowledge_drafts`
`id`, `species_id`, `language`, `status`, `initiated_by`, `research_request_id`, `content jsonb`, `research_notes`, `admin_note`, timestamps.

**Amended during implementation (MVP), per FINAL §37:** a partial unique index allows at most
one *open* draft per species and language — open meaning `DRAFT`, `RESEARCHING` or
`READY_FOR_REVIEW`. Two concurrent research runs would otherwise race to publish two versions
of the same knowledge. `REJECTED` and `FAILED` drafts deliberately do not block a retry, which
is what A17 needs: a rejected draft must leave the species retriable or plants stranded in
`KNOWLEDGE_PENDING` could never be released. Drafts are admin-only; a user's visibility into
pending research is the plant's `KNOWLEDGE_PENDING` status, not the draft.

Content sections: Identification, Description, Light, Watering, Soil, Temperature, Humidity, Fertilization, Repotting, Pruning, Propagation, Common Problems, Toxicity/Safety, Sources.

**Specified in PR 14, per FINAL §37 (A16):** `content` is `jsonb`, so the database cannot
constrain it and every consumer would otherwise guess. The recorded shape is the Pydantic
`KnowledgeContent` model in `app/agents/knowledge/contract.py`, validated when the draft is
written and again at publication:

```jsonc
{
  "sections": {
    "identification": {"text": "…", "confidence": 0.0-1.0},
    // the other twelve, all required
  },
  "sources": [
    {"source_class": "APPROVED | EXTERNAL_UNAPPROVED | AI_GENERATED_REQUIRES_VERIFICATION",
     "url": "… or null", "title": "…", "publisher": "…",
     "approved_source_id": "uuid or null", "notes": "…",
     "supports_sections": ["watering", "…"]}
  ]
}
```

Three points worth stating rather than leaving to be inferred:

- **Thirteen prose sections, not fourteen.** The list above names Sources as the fourteenth, but
  Sources is not prose — it is the provenance record, and it carries a class, a URL and a
  retrieval time that the database constrains. It therefore sits beside the sections rather than
  inside them, and becomes `knowledge_sources` rows at publication.
- **Every section is required, and none may be blank or a refusal.** A model that runs out of
  tokens mid-answer, or fills a field with "no information was found", produces a document whose
  Toxicity/Safety section is missing or meaningless — the section a user with a cat goes looking
  for. Validation fails the run instead, which is retriable.
- **`confidence` is per section and is not shown to users.** It is an admin review signal: the
  least-supported section is where a reviewer's limited time is worth spending. A single
  document-level score would average away exactly that.

**Sources live in the draft blob until approval.** `knowledge_sources` rows reference a
*published version* and are immutable, so writing them at draft time would freeze a draft's
provenance while the draft is still being revised.

### `knowledge_versions`
`id`, `species_id`, `language`, `version_number`, `content jsonb`, `source_summary jsonb`, `is_current`, `published_by`, `published_at`, `created_at`.

Published versions are immutable. Enforce one current version per species+language with a partial unique index.

**Clarified during implementation, per FINAL §37:** "immutable" means *content*-immutable, not
row-immutable. `is_current` must be able to flip to false when a newer version is published —
a row-immutable table could never demote its predecessor, making publication impossible. The
trigger therefore protects `species_id`, `language`, `version_number`, `content`,
`source_summary`, `published_by` and `published_at`, while leaving `is_current` writable.
DELETE is refused outright for everyone, since §29 says historical published versions are never
deleted. This is the same distinction already drawn for `care_plan_versions`.

`language` added per the MVP decision to store AI content in Hebrew with a language tag, so a
future English localisation publishes independently rather than needing a migration.

RLS: users read `where is_current`; **admins additionally read every version**, which the Admin
Panel's version-history view requires — without that policy a JWT-scoped admin client sees
nothing but the current row.

### `approved_sources`
`id`, `name`, `domain`, `source_type`, `reliability_level`, `notes`, `is_enabled`, `created_by`, timestamps.

### `knowledge_sources`
`id`, `knowledge_version_id`, `approved_source_id nullable`, `source_class`, `title`, `url nullable`, `publisher`, `retrieved_at`, `citation_text`, `notes`, `created_at`.

Every external claim must have a real source; unsupported AI-only content is explicitly marked `AI_GENERATED_REQUIRES_VERIFICATION`.

**Amended during implementation (MVP), per FINAL §37** — three CHECK constraints make the
provenance rules unfalsifiable rather than conventional:

- an `APPROVED` or `EXTERNAL_UNAPPROVED` row must carry a `url` matching `^https?://`, because
  by definition it represents an external claim that was fetched and verified;
- only `AI_GENERATED_REQUIRES_VERIFICATION` may lack a URL — that is what the class means;
- an `AI_GENERATED_REQUIRES_VERIFICATION` row may not reference an `approved_source_id`, so an
  unverified claim cannot masquerade as a cited one; and `APPROVED` *must* reference one, so
  only a real domain match earns that classification.

Rows are fully immutable (no UPDATE, no DELETE) and the parent version uses ON DELETE RESTRICT,
so provenance can never be orphaned.

### `knowledge_reports`
`id`, `user_id`, `plant_id nullable`, `species_id nullable`, `knowledge_version_id nullable`, `report_text`, `status`, `admin_note`, timestamps.

**Amended during implementation (MVP), per FINAL §37:** `status` is constrained to
`OPEN | REVIEWING | ACTIONED | DISMISSED`, and a CHECK requires at least one of `species_id` or
`knowledge_version_id` — a report naming nothing is unactionable. Users may INSERT and SELECT
their own reports but not UPDATE them: `status` and `admin_note` are the administrator's triage
record, not something the reporter may edit after filing.

## Care
### `care_plans`
`id`, `user_id`, `plant_id UNIQUE`, `active_version_id`, timestamps.

### `care_plan_versions`
`id`, `care_plan_id`, `version_number`, `knowledge_version_id`, `status`, `professional_recommendations jsonb`, `operational_preferences jsonb`, `change_summary`, `source_type` (`care_plan_version_source_type`), `created_by_user_id`, `created_at`.

User operational changes create a new version. Professional recommendation content is not directly editable.

`source_type` records why this version was created and is the single audit trail for version provenance; there is no separate `care_plan_changes` table (a prior draft of this schema referenced one — superseded by this field).

### `care_rules`
`id`, `care_plan_version_id`, `action_type` (`care_rule_action_type`), `interval_days`, `preferred_time_local`, `preferred_weekday`, `instructions`, `is_active`, `created_at`.

**Amended during implementation (MVP), per FINAL §37:** A7 is now a CHECK rather than a
scheduler convention - `preferred_weekday` may only be set when `interval_days % 7 = 0`.
Anchoring a weekday to a 30-day interval is incoherent, so it is rejected at write time instead
of being silently ignored later. `interval_days` is bounded to 1-365, rejecting a model that
emits nonsense such as 3650.

`interval_days` always defines the recurrence period. `preferred_weekday` is optional and only anchors *which* day of the week the recurrence should land on (e.g. `interval_days=7` with `preferred_weekday=FRIDAY`); it is never used as an alternate recurrence mode on its own.

### `care_tasks`
`id`, `user_id`, `plant_id`, `care_rule_id`, `due_at_utc`, `status`, `overdue_since`, `completed_at`, `created_at`.

Generate only relevant near-term tasks; do not pre-generate thousands of future tasks. Do not create an infinite overdue backlog.

**Amended during implementation (MVP), per FINAL §37:** a partial unique index enforces **at
most one PENDING task per rule**, so a buggy scheduler run cannot pre-generate a backlog. A task
that has gone OVERDUE is no longer PENDING, so the next recurrence can still be scheduled -
exactly the §13 behaviour. CHECKs additionally require `overdue_since` whenever status is
OVERDUE, and `completed_at` if and only if status is DONE.

### `care_events`
`id`, `user_id`, `plant_id`, `care_task_id`, `event_type`, `event_at`, `note`, `correction_of_event_id`, `created_at`.

Immutable. Corrections create new events.

**Amended during implementation (MVP), per FINAL §37:** a partial unique index allows one `DONE`
or `SKIPPED` event per task, so API_CONTRACTS' "duplicate action events are rejected" is backed
by the database rather than by a read-then-write race in application code. `MISSED` is
deliberately excluded from that index: it is written by the scheduler sweep, not the user, and
must not consume the slot a later corrective `DONE` needs. A CHECK requires
`correction_of_event_id` if and only if `event_type = 'CORRECTED'`.

## Health
### `health_assessments`
`id`, `user_id`, `plant_id`, `agent_request_id`, `overall_status`, `confidence_level`, `trend`, `user_note`, `requires_attention`, `insufficient_information_reason`, `raw_result jsonb`, `created_at`.

**Amended during implementation (MVP), per FINAL §37:** a CHECK requires
`insufficient_information_reason` whenever `overall_status = 'UNKNOWN'` - §16 says to save
UNKNOWN *with the reason*, and an unexplained UNKNOWN is indistinguishable from a bug. A second
CHECK forbids an UNKNOWN verdict from also carrying a `confidence_level`, since the two would
contradict each other on screen. `trend` is computed in Python from prior assessments (A11),
never taken from model output.

The 1-4 image rule spans rows, so it is enforced by two deferred constraint triggers rather than
a CHECK: one on `health_assessment_images` and one on `health_assessments`. Both are needed -
the image-side trigger alone never fires when an assessment is written with no images at all,
which is the likelier bug.

### `health_assessment_images`
Composite PK `(health_assessment_id, plant_image_id)`, plus `display_order`, `created_at`. MVP: 1–4 images.

### `health_observations`
`id`, `health_assessment_id`, `observation_text`, `confidence_level`, `created_at`.

### `health_issues`
`id`, `health_assessment_id`, `issue_name`, `severity`, `confidence_level`, `evidence`, `created_at`. Use possible-issue language, never definitive diagnosis.

### `health_recommendations`
`id`, `health_assessment_id`, `recommendation_text`, `priority`, `requires_care_plan_adjustment`, `created_at`.

`requires_care_plan_adjustment` is a flag only. The Health Agent cannot modify a Care Plan; it
raises a proposal through the Care Agent, which the user must approve (FINAL §12).

### `health_assessment_sources`
`id`, `health_assessment_id`, `source_class`, `title`, `url nullable`, `publisher`, `retrieved_at`, `citation_text`, `created_at`.

**Added during implementation (MVP), per FINAL §37:** FINAL §16 lists `sources` as a required
output field of a `HealthAssessment`, and DEVELOPMENT_PROGRESS §16 has a "Sources" item, but
this document defined no table to hold them. Mirrors `knowledge_sources`, reuses the same
deterministic verification pipeline, and carries the same CHECK: an external claim must supply
the URL that was actually fetched, and only `AI_GENERATED_REQUIRES_VERIFICATION` may lack one.
Immutable, like its parent assessment.

Every successful Health Check updates the plant's current health status; historical assessments remain unchanged.

## AI infrastructure
### `agent_requests`
`id`, `user_id`, `plant_id`, `agent_type`, `status`, `stage`, `idempotency_key`, `request_fingerprint`, `input_summary jsonb`, `output_summary jsonb`, `error_code`, timestamps.

**Amended during implementation (MVP), per FINAL §37:** `stage` added, constrained to the UI
progression `IMAGES_RECEIVED -> CONTEXT_LOADED -> ANALYZING -> PREPARING_RESULT -> COMPLETE`
that API_CONTRACTS specifies for the 202-poll pattern. `request_fingerprint` added for A24: it
holds a hash of the request body, so a repeated `Idempotency-Key` carrying a *different* payload
can be distinguished from a genuine retry and answered with 409. Uniqueness on
`(user_id, idempotency_key)` is scoped per user, since keys are client-generated and will
collide across users.

**Corrected in PR 13, per FINAL §37 (migration `0011`):** `agent_requests` was given a SELECT
policy for the owner and an ALL policy for administrators, and **no INSERT policy for anyone
else** - so no user could start an AI request at all. The rule below reads "AI monitoring is
Admin-only except minimal request status for the request owner", which governs *reading*; it is
silent on who creates the row, and the row is created by the user, when they press the button.
The gap was invisible until identification was wired end to end, because nothing before that had
created one of these rows through a user's client. The added policy admits an INSERT only when
`user_id = auth.uid()`, the `plant_id` is null or the caller's own plant, and `status = 'QUEUED'`:
a user starts work but does not get to declare it finished. There is deliberately still **no
UPDATE policy** - `status` and `stage` after `QUEUED` are written by the background task through
the service role, so a client cannot fabricate a `SUCCEEDED` request carrying an invented result.

### `agent_executions`
`id`, `agent_request_id`, `agent_type`, `model`, `model_version`, `prompt_version`, `status`, `attempt`, `started_at`, `completed_at`, `input_tokens`, `output_tokens`, `estimated_cost`, `latency_ms`, `error_code`, `error_message`, `created_at`.

Do not store chain-of-thought. The column list is deliberately closed and carries no free-text
field for model reasoning, raw prompts or raw responses; `error_message` exists for a provider
error string, not for transcripts.

**Amended during implementation (MVP), per FINAL §37:** `attempt` added and CHECKed to 1-3. §23
caps structured-output retries at 2, so a request can produce at most three attempts; a fourth
means the ceiling was bypassed. Read access is admin-only - model, cost and prompt version are
not user-facing.

## Notifications
### `notification_preferences`
`user_id PK`, `email_enabled`, `preferred_time_local`, `daily_digest`, timestamps.

Created by the same `auth.users` insert trigger that creates `profiles`, with defaults
`email_enabled = true`, `preferred_time_local = '08:00'`, `daily_digest = true` (matching
the Settings wireframe). A user must never exist without a preferences row, or
`GET /v1/notification-preferences` and the scheduler tick are undefined for a new account.
For that reason this table is created in the foundation migration alongside `profiles`,
not with the other notification tables.

### `notification_deliveries`
`id`, `user_id`, `care_task_id nullable`, `channel`, `status`, `dedupe_key UNIQUE`, `scheduled_at`, `sent_at`, `provider_message_id`, `error_message`, `created_at`.

Use idempotency/unique logical notification keys to prevent duplicate sends.

**Amended during implementation (MVP), per FINAL §37:** this document mandated duplicate-send
prevention but defined no column for it (A12). `dedupe_key` is `text UNIQUE`, formatted
`{scope}:{identifier}:{local_date}` - for example `digest:<user_id>:2026-09-05` or
`task:<care_task_id>:reminder`. The date component is the **local** date of the recipient, so
changing timezone cannot produce two sends on one local day. A duplicate fails on insert, before
any provider call, so re-running the scheduler tick is safe.

### `admin_audit_log`
`id`, `admin_user_id`, `action`, `target_table`, `target_id`, `payload jsonb`, `created_at`.

**Added during implementation (MVP), per FINAL §37:** §27 said "audit records as required" and
§29 requires consequential admin actions to be audited, but no table was defined (A12). `action`
is free text, deliberately not an enum: an enum would force a migration for every new
administrative action, and an audit log must never block a feature. Append-only **including for
administrators** - an audit trail an admin can edit is not an audit trail. Admin-read;
service-role write.

## System history
### `system_events`
Immutable generic events: `id`, `user_id nullable`, `plant_id nullable`, `event_type`, `payload jsonb`, `created_at`.

Since `plant_environments` keeps only one current row per plant, every environment update must also write a `system_events` row (`event_type = ENVIRONMENT_CHANGED`, `payload` = old/new values) so that Plant History (FINAL_SPECIFICATION §19) has something to render. There is no separate environment-history table in MVP.

## Minimum indexes
```sql
create index idx_plants_user_status on plants(user_id, status);
create index idx_plants_user_health on plants(user_id, current_health_status);
create index idx_plant_images_plant on plant_images(plant_id, created_at desc);
create index idx_identifications_plant on identifications(plant_id, created_at desc);
create index idx_knowledge_drafts_status on knowledge_drafts(status, updated_at desc);
create index idx_knowledge_versions_species on knowledge_versions(species_id, version_number desc);
create index idx_care_tasks_user_due on care_tasks(user_id, due_at_utc, status);
create index idx_care_events_plant on care_events(plant_id, event_at desc);
create index idx_health_assessments_plant on health_assessments(plant_id, created_at desc);
create index idx_agent_requests_status on agent_requests(status, created_at);
create index idx_agent_executions_agent on agent_executions(agent_type, created_at desc);
create index idx_notification_deliveries_schedule on notification_deliveries(status, scheduled_at);
```

## RLS model
- User-owned rows: only when `user_id = auth.uid()`.
- Child rows without `user_id`: authorize through owning Plant/Profile.
- Regular users: read published Knowledge only.
- Admins: manage Knowledge Drafts, Published Knowledge, Approved Sources, Reports and AI monitoring.
- AI monitoring is Admin-only except minimal request status for the request owner.
- Storage policies enforce owner access for visible images and Admin-only access to retained hidden AI-history images.
- RLS is the real database security boundary; Python checks are not sufficient.

## Account deletion
An account is anonymized rather than physically deleted: disable access, remove identifying profile fields, set `anonymized_at`, preserve anonymized history, and restrict it to Admin access.
