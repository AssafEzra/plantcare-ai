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
`id`, `user_id FK`, `name`, `species_id FK nullable`, `status`, `current_health_status`, `main_image_id nullable`, `notes`, `archived_at`, `created_at`, `updated_at`.

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
`id`, `user_id`, `plant_id`, `agent_request_id`, `status`, `primary_species_id`, `confidence_score`, `confidence_level`, `image_quality`, `user_description`, `request_more_photos`, `wikipedia_url`, `raw_result`, `created_at`.

### `identification_candidates`
`id`, `identification_id`, `species_id`, `rank` (1–3), `confidence_score`, `created_at`.

Identification Agent never directly changes `plants.species_id`; confirmation is an application/orchestration action.

## Species & Knowledge
### `species`
`id`, `scientific_name UNIQUE`, `common_name`, `family`, `genus`, timestamps. MVP is Species-only; Cultivar is future.

### `knowledge_drafts`
`id`, `species_id`, `status`, `initiated_by`, `research_request_id`, `content jsonb`, `research_notes`, `admin_note`, timestamps.

Content sections: Identification, Description, Light, Watering, Soil, Temperature, Humidity, Fertilization, Repotting, Pruning, Propagation, Common Problems, Toxicity/Safety, Sources.

### `knowledge_versions`
`id`, `species_id`, `version_number`, `content jsonb`, `source_summary jsonb`, `is_current`, `published_by`, `published_at`, `created_at`.

Published versions are immutable. Enforce one current version per species with a partial unique index.

### `approved_sources`
`id`, `name`, `domain`, `source_type`, `reliability_level`, `notes`, `is_enabled`, `created_by`, timestamps.

### `knowledge_sources`
`id`, `knowledge_version_id`, `approved_source_id nullable`, `source_class`, `title`, `url nullable`, `publisher`, `retrieved_at`, `citation_text`, `notes`, `created_at`.

Every external claim must have a real source; unsupported AI-only content is explicitly marked `AI_GENERATED_REQUIRES_VERIFICATION`.

### `knowledge_reports`
`id`, `user_id`, `plant_id nullable`, `species_id nullable`, `knowledge_version_id nullable`, `report_text`, `status`, `admin_note`, timestamps.

## Care
### `care_plans`
`id`, `user_id`, `plant_id UNIQUE`, `active_version_id`, timestamps.

### `care_plan_versions`
`id`, `care_plan_id`, `version_number`, `knowledge_version_id`, `status`, `professional_recommendations jsonb`, `operational_preferences jsonb`, `change_summary`, `source_type` (`care_plan_version_source_type`), `created_by_user_id`, `created_at`.

User operational changes create a new version. Professional recommendation content is not directly editable.

`source_type` records why this version was created and is the single audit trail for version provenance; there is no separate `care_plan_changes` table (a prior draft of this schema referenced one — superseded by this field).

### `care_rules`
`id`, `care_plan_version_id`, `action_type`, `interval_days`, `preferred_time_local`, `preferred_weekday`, `instructions`, `is_active`, `created_at`.

`interval_days` always defines the recurrence period. `preferred_weekday` is optional and only anchors *which* day of the week the recurrence should land on (e.g. `interval_days=7` with `preferred_weekday=FRIDAY`); it is never used as an alternate recurrence mode on its own.

### `care_tasks`
`id`, `user_id`, `plant_id`, `care_rule_id`, `due_at_utc`, `status`, `overdue_since`, `completed_at`, `created_at`.

Generate only relevant near-term tasks; do not pre-generate thousands of future tasks. Do not create an infinite overdue backlog.

### `care_events`
`id`, `user_id`, `plant_id`, `care_task_id`, `event_type`, `event_at`, `note`, `correction_of_event_id`, `created_at`.

Immutable. Corrections create new events.

## Health
### `health_assessments`
`id`, `user_id`, `plant_id`, `agent_request_id`, `overall_status`, `confidence_level`, `trend`, `user_note`, `requires_attention`, `insufficient_information_reason`, `raw_result jsonb`, `created_at`.

### `health_assessment_images`
Composite PK `(health_assessment_id, plant_image_id)`, plus `display_order`, `created_at`. MVP: 1–4 images.

### `health_observations`
`id`, `health_assessment_id`, `observation_text`, `confidence_level`, `created_at`.

### `health_issues`
`id`, `health_assessment_id`, `issue_name`, `severity`, `confidence_level`, `evidence`, `created_at`. Use possible-issue language, never definitive diagnosis.

### `health_recommendations`
`id`, `health_assessment_id`, `recommendation_text`, `priority`, `requires_care_plan_adjustment`, `created_at`.

Every successful Health Check updates the plant's current health status; historical assessments remain unchanged.

## AI infrastructure
### `agent_requests`
`id`, `user_id`, `plant_id`, `agent_type`, `status`, `idempotency_key`, `input_summary jsonb`, `output_summary jsonb`, `error_code`, timestamps.

### `agent_executions`
`id`, `agent_request_id`, `agent_type`, `model`, `model_version`, `prompt_version`, `status`, `started_at`, `completed_at`, `input_tokens`, `output_tokens`, `estimated_cost`, `latency_ms`, `error_code`, `error_message`, `created_at`.

Do not store chain-of-thought.

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
`id`, `user_id`, `care_task_id nullable`, `channel`, `status`, `scheduled_at`, `sent_at`, `provider_message_id`, `error_message`, `created_at`.

Use idempotency/unique logical notification keys to prevent duplicate sends.

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
