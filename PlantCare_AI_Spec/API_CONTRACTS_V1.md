# PlantCare AI — API_CONTRACTS.md

## Architecture
```text
Streamlit → FastAPI → Orchestration/Domain Services
                    ├→ Supabase Auth
                    ├→ Supabase PostgreSQL/Storage
                    ├→ NotificationService → EmailProvider → Resend
                    └→ AI Gateway → configurable AI Provider(s)
```

Agents never call each other directly.

Base path: `/v1`

Authentication:
`Authorization: Bearer <supabase_access_token>`

The server derives ownership from the JWT.

## Standard responses
Success:
```json
{"data": {}, "request_id": "uuid"}
```

Error:
```json
{"error":{"code":"PLANT_NOT_FOUND","message":"Plant was not found.","details":{}},"request_id":"uuid"}
```

Statuses: 200, 201, 202, 400, 401, 403, 404, 409, 413, 422, 429, 500, 503.

AI-triggering POST endpoints accept `Idempotency-Key`.

## Profile
`GET /v1/me`

`PATCH /v1/me`
```json
{"display_name":"My Name","timezone":"Asia/Jerusalem"}
```
(`care_level` is out of MVP scope — see FINAL_SPECIFICATION §2, §36 — and is not accepted here.)

## Plants
`POST /v1/plants`
```json
{"name":"המונסטרה בסלון","notes":"קיבלתי אותה במתנה"}
```
Creates `PENDING_IDENTIFICATION`.

`GET /v1/plants?status=ACTIVE&health_status=NEEDS_ATTENTION&q=monstera`

`GET /v1/plants/{plant_id}` — complete Plant Dashboard view model.

`PATCH /v1/plants/{plant_id}` — personal fields such as `name`, `notes`.

`POST /v1/plants/{plant_id}/archive`

`POST /v1/plants/{plant_id}/restore`

Manual Species selection is not supported in MVP.

## Environment
`GET /v1/plants/{plant_id}/environment`

`PUT /v1/plants/{plant_id}/environment`
```json
{
  "location_type":"Indoor",
  "light_level":"Bright",
  "light_direction":"East",
  "temperature_c":24,
  "humidity_percent":55,
  "room":"Living Room",
  "notes":"Morning light"
}
```
All environment fields are optional.

## Images
`POST /v1/plants/{plant_id}/images` — multipart upload.

Rules: JPG/JPEG/PNG/WEBP; maximum 10 MB each; validate → process/resize/compress → Storage.

`DELETE /v1/plants/{plant_id}/images/{image_id}` — normal images may be removed/hidden; AI-used retained images are hidden rather than physically removed.

## Identification
`POST /v1/plants/{plant_id}/identification-runs`
```json
{"image_ids":["uuid","uuid"],"user_description":"נראה לי שזו מונסטרה"}
```
Returns `202` with `agent_request_id`.

`GET /v1/agent-requests/{request_id}` returns `QUEUED | PROCESSING | SUCCEEDED | FAILED` plus stage.

Suggested UI stages:
`IMAGES_RECEIVED → CONTEXT_LOADED → ANALYZING → PREPARING_RESULT → COMPLETE`.

`GET /v1/identifications/{identification_id}` returns primary candidate, up to two alternatives, confidence, image quality, request-more-photos flag and verified Wikipedia URL when available.

`POST /v1/identifications/{identification_id}/confirm`
```json
{"confirmed_species_id":"uuid"}
```

Orchestration:
- published Knowledge exists → `ACTIVE`;
- otherwise create Species if necessary, create Knowledge Draft, queue research, set plant `KNOWLEDGE_PENDING`.

`POST /v1/identifications/{identification_id}/correct`

(Aligned to the flat `/v1/identifications/{identification_id}` convention already used by `confirm` and `GET`; ownership is still derived from the JWT plus the identification's `plant_id`, so no `plant_id` path segment is needed.)

Creates historical correction; user confirmation is required before updating the plant. A Species change triggers a new Care Plan proposal.

## Knowledge
`GET /v1/species/{species_id}/knowledge` — current published version for regular users.

`POST /v1/species/{species_id}/knowledge-reports`
```json
{"plant_id":"uuid","report_text":"המידע על ההשקיה נראה לי לא נכון."}
```

Admin:
```text
GET  /v1/admin/knowledge-drafts
GET  /v1/admin/knowledge-drafts/{draft_id}
POST /v1/admin/knowledge-drafts/{draft_id}/approve
POST /v1/admin/knowledge-drafts/{draft_id}/reject
POST /v1/admin/knowledge-drafts/{draft_id}/retry
GET  /v1/admin/knowledge-versions/{species_id}
GET  /v1/admin/approved-sources
POST /v1/admin/approved-sources
PATCH /v1/admin/approved-sources/{source_id}
POST /v1/admin/approved-sources/{source_id}/disable
```

Approval creates an immutable Published Knowledge Version.

## Care Plans
`GET /v1/plants/{plant_id}/care-plan`

`POST /v1/plants/{plant_id}/care-plan/proposals`
```json
{"reason":"INITIAL_PLAN"}
```
`reason` is one of `care_plan_version_source_type`: `INITIAL_PLAN | OPERATIONAL_ADJUSTMENT | ENVIRONMENT_CHANGE | HEALTH_DRIVEN | RE_IDENTIFICATION`. This value is carried onto the resulting `care_plan_versions.source_type`. Returns 202.

`GET /v1/plants/{plant_id}/care-plan/proposals`

`POST /v1/care-plan-proposals/{proposal_id}/approve`

`POST /v1/care-plan-proposals/{proposal_id}/reject`

`POST /v1/plants/{plant_id}/care-plan/adjustment-proposals`
```json
{"health_assessment_id":"uuid","reason":"Potential overwatering adjustment"}
```

`POST /v1/care-plan-versions/{version_id}/operational-adjustment`
```json
{
  "operational_preferences":{"watering_frequency_days":7,"preferred_time_local":"08:00"},
  "change_summary":"Changed watering preference."
}
```
Creates a new version. Professional recommendations cannot be overwritten through this endpoint.

## Care Tasks
`GET /v1/care-tasks?date=today&status=pending`

`POST /v1/care-tasks/{task_id}/done`

`POST /v1/care-tasks/{task_id}/skip`

Done/Skip creates an immutable Care Event and advances scheduling. Duplicate action events are rejected.

## Health
`POST /v1/plants/{plant_id}/health-assessments`
```json
{"image_ids":["uuid","uuid"],"user_note":"העלים החדשים מצהיבים"}
```
Rules: 1–4 images, at least one required, images must belong to the plant/user. Returns 202.

`GET /v1/health-assessments/{assessment_id}`

`GET /v1/plants/{plant_id}/health-history`

Insufficient evidence produces `UNKNOWN` with a reason. Health results use possible-issue language, not definitive diagnosis.

## Dashboard
`GET /v1/dashboard`

Example:
```json
{
  "data":{
    "today_care":[],
    "plants_needing_attention":[],
    "my_plants":[],
    "counts":{"today_tasks":0,"attention":0,"active_plants":0}
  },
  "request_id":"uuid"
}
```

Designed to render Home without many sequential calls.

## Notifications
`GET /v1/notification-preferences`

`PUT /v1/notification-preferences`
```json
{"email_enabled":true,"preferred_time_local":"08:00","daily_digest":true}
```

MVP channel is Email.

`GET /v1/notification-deliveries`

## Admin monitoring
Admin-only:
```text
GET /v1/admin/agent-executions
GET /v1/admin/agent-requests
GET /v1/admin/knowledge-reports
GET /v1/admin/notification-deliveries
```

Expose model, prompt version, duration, token usage and estimated cost. Never expose chain-of-thought.

## AI failure contract
Structured output is schema-validated. Invalid output gets up to 2 automatic retries, then a failed execution is recorded and no authoritative record is created.

| Agent | Failure |
|---|---|
| Identification | NEEDS_MORE_INFORMATION / FAILED |
| Knowledge | incomplete/failed draft; Admin retry |
| Care | ask for missing context or qualify proposal |
| Health | UNKNOWN with reason |

## Security
JWT verification + RLS. Never trust client `user_id` or `role`. Rate-limit AI endpoints. Provider secrets stay server-side.
