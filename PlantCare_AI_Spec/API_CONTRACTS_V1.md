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

It also returns **`output_summary`** — where the result landed (added in PR 23).
A client that polls until `SUCCEEDED` holds an `agent_request_id` and nothing
else, and there is no route from a plant to its identification, so without this
field the confirmation screen is unreachable. It shipped without it and the Add
Plant flow dead-ended at "the identification was not found"; a journey test walking
the client's own path is what found it.

The column holds identifiers and statuses only — each workflow writes a small
explicit dict (`identification_id`, `care_plan_version_id`, `health_assessment_id`,
version numbers, an overall status). No prompt and no reasoning reaches it, which
is why exposing it to the request's owner does not weaken the rule that keeps
`agent_executions` admin-only.

`GET /v1/identifications/{identification_id}` returns primary candidate, up to two alternatives, confidence, image quality, request-more-photos flag and verified Wikipedia URL when available.

`POST /v1/identifications/{identification_id}/confirm`
```json
{"candidate_id":"uuid","name":"מונסטרה של דנה"}
```

**Amended in PR 13** (`FINAL_SPECIFICATION §37`). The payload was
`{"confirmed_species_id":"uuid"}`, which presumes a `species` row already exists
for every candidate. It must not: materialising a species per candidate would let
every low-confidence hallucinated binomial permanently enter a taxonomy table
shared by all users, and two of the three candidates on a typical identification
are wrong by construction. The candidate carries the raw `scientific_name` and
`common_name`; the species row is created — or matched, on `normalized_name` — at
confirmation, from the candidate the user actually chose. `name` is optional; when
absent the plant takes the candidate's common name (A2: `plants.name` is nullable
only until this point).

Orchestration:
- published Knowledge exists for `(species_id, language)` → `IDENTIFIED` → `ACTIVE`;
- otherwise create Species if necessary, create Knowledge Draft, queue research,
  plant goes `IDENTIFIED` → `KNOWLEDGE_PENDING`.

The plant passes **through `IDENTIFIED`** rather than jumping from
`PENDING_IDENTIFICATION` to its destination. `FINAL_SPECIFICATION §7` and
`TESTING_STRATEGY §3` both model `IDENTIFIED` as a real state, and the lifecycle
table refuses the skip. **Amended in PR 13:** the workflow walks the path.

**Re-identification of an already-`ACTIVE` plant (A21, resolved in PR 13).** The
plant keeps its current status and its live plan while the new species is
researched — it does not regress to `KNOWLEDGE_PENDING`, and outstanding tasks are
not cancelled. Regressing would silence a working care schedule for a plant whose
care needs have not changed just because its label did. A care-plan proposal is
raised when the new knowledge publishes.

**Confidence (A18, resolved in PR 13).** `confidence_score` is `0.000`–`1.000` with
three decimal places. `confidence_level` is **derived in Python**, never taken from
the model: `HIGH >= 0.85`, `MEDIUM >= 0.60`, otherwise `LOW`. A model asked to
self-report a label picks the one that sounds right for its answer rather than the
one its evidence supports; a number it must commit to first, and a threshold it
does not know, keep the two independent.

`POST /v1/identifications/{identification_id}/correct`
```json
{"scientific_name":"Monstera adansonii","note":"החורים בעלים"}
```

**Specified in PR 13** (A13) — the endpoint was listed with no request body. At least
one of `scientific_name` (a name the user supplies themselves) or `note` (free text)
is required; a correction that says nothing is not a correction. Choosing an
alternative the agent already offered is not a correction at all — that is
`confirm` with a different `candidate_id`, which is why no `candidate_id` is
accepted here.

A correction is **history only**: it appends an identification row with method
`USER_CORRECTED` and status `NEEDS_MORE_INFORMATION`, and never mutates the row it
corrects. It does not move the plant — `FINAL_SPECIFICATION §8` requires a
confirmation for that, and the status CHECK enforces it, since a row that is not
`SUCCESS` may carry no species.

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

**Specified in PR 15, per FINAL §37**

*Approval is one database transaction*, not six API calls. It demotes the previous current
version, inserts the new one at `max(version_number) + 1`, writes its `knowledge_sources` rows,
marks the draft `APPROVED`, releases the plants waiting on it, and writes the audit entry — all
or none. The ordering is forced by the partial unique index on `(species_id, language) where
is_current`: demote-then-insert is the only sequence it permits, and a failure between the two
would leave a species with **no** current version, so every plant of that species would suddenly
be unable to find its knowledge. The function is `publish_knowledge_draft()` (migration 0012).

```jsonc
// POST /v1/admin/knowledge-drafts/{draft_id}/approve
{"admin_note": "optional"}
// -> {"version_id", "species_id", "language", "version_number",
//     "source_summary": {"total", "approved", "unapproved", "unverified"},
//     "active_plants"}
```

*Rejection requires a reason.* `POST .../reject` takes `{"admin_note": "..."}` and the note is
mandatory: without one the retry has nothing to address and the audit entry records only that
somebody said no. Rejection changes **no plant** — they stay `KNOWLEDGE_PENDING` and the species
stays retriable, which is A17.

*Retry* (`POST .../retry`, optional `{"reason": "..."}`) returns `202` with an
`agent_request_id`. The reason is passed to the agent, so a retry after a rejection can address
the objection rather than reproduce it.

*The fan-out (A4).* Publication moves every plant of that species from `KNOWLEDGE_PENDING` to
`ACTIVE`. Restricted to that status on purpose: an `ARCHIVED` plant is not silently revived, and
an already-`ACTIVE` one (A21 re-identification) is not disturbed. The queued `INITIAL_PLAN` care
proposal that A3 calls for is **not** created here — the Care Agent arrives in PR 16, and a
`QUEUED` request nothing can execute would be worse than none. PR 16 adds it at this same point
and backfills plants released before it existed.

*Disabling an approved source does not rewrite history.* It stops the domain conferring
`APPROVED` on future research; existing `knowledge_sources` rows are untouched, because they
record what was true when a version was published. For the same reason a source's `domain` is
not editable — changing it would silently reclassify every immutable row pointing at it. A
different domain is a different source: add it, and disable the old one.

*Every admin route is refused to a regular user with `403`,* and every admin table also carries
an `is_admin()` RLS policy. The dependency produces the clean error; the policy is what makes a
forgotten dependency a non-event rather than a breach.

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

**Specified in PR 16, per FINAL §37**

*The payload has no `professional_recommendations` field and rejects one.* "Cannot be
overwritten" is a product rule in §12; `extra: forbid` makes it a `422`, so a client that sends
new advice alongside a frequency change is refused rather than quietly ignored. The
recommendations are copied **byte-identical** from the source version - not regenerated, and no
model is called, because an operational edit is deterministic and giving a model the opportunity
would be giving it the opportunity to rewrite the advice.

*`operational_preferences` is keyed by action type*, so changing one rule leaves the others
alone: `{"WATERING": {"interval_days": 10}}`. A key naming an action the plan does not have is
ignored - adding an action is a plan change, which is a proposal, not an adjustment.

*An adjustment produces a PROPOSED version, not an active one.* The user still approves it. The
version chain is the audit trail, and letting an operational tweak be the one way to change the
active plan without saying yes to it would put a hole in it.

*Approval is one database transaction* (`activate_care_plan_version()`, migration 0013): the
previous version is superseded, the new one activated, `care_plans.active_version_id` repointed,
and the old version's **PENDING** tasks cancelled (A5). The partial unique index allows one
ACTIVE version per plan, so supersede-then-activate is the only legal ordering, and a failure
between the two would leave the plant with no active plan - which is how a plant silently stops
being cared for. `DONE`, `SKIPPED` and `OVERDUE` tasks are untouched: they record what happened,
and a new plan does not change the past.

*A proposal is refused while one is already open.* Two open proposals is a choice the user did
not ask to make, and approving one would silently orphan the other.

*`reason: OPERATIONAL_ADJUSTMENT` is not accepted by the proposals endpoint.* It is the one
source type a user creates directly, and it has its own route.

*A20 - missing context.* A proposal may carry `missing_context`: facts that would have made the
plan better, rendered on the card as information. They are **not questions**; the MVP has no
status, table or endpoint that could carry an answer back, and phrasing them as questions would
promise a conversation that cannot happen. The plan is produced regardless.

## Care Tasks
`GET /v1/care-tasks?date=today&status=pending`

`POST /v1/care-tasks/{task_id}/done`

`POST /v1/care-tasks/{task_id}/skip`

Done/Skip creates an immutable Care Event and advances scheduling. Duplicate action events are rejected.

**Specified in PR 17, per FINAL §37**

*`date=today` means the **user's** today.* Jerusalem is ahead of UTC, so reading the UTC date
would show yesterday's work for the first three hours of every morning. Overdue tasks from
earlier days stay on today's list — they are what the user still has to do, and filtering them
out by date is how a task gets quietly forgotten.

*The 409 comes from a unique index,* not a read-then-check: `care_events_one_action_per_task`
admits one DONE or SKIPPED per task, so two taps on a slow connection cannot both succeed.

*What the next occurrence counts from (A8)* — the specification does not say, and the answers
behave differently enough that either guess would be a bug:

| Event | Anchor | Why |
|---|---|---|
| `DONE` | when it actually happened | Watered on Thursday, next watering seven days from Thursday. Anchoring on the due date compounds lateness into a schedule the user never agreed to |
| `SKIPPED` | the original due date | Skipping says "not this time", not "restart the clock". Otherwise a user could postpone indefinitely and the rhythm would drift |
| `MISSED` | when it was written off | **Not** its long-past due date: that puts the next occurrence in the past too, the sweep retires it as expired as well, and the scheduler writes a MISSED event on every tick forever |

*Overdue and its end (A9).* A past-due task becomes `OVERDUE`. After
`min(interval_days, 14)` days it stops being actionable: a `MISSED` event records the history and
the task is `CANCELLED`, so the next recurrence can be scheduled. Bounding by the rule's own
interval keeps the window proportional — a daily task a fortnight late is meaningless, a monthly
one at a week is still worth doing.

## Internal

`POST /v1/internal/tick`

The only route with no user behind it. A cron job authenticates with the
`X-Internal-Secret` header, compared with `hmac.compare_digest`, and a wrong or missing secret
gets the same `403` as any other forbidden request — an endpoint that says "wrong secret" tells a
prober it found the right endpoint. It runs under the service role because it works across every
user's plants.

**Idempotent by construction.** Materialisation skips any rule that already has a pending task,
and a partial unique index refuses a second one regardless, so running the tick three times in a
minute leaves exactly the state one run would. That is the difference between a reminder and a
duplicate reminder, and it is asserted directly rather than assumed.

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

**Specified in PR 19, per FINAL §37**

*A10 — two "preferred times", and what each governs.* A care rule has a
`preferred_time_local` and so does a notification preference, and the specification never says
how they relate:

- the **rule's** time is when a task is *due* — "water at 08:00";
- the **preference's** time is when we are allowed to *write* — "tell me at 07:00".

They answer different questions. A user who waters in the evening still wants a morning reminder,
and a user with six plants wants one message at a time they choose rather than six at whatever
hours their rules happen to specify. The Settings help text says which is which, because a user
who confuses them gets reminders they did not ask for.

*The send window is a window, not an instant.* The tick runs every fifteen minutes and can be
late; a reminder requiring the clock to land exactly on 08:00 would silently not arrive on a day
a deploy overlapped it. Once the hour has passed the dedupe key is what stops the open window
sending twice.

*Duplicate prevention is an ordering, not a check.* The `notification_deliveries` row is inserted
**before** the provider is called, and `dedupe_key` carries a unique index — so a second attempt
fails on the insert and never reaches Resend. The obvious alternative (look, send, record) has a
window in which two ticks both pass the read and the user gets two emails. The worst case here is
a row stuck in `QUEUED`, not a duplicate message.

Key formats: `digest:<user_id>:<local_date>` and `task:<care_task_id>:reminder`. The digest key
carries the user's **local** date, so changing timezone cannot yield two digests on one of their
days. The task key carries no date at all — a task overdue for a week belongs in the digest, not
in a fresh email every morning, and `FINAL §14` lists missed-reminder emails as Future.

*`daily_digest` is honoured as the preference it is.* `true` sends one message for the day;
`false` sends one per task. The plan's first draft chose by task count, which made the user's
setting inert.

*A failed send is recorded, never swallowed* (`FINAL §30`), and the task is untouched — still
outstanding, still on the dashboard. It is not retried the same day: hammering a provider that is
refusing is a good way to lose an account, and the digest returns tomorrow.

## Admin monitoring
Admin-only:
```text
GET  /v1/admin/overview
GET  /v1/admin/agent-executions
GET  /v1/admin/agent-requests
GET  /v1/admin/knowledge-reports
POST /v1/admin/knowledge-reports/{id}/review
GET  /v1/admin/notification-deliveries
GET  /v1/admin/audit-log
GET  /v1/admin/accounts
POST /v1/admin/accounts/{user_id}/anonymize
```

Expose model, prompt version, duration, token usage and estimated cost. Never expose chain-of-thought.

`agent_executions` has no column for prompts or reasoning, so the monitoring view cannot
leak them however it is queried. That is the enforcement; the sentence above is the intent.

`/overview` is ordered by what would make an administrator act — failures first, then the
queues waiting on a human, then volume — not by table.

`review` records triage on a reported knowledge error (`status`, `admin_note`). It does
**not** start research: acting on a report is the existing draft-retry route, and that
research may already be in flight. Coupling them would let a status imply a research run
that never happened.

`anonymize` is FINAL §21, and its `reason` is required — see that section for what the
operation does and why the audit entry records none of what it erased.

`/audit-log` reads a table that refuses UPDATE and DELETE for every role. Append-only is
a property of the table, not a convention of the endpoint.

## Plant list

`GET /v1/plants` returns, per plant, three fields beyond the stored row — added in
PR 25 because `PROGRESS §10` asks the card to show them and nothing supplied them:

| Field | Why it is not just the stored column |
|---|---|
| `thumbnail_url` | The bucket is private, so `main_image_id` is not something a browser can render. The URL is signed as the caller and short-lived, like every other image URL in this API. |
| `species_name` | `species_id` is a UUID. Common name where the species has one, the binomial otherwise. |
| `next_task` | The earliest PENDING or OVERDUE task, with its `action_type` — a due date with no action is not a reminder. Overdue work is included deliberately: late work is the most relevant thing a card can say. |

All three are batched across the whole page — four queries for the listing rather
than three per plant, with the thumbnails signed in one call. They are absent from
`GET /v1/plants/{id}`, which has richer sources for the same facts.

Until this shipped, `plant_card` read a `thumbnail_url` key that nothing ever set,
so every card in My Plants rendered "no image" regardless of how many photographs
the plant had.

## Knowledge reads

`GET /v1/species/{species_id}/knowledge` renders the current published version.

`source_summary` is nullable in the schema and every version created outside the
publication RPC — the seed included — leaves it NULL. The response coerces a NULL
to `{}` (PR 23): the provenance of a version lives in `knowledge_sources`, and a
missing convenience summary is not a reason to refuse to render the article. Before
that coercion the endpoint returned 500 for 131 of the 238 current versions in DEV.

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
