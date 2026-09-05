# PlantCare AI — Final Project Specification

> **Status:** Final MVP specification  
> **MVP language:** Hebrew (RTL)  
> **Frontend:** Streamlit  
> **Backend:** FastAPI  
> **Database / Auth / Storage:** Supabase + PostgreSQL + Supabase Storage  
> **Development approach:** Python-first  
> **AI architecture:** Four specialized Agents behind an application/orchestration layer  
> **MVP scope:** Core product + scheduling/reminders + health + admin

---

## 1. Product Vision

PlantCare AI is an AI-powered personal manager for every plant in the user's home.

The product helps the user:
- know what each plant is,
- understand what it needs,
- maintain a personalized care plan,
- receive actionable reminders,
- monitor plant health over time,
- preserve a long-term history for each plant.

### Product principles

1. **The user remains in control.**
   - AI proposes identification; the user confirms it.
   - Care Plan changes are proposals and require user approval.
   - Global Knowledge is not user-editable.

2. **The database is the source of truth for operational data.**
   - The LLM is an inference component, not the authoritative source.

3. **Static knowledge is separated from dynamic plant state.**
   - Species Knowledge describes what a species generally needs.
   - Plant state describes the user's specific plant.

4. **Use deterministic software where AI adds no value.**
   - Scheduling and recurrence are implemented in Python, not by an LLM.

5. **Preserve history.**
   - Important knowledge, care plans, assessments and care events are versioned/immutable where defined.
   - Updates create new versions/events rather than silently overwriting history.

---

# 2. MVP Scope

## Included

### Authentication
- Supabase Auth
- Email + password registration
- Email + password login
- Email verification
- Password reset
- Logout/session handling
- User profile
- User-specific data isolation

### Application
- Hebrew RTL UI
- Streamlit
- Sidebar navigation
- Home Dashboard
- My Plants
- Plant Dashboard
- Add Plant
- Settings
- Admin Panel for admins

### Plant lifecycle
- Add plant through AI Identification
- User confirmation of identification
- Species-based model (no Cultivar in MVP)
- New species → Knowledge Draft workflow
- Existing published Knowledge → plant can become active
- Plant archive/restore
- Plant History

### Images
- JPG/JPEG/PNG/WEBP
- Maximum 10 MB per image
- Supabase Storage
- Original + processed + thumbnail
- Owner-only normal access
- Identification and Health images supported

### AI
- Identification Agent
- Knowledge Agent
- Care Agent
- Health Agent
- AI provider abstraction
- Configurable model per Agent
- Structured outputs and schema validation
- AI execution logging

### Care and scheduling
- Personalized Care Plan
- Care Plan versioning
- User approval
- Care Rules
- Generated Care Tasks
- Deterministic scheduling service
- Done / Skip
- Overdue handling
- Internal reminders
- Email reminders through Resend
- User timezone support

### Health
- User-initiated Health Check
- 1–4 images
- Optional user note
- Health Assessment
- Plant status update
- Health history
- Basic trend analysis
- Care adjustment proposal, requiring Care Agent + user approval

### Knowledge
- Species
- Published Knowledge Versions
- Knowledge Drafts
- Source provenance
- Approved Sources
- Admin review
- User error reports
- Immutable published history

### Admin
- Admin-only access
- Knowledge Draft review
- Published Knowledge history
- Approved Sources management
- Reported Errors
- AI/Agent Monitoring
- Audit logging

## Explicitly excluded from MVP

- Google / Apple / other Social Login
- Care Level personalization
- Cultivar model
- External calendar integration
- Push notifications
- Advanced email notification strategies
- Smart notification timing
- General-purpose documentation photos
- ML-based purchase recommendations
- Native mobile application
- Community/social features
- IoT/device integrations
- English UI

---

# 3. User Experience

## 3.1 First-time Onboarding

Keep onboarding short.

1. Register/login.
2. Short Welcome screen.
3. Add first plant.
4. Identify and confirm the plant.
5. Enter:
   - personal plant name,
   - optional environment,
   - optional note.
6. Open Plant Dashboard.

Subsequent plants go directly through Add Plant without repeating onboarding.

---

# 4. Main Navigation

Sidebar:

- Home
- My Plants
- Settings
- Admin Panel (admin only)

The interface is Hebrew and RTL in the MVP.

---

# 5. Home Dashboard

The dashboard is action-oriented.

The user should understand in seconds what needs attention today.

### Components

- Personalized greeting
- Today's Care
- Done / Skip actions
- Plants Needing Attention
- Quick Health Check
- My Plants preview
- Add Plant CTA
- Upcoming care
- All-caught-up state

---

# 6. My Plants

Default presentation: grid of plant cards.

Each card contains:
- Main image
- Personal Plant Name
- Species
- Current Health Status
- Nearest care task
- Attention indicator

Features:
- Search
- Basic health filter/sort
- Click card → Plant Dashboard
- Empty state
- Loading state

---

# 7. Plant Lifecycle

Statuses:

- `PENDING_IDENTIFICATION`
- `IDENTIFIED`
- `KNOWLEDGE_PENDING`
- `ACTIVE`
- `ARCHIVED`

### Lifecycle

```text
Add Plant
   ↓
Identification Agent
   ↓
User Confirmation
   ↓
Species known?
 ┌───────────────┴───────────────┐
Yes                             No
 ↓                               ↓
Published Knowledge?             Create Species
 ↓                               ↓
Yes → ACTIVE                     Knowledge Draft
                                 ↓
                              Research
                                 ↓
                            Admin Review
                                 ↓
                              Published
                                 ↓
                                ACTIVE
```

If the user archives a plant, its history remains and the plant can be restored.

**Clarified during implementation, per §37 — what a restored plant's status becomes.**
TESTING_STRATEGY §3 lists `ARCHIVED → ACTIVE`, but archiving is the user's replacement for
deletion and is therefore allowed from any status, including a plant that was never
identified. Restoring such a plant straight to `ACTIVE` would produce an active plant with no
species and no care plan.

The restored status is therefore **recomputed** from the plant's own data rather than
remembered: no confirmed species → `PENDING_IDENTIFICATION`; species with published knowledge
→ `ACTIVE`; species without → `KNOWLEDGE_PENDING`. This needs no extra column, cannot drift
out of sync, and yields the documented `ARCHIVED → ACTIVE` for the ordinary case. It also
means a plant whose species gained published knowledge while it was archived comes back
`ACTIVE` rather than waiting again.

---

# 8. Add Plant

A new plant must go through Identification Agent in the MVP.

Manual species selection is not the primary Add Plant path.

### Input

- 1–4 useful identification photos
- Optional user description/note

The user may say what they think the plant is, but this is contextual information and is not treated as confirmed fact.

### Identification result

Return:
- Primary candidate
- Up to two alternatives when appropriate
- Scientific name
- Common name where available
- Confidence score
- Confidence category: HIGH / MEDIUM / LOW
- Image quality
- Optional request for additional photos

### Confirmation

The user must confirm the identification before Care processing.

A real relevant Wikipedia page may be shown on the confirmation screen. The URL must never be invented.

### Re-identification

The user can trigger a new identification later.

- Old identification remains in history.
- New confirmed species updates `plant.species_id`.
- Existing Care Plan is not silently replaced.
- A new Care Plan proposal is generated and requires user approval.

---

# 9. Identification Agent

Contract:

```text
IdentificationAgent.identify(request) -> IdentificationResult
```

Responsibilities:
- Analyze plant images.
- Produce structured candidates.
- Provide confidence and image-quality assessment.

Does NOT:
- mutate Plant,
- modify Knowledge,
- create Care Plan,
- modify Health.

The application/orchestration layer handles persistence after user confirmation.

Failure states:
- `SUCCESS`
- `NEEDS_MORE_INFORMATION`
- `FAILED`

No failed AI result becomes an authoritative identification.

---

# 10. Knowledge Base

Knowledge is global and species-based.

### Knowledge fields

- Identification
- Description
- Light
- Watering
- Soil
- Temperature
- Humidity
- Fertilization
- Repotting
- Pruning
- Propagation
- Common Problems
- Toxicity/Safety
- Sources

### Knowledge lifecycle

```text
Species
  ↓
Knowledge Draft
  ↓
Knowledge Agent research
  ↓
Admin Review
  ↓
Published Knowledge Version
```

The Knowledge Agent never publishes directly.

All external claims require a real source.

If a claim has no verified external source, mark it:

`AI-generated / Requires Verification`

### Source policy

Approved Domains are preferred.

Outside domains may be used when necessary, but must be marked:

`External / Unapproved Source`

and receive additional admin attention before publication.

### User permissions

Users:
- read published Knowledge,
- report possible errors,
- cannot edit Knowledge.

Admins:
- review drafts,
- approve/reject,
- manage Approved Sources,
- view version history,
- never delete published historical versions.

---

# 11. Knowledge Agent

Contract:

```text
KnowledgeAgent.generate(request) -> KnowledgeDraft
```

Responsibilities:
- Research a species.
- Create or update a Knowledge Draft.
- Attach real sources.
- Identify uncertainty.

Does NOT:
- publish,
- edit user plants,
- create Care Plans,
- execute care tasks,
- perform diagnosis.

Knowledge research may be long-running and should be queued/background-like from the UX perspective.

**Specified during implementation (PR 14), per §37**

*When research starts.* Automatically, when a user confirms an identification for a species with
no published Knowledge. The user is not asked and is not made to wait: their plant is added and
usable in `KNOWLEDGE_PENDING` while research runs behind the 202-and-poll contract of §24. An
administrator can also start or restart a run.

*One run per species.* A second confirmation of the same new species joins the run already in
flight rather than starting a rival one. Two concurrent runs would bill twice and end with two
drafts of the same knowledge competing to publish, which the partial unique index refuses anyway.

*The draft lifecycle.* The states this section names, and the moves between them that are legal:

```text
DRAFT ──────────────► RESEARCHING ──────► READY_FOR_REVIEW ──► APPROVED (terminal)
  └──► REJECTED           └──► FAILED            ├──► REJECTED
                                                 └──► RESEARCHING (research again)
REJECTED ──► RESEARCHING        FAILED ──► RESEARCHING
```

A rejected or failed draft stays retriable (A17). It has to: plants sit in `KNOWLEDGE_PENDING`
until *some* version of that species publishes, and a terminal rejection would strand every one
of them with no path out. `APPROVED` is terminal in the other direction — its content is already
an immutable published version, and a draft that could move again would imply that version could
change. Only `RESEARCHING` can become `FAILED`, because failure is what a run does when it cannot
finish and a run always sets `RESEARCHING` first.

*Sources are verified, never taken on trust.* The agent proposes URLs; Python fetches each one,
requires a 200, and requires the page to actually be about that species — Wikipedia-style
redirects and real domains serving fabricated paths both pass a status check and fail this one.
Only then is a source classified `APPROVED` (matching an enabled approved domain) or
`EXTERNAL_UNAPPROVED`. A claim that fails verification is **kept and marked**
`AI_GENERATED_REQUIRES_VERIFICATION`, not discarded: dropping it would leave the draft looking
better sourced than it is.

---

# 12. Care Agent

Contract:

```text
CareAgent.generate_plan(request) -> CarePlanProposal
```

Inputs:
- Published/relevant Knowledge Version
- Plant
- Environment
- Health state
- Health history
- Care history
- User preferences

### Output

A structured Care Plan Proposal containing professional recommendations and operational rules.

### User approval

The user must approve the initial Care Plan.

The user may edit operational parameters such as:
- frequency,
- preferred time,
- reminder preference.

Professional recommendation content is not directly editable as if it were authoritative advice.

If a meaningful change is requested:
- show a warning where appropriate,
- create a new Care Plan Version,
- record a Change Summary.

### Environment changes

Changing Environment does not automatically overwrite the Care Plan.

Instead:

```text
Environment change
       ↓
Care Agent review
       ↓
Adjustment Proposal
       ↓
User approval
       ↓
New Care Plan Version
```

### Health-driven changes

Health Agent may suggest a possible adjustment.

It cannot directly modify the Care Plan.

Flow:

```text
Health Assessment
       ↓
Potential adjustment
       ↓
Care Agent proposal
       ↓
User approval
       ↓
New Care Plan Version
```

**Specified during implementation (PR 16), per §37**

*The two halves are separate fields, not one document.* `professional_recommendations` is prose;
`care_rules` are parameters. This section says the user may edit frequency, preferred time and
reminder preference but not the advice — a rule that is only expressible if the two are
structurally apart. Were they one blob, every operational tweak would rewrite the advice
underneath it, and "not directly editable" would be a convention rather than a guarantee. The
proposal card reflects this: the advice has no input anywhere near it.

*A plan is for one plant, not for the species.* All seven inputs listed above are assembled and
sent. The care history matters most and is the easiest to forget: the plan says what should
happen and the history says what does, and a user watering five days late every time is telling
us the interval is wrong for their home rather than that they are careless.

*A proposed rule the scheduler could not honour is dropped, not fatal.* Interval bounds, per
action plausibility (repotting is measured in months), A7 weekday coherence and reminder hours
are checked in Python before the write. A rule that reached the database would fail a CHECK
constraint and take the whole insert with it, losing the good rules alongside the bad one. A
proposal left with **no** rules is a failure, though: it would appear in the user's list looking
approvable, and approving it would activate a plan that schedules nothing.

*One watering rule, not two.* A duplicate action type is a competing rule, not a richer schedule
— the scheduler would materialise a task for each and tell the user to water the same plant
twice.

*The initial plan is proposed automatically* when a plant becomes `ACTIVE`, including via the
knowledge fan-out of §10 (A3). It is still only a proposal.

*Missing context (A20).* The agent may report what would have made the plan better — pot size,
drainage, how much direct sun the window really gets. The MVP **renders these and asks nothing**:
there is no status, table or endpoint that could carry an answer back, so a question would
promise a conversation the product cannot have. Notably, pot size and drainage are not columns on
`plant_environments` at all, which is exactly why the agent tends to name them.

---

# 13. Care Rules, Tasks and Events

### Care Rule

Recurring logic, for example:

`Water every 7 days at 08:00`

### Care Task

An actionable occurrence:

`Water Monstera — tomorrow 08:00`

### Care Event

Immutable record of what actually happened:
- Completed
- Skipped
- Corrective/manual event where applicable

Scheduling is deterministic Python.

Do not pre-generate excessive future tasks.

The scheduler calculates relevant occurrences from:
- active Care Plan Version,
- Care Rules,
- Care Events,
- current time,
- user timezone.

### Missed tasks

A missed task becomes Overdue.

Do not create an infinite backlog.

The next recurrence remains scheduled.

Multiple overdue items can be summarized.

**Specified during implementation (PR 17), per §37**

*Scheduling is day arithmetic in the user's timezone,* not seconds added to a UTC instant. A
reminder set for 08:00 means 08:00 where the user is, on the day it lands. The naive
implementation passes every test except a DST boundary and then moves every reminder by an hour
twice a year — Israel changes its clocks, and Asia/Jerusalem is the MVP default.

*A newly approved plan reminds today or tomorrow,* not after a full interval. A nine-day watering
plan that says nothing for nine days reads as an app that did not work.

*What the next occurrence counts from:* a completion anchors on when it actually happened, a skip
on the original due date, and a miss on the moment it was written off. The third is the subtle
one — anchoring a miss on its long-past due date puts the next occurrence in the past too, the
sweep retires that as expired as well, and a MISSED event is written on every scheduler run
indefinitely.

*"Do not create an infinite backlog" is enforced three ways,* because it is the requirement most
easily lost to a small bug: an overdue task expires after `min(interval_days, 14)` days and
becomes history; a partial unique index permits at most one pending task per rule; and any
occurrence computed into the past is advanced to the next one still worth doing before it is
written.

*An archived plant is not scheduled.* Reminding someone to water a plant they have put away is
the clearest possible sign the application is not paying attention. Its plan and history survive
intact for when it is restored.

---

# 14. Notifications

## MVP

- In-app reminders
- Email reminders
- Email provider abstraction
- Resend implementation

Email preferences:
- enabled/disabled
- preferred reminder time
- daily digest when multiple tasks are appropriate

All sends are logged to prevent duplicate delivery.

Future:
- Push
- advanced email flows
- pre-reminders
- missed-reminder emails
- weekly summaries
- smart timing

---

# 15. Timezone

- Detect timezone automatically.
- Allow manual override.
- Store timestamps in UTC.
- Store user timezone preference.
- Display and schedule according to the user's timezone.

---

# 16. Health Agent

Contract:

```text
HealthAgent.assess(request) -> HealthAssessment
```

Inputs:
- 1–4 images
- confirmed species
- relevant Knowledge
- previous Health Assessments
- treatment/care history
- environment
- current Care Plan

### Output

`HealthAssessment`:

- `overall_status`
- `observations`
- `possible_issues`
- `severity`
- `confidence`
- `recommendations`
- `requires_attention`
- `sources`

### Status values

- `HEALTHY`
- `NEEDS_ATTENTION`
- `CRITICAL`
- `UNKNOWN`

Overall status and issue severity are separate concepts.

The Agent must not present definitive diagnosis.

Use language such as:
- possible issue,
- signs that may be consistent with,
- worth checking.

### Health Check flow

```text
Health Check
   ↓
Upload 1–4 images
   ↓
Image quality validation   (warns; never blocks — see below)
   ↓
Optional note
   ↓
Context assembly
   ↓
Health Agent
   ↓
Structured result
   ↓
Immutable Health Assessment saved      ← always, including UNKNOWN
   ↓
User sees findings
   ↓
Optional Care adjustment proposal
   ↓
User approval
   ↓
New Care Plan Version
```

**Diagram corrected in PR 21, per §37 (A28).** The original placed "Immutable Health Assessment
saved" *after* "User approval", which contradicted this section's own prose — "Every successful
Health Check updates the Plant's current health status" — and would have meant a check was
recorded only when the user agreed to a care change, and never when they declined one. The prose
is authoritative and is what is implemented: the assessment is saved as soon as it exists, and a
care proposal is raised afterwards from the saved row.

**Specified during implementation (PR 21), per §37**

*Image quality warns; it never rejects (A25).* The gate measures decoded dimensions, contrast and
a focus score before the model call, and passes what it finds to the agent as context. It does
not block the upload: this section already defines the outcome for weak evidence — an `UNKNOWN`
assessment saved with its reason — and refusing the upload would put that outcome out of reach,
telling a worried user to go away and photograph their plant again instead of looking at what
they sent. A model *told* the photographs are poor returns `UNKNOWN` honestly far more often than
one left to discover it.

*An UNKNOWN carries no findings.* A verdict that could not tell what it was looking at cannot
also list what might be wrong, so issues and recommendations are dropped from an `UNKNOWN` result
— showing both would let a user act on findings the verdict itself disowns. Observations survive:
"the lower leaves are yellow" stays true even when what it means is not. Two CHECK constraints
enforce the rest — an `UNKNOWN` must carry a reason and must not carry a confidence level.

*An UNKNOWN does not overwrite a real status.* It is a record that we could not tell, not evidence
the plant declined, so the plant keeps the status its last readable check gave it.

*Everything a check produces is written in one transaction.* The 1–4 image constraint is
`DEFERRABLE INITIALLY DEFERRED` and therefore checked at commit, and PostgREST gives every call
its own transaction — so the assessment, its images, observations, issues, recommendations and
sources go through a single RPC (`save_health_assessment`, migration 0014). A failure leaves no
row at all.

*The trend is computed in Python (A11)* by comparing the new status with the previous readable
one. `UNKNOWN` assessments are skipped rather than counted as a low point, or every blurred
photograph would report a decline.

Every successful Health Check updates the Plant's current health status.

Previous assessments remain unchanged.

If information is insufficient, save an `UNKNOWN` assessment with the reason.

### Trend

Simple MVP trend:
- Improving
- Worsening
- Stable
- Unable to determine

Do not claim a trend without sufficient evidence.

---

# 17. Plant Dashboard

The Plant Dashboard is the central hub.

Sections:

- Main image / gallery
- Personal Plant Name
- Confirmed Species
- Current Health Status
- Upcoming Care Tasks
- Care Plan
- Health Assessments / basic trend
- History
- Environment
- Basic plant information
- Health Check action
- Update Environment
- Report Knowledge Error

### Status card

- Healthy
- Needs Attention
- Critical
- Unknown

Status is an assessment, not a medical/botanical diagnosis.

---

# 18. Plant Environment

Fields:

- `location_type`
  - Indoor
  - Outdoor
  - Balcony
  - Greenhouse
- `light_level`
  - Low
  - Medium
  - Bright
  - Direct Sun
- `light_direction`
  - North
  - South
  - East
  - West
  - Unknown
- Temperature (optional)
- Humidity (optional)
- Room
- Notes
- `updated_at`

The Care Agent works with partial environment data.

If an important input is missing, the system may ask the user or qualify the recommendation.

MVP units:
- Temperature: °C
- Humidity: %

---

# 19. Plant History

History is preserved as a timeline.

Examples:
- Plant created
- Identification confirmed
- Identification changed
- Care Plan created/approved
- Care event
- Health Check
- Environment changed
- Repot
- Move
- Prune
- User-created custom event

Events should be append-oriented. Corrections create corrective events rather than rewriting history.

`plant_environments` holds only the current row per plant, so "Environment changed" history entries are persisted as `system_events` rows (`event_type = ENVIRONMENT_CHANGED`) written alongside every environment update — not as a separate environment-history table.

---

# 20. Images and Storage

Supported:
- JPG
- JPEG
- PNG
- WEBP

Maximum:
- 10 MB per image

Pipeline:

```text
Validate
   ↓
Process / resize / compress
   ↓
Supabase Storage
   ↓
Persist image reference + metadata
   ↓
Use by AI when required
```

Store:
- original
- processed version
- thumbnail

Metadata belongs in PostgreSQL, not inside the blob as the authoritative record.

Logical path:

```text
plant-images/{user_id}/{plant_id}/{gallery|identification|health}/
```

Normal user-facing access is owner-only.

### Retention

Images used by AI are not physically deleted when the user requests removal.

They remain for history/audit purposes but are hidden from the user and not displayed.

Admin may access retained AI-used images when needed.

---

# 21. Privacy and Account Deletion

### User data

Supabase RLS is mandatory for user-owned tables.

Do not rely only on Python authorization checks.

### Account deletion

Do not physically delete the account record.

Instead:
- anonymize identifying/user-related details,
- disable access,
- preserve anonymized history/data where required,
- restrict access to the anonymized account data to Admin.

**How it is initiated (A26, resolved in PR 22).** The MVP has no self-service deletion
control. A deletion is an out-of-band request — support ticket, email — that an
administrator carries out from the Accounts tab of the admin panel. That is why the
`reason` is required rather than optional: it is the only record of why the account
was closed, and without it the audit entry cannot be understood a year later. A
self-service path is Future work; it needs a confirmation flow and a grace period,
neither of which is specified.

**What it does, in one transaction.** `anonymize_account(user_id, reason)`:
clears `email` and `display_name`, sets `is_active = false`, stamps `anonymized_at`,
nulls the names and notes the user chose for their plants, and writes one
`admin_audit_log` entry. Half of that is worse than none — an account with its email
cleared but access still enabled is a user locked out of a login they can still
perform — so it is a single SQL function, not a sequence of updates.

The audit entry deliberately records **no email and no display name**, only the reason
and the number of plants retained. An audit trail that preserved what was erased would
defeat the operation it describes.

The `auth.users` credential is revoked separately through Supabase's own admin API.
Anonymisation owns the public schema; putting a second, partial copy of credential
revocation in SQL would be worse than leaving it to the system that owns it.

Plants, care history, health assessments and knowledge contributions survive, per
"preserve anonymized history" above — and because a published knowledge version cannot
be deleted at all (§29) and care events are immutable by trigger (§1.5). What changes is
that nothing in the account identifies a person any more.

An administrator cannot anonymise their own account: it would revoke the role needed to
undo it, and remove an administrator by accident. Running it twice is harmless — the
second call returns the already-anonymised profile rather than raising, which matters
for something executed by hand from a ticket.

### Plant deletion

Normal user action is Archive, not hard delete.

Archived plants are hidden from active views and can be restored.

---

# 22. Authentication and Authorization

Supabase Auth is the identity provider.

MVP:
- Email/password
- Email verification
- Password reset
- Session handling

Authorization:
- regular user
- admin

RLS policies enforce ownership.

Knowledge is globally readable to regular users but writable only by Admin.

Admin Panel is admin-only.

---

# 23. AI Architecture

Four Agents:

1. Identification
2. Knowledge
3. Care
4. Health

Agents do not call each other directly.

The application/orchestration layer coordinates workflows.

### Contracts

```text
IdentificationAgent.identify()
KnowledgeAgent.generate()
CareAgent.generate_plan()
HealthAgent.assess()
```

### AI Provider abstraction

Agents must not be tied to a specific provider.

Suggested interface:

```text
text_generation()
vision_analysis()
structured_output()
verify_wikipedia_page(scientific_name, locale) -> WikipediaPage | null
retrieve_source(query | url) -> RetrievedSource
```

**Resolved — Identification Wikipedia link (§8):** `verify_wikipedia_page()` calls Wikipedia's own public REST API (`GET https://{locale}.wikipedia.org/api/rest_v1/page/summary/{title}`, no key required) against the confirmed scientific name. A URL is shown only when that lookup returns a real matching page; otherwise the field is omitted. No vendor decision is needed here — it is Wikipedia's own API.

**Resolved — Knowledge Agent general source research:** as of 2026, Claude, GPT and Gemini all offer native search/grounding tool-use as part of the model call itself — this is provider-agnostic, so the choice of `KNOWLEDGE_MODEL` no longer blocks this decision. `retrieve_source()` uses the configured provider's native search/grounding capability to find and draft candidate sources; no separate search-API vendor is required for MVP.

Every URL the model returns is then verified deterministically in Python before being persisted as a `knowledge_sources` row: fetch it directly, confirm it resolves (`HTTP 200`) and its content is relevant to the claim, then classify `source_class = APPROVED` if the domain matches `approved_sources`, otherwise `EXTERNAL_UNAPPROVED`. This verification step — not the model's self-report — is the authoritative check, consistent with product principle #2 ("the LLM is an inference component, not the authoritative source"). If `KNOWLEDGE_MODEL` is later switched to a provider without native search, a dedicated search API becomes the fallback — that is a future-scope contingency, not an MVP blocker.

An AI Gateway handles:
- provider selection
- authentication
- retries
- timeouts
- structured output
- logging
- cost tracking

### Models

Different models may be used for different Agents.

Configuration is external to Agent code:

```text
IDENTIFICATION_MODEL=...
KNOWLEDGE_MODEL=...
CARE_MODEL=...
HEALTH_MODEL=...
```

Models can be swapped without rewriting Agent logic.

### Prompts

Version prompts under:

```text
prompts/
  identification/
  knowledge/
  care/
  health/
```

### Structured output

All Agent outputs are schema-validated.

Invalid output:
- retry automatically up to 2 times,
- then fail gracefully.

AI failure must never create an approved/authoritative record.

### Execution logging

`agent_executions` should record:
- agent type
- request ID
- plant ID where applicable
- model
- model version
- prompt version
- status
- start/end timestamps
- token usage
- estimated cost
- latency
- error information

Do not store chain-of-thought.

---

# 24. Processing / Performance Model

UX should feel responsive for quick actions.

AI operations display explicit processing states, for example:

```text
Images received
      ↓
Context loaded
      ↓
Analyzing
      ↓
Preparing results
```

Long Knowledge research is asynchronous/background-like from the user's perspective.

**MVP decision:** no dedicated queue/worker service is part of MVP scope. The `202` + poll-`GET /v1/agent-requests/{request_id}` pattern is served by in-process async execution (e.g. FastAPI background tasks) behind the same Agent contracts. The architecture must allow a future worker/queue to replace this without changing Agent contracts.

---

# 25. Error Handling

### Identification
- Need more information
- Failed
- No authoritative species assignment on failure

### Knowledge
- Draft can be incomplete
- Failed research is visible to Admin
- Retry is possible
- Unverified claims are clearly marked

### Care
- Ask for missing essential context
- Do not generate unsafe-looking certainty from incomplete context

### Health
- Save `UNKNOWN` when evidence is insufficient

### General

AI failure never creates an approved/authoritative record.

---

# 26. Security

- Supabase RLS on every user-owned table
- Owner-only plant/image access
- Admin-only Knowledge management
- Admin-only Agent monitoring
- Admin actions audited
- DEV and PROD fully separated
- Secrets stored in environment configuration
- `.env` never committed
- Production credentials never used by default in local development

---

# 27. Database Model

Core tables:

- `profiles`
- `plants`
- `plant_images`
- `plant_environments`

Identification:
- `identifications`
- `identification_candidates`

Knowledge:
- `species`
- `knowledge_versions`
- `knowledge_sources`
- `approved_sources`
- `knowledge_drafts`
- `knowledge_reports`

Care:
- `care_plans`
- `care_plan_versions` (includes `source_type` and `change_summary` — this is the version-provenance audit trail; there is no separate `care_plan_changes` table)
- `care_rules`
- `care_tasks`
- `care_events`

Health:
- `health_assessments`
- `health_observations`
- `health_issues`
- `health_recommendations`

AI/System:
- `agent_executions`
- `agent_requests`
- `system_events`
- audit records as required

### Core relationship

```text
User
 └── Plants
      ├── Images
      ├── Identification History
      ├── Environment History
      ├── Care Plan + Versions
      ├── Care Rules / Tasks / Events
      ├── Health Assessments
      └── Plant History

Species
 └── Published Knowledge Versions
      └── Sources
```

`plant.species_id` is nullable until identification is confirmed.

Species is the MVP knowledge entity. Cultivar is future scope.

---

# 28. API / Application Boundaries

FastAPI is the backend boundary even when Streamlit is the MVP client.

Recommended domain services:

```text
auth/
plants/
identification/
knowledge/
care/
health/
schedule/
notifications/
admin/
images/
ai/
```

The exact REST endpoint names may be finalized during implementation, but business rules must remain behind service/domain boundaries rather than inside Streamlit page code.

---

# 29. Admin Panel

Admin-only.

### Knowledge Drafts
- list/view
- source inspection
- approve
- reject
- admin note
- retry research

### Published Knowledge
- current versions
- history
- source provenance
- no deletion of historical published versions

### Approved Sources
- add
- edit
- disable
- reliability level
- notes
- view Knowledge Versions using source

### Reported Errors
- user reports
- status
- review
- trigger new Knowledge Draft when necessary

### AI / Agent Monitoring
- executions
- failures
- model
- prompt version
- duration
- cost metadata

### Audit
All consequential Admin actions are logged.

---

# 30. Email

MVP email provider:

**Resend**

Architecture:

```text
NotificationService
      ↓
EmailProvider abstraction
      ↓
Resend
```

This allows a provider change later without rewriting notification logic.

---

# 31. Deployment and Environments

### GitHub

Branches:
- `main`
- `dev`
- feature branches + PRs

### DEV

- Separate Supabase project/database
- Separate credentials
- Test data only
- Safe AI testing
- Migration testing

### PROD

- Separate Supabase project/database
- Production secrets
- Backup strategy
- Monitoring/logging
- Deployment pipeline
- Rollback plan

Production DB must never be used as the routine development database.

Railway is the preferred deployment direction for the Python application, subject to final implementation validation.

---

# 32. UI / Design

Use the previously approved PlantCare AI visual direction:

- Natural / Premium
- Hebrew RTL
- Clean hierarchy
- Plant imagery is prominent
- Cards for plants/tasks/status
- Clear status indicators
- Strong empty/loading/error states
- Responsive within Streamlit constraints

The exact design tokens and final wireframes are implementation artifacts and should preserve the approved visual direction rather than introduce a new visual language.

---

# 33. Accessibility

MVP:
- RTL
- clear typography
- readable controls
- clear loading/error/empty states
- basic desktop/mobile responsiveness within Streamlit constraints

Advanced accessibility system is not an MVP requirement.

---

# 34. Testing and Acceptance Criteria

Testing focuses on critical user flows.

## Unit tests

At minimum:
- recurrence calculation
- overdue calculation
- Care Rule validation
- Health status handling
- versioning
- permissions
- image validation
- structured AI output validation

## Integration tests

- Authentication
- Add Plant
- Identification
- Knowledge lookup
- Knowledge Draft
- Care Plan generation
- Schedule generation
- Health Check
- Care Plan update
- Admin workflow
- Notifications

## End-to-end smoke test

A complete successful path must work:

```text
New user
 → Register/Login
 → Add Plant
 → Upload photos
 → Identification
 → Confirm
 → Knowledge
 → Care Plan
 → Schedule
 → Complete task
 → Health Check
 → Status update
 → History
```

Additional critical paths:
- existing species reuses published Knowledge
- new species creates Draft and reaches Admin approval
- Health Assessment can create a Care adjustment proposal
- overdue task is represented correctly
- user A cannot access user B's data
- AI failure never creates an approved record

---

# 35. Definition of Done — MVP

The MVP is considered complete when a new user can:

- register and log in,
- complete onboarding,
- add a plant,
- upload photos,
- receive an AI identification,
- confirm identification,
- use existing Knowledge or enter the Knowledge Draft workflow,
- receive and approve a personalized Care Plan,
- see recurring care tasks,
- receive in-app/email reminders,
- complete or skip tasks,
- see overdue tasks,
- open Plant Dashboard,
- view plant history,
- perform a Health Check,
- receive structured health findings,
- see current plant status update,
- preserve Health history,
- approve/reject Care Plan adjustment proposals,
- report Knowledge errors.

The system must also satisfy:
- RLS isolation,
- admin-only controls,
- DEV/PROD separation,
- structured AI validation,
- graceful AI failures,
- audit logging for Admin actions.

---

# 36. Future Features

These are intentionally outside MVP:

### Authentication
- Google Login
- Apple Login
- other Social Login

### Personalization
- Care Level: Beginner / Intermediate / Advanced

### Calendar / Notifications
- Google Calendar
- Apple Calendar
- Push Notifications
- advanced email notifications
- pre-reminders
- missed-reminder messages
- weekly summaries
- smart notification timing

### Plant intelligence
- Cultivar support
- more advanced health trends
- before/after image analysis
- adaptive care plans
- weather/environment integrations
- smart watering insights

### Product / ecosystem
- ML-based plant purchase recommendations
- product recommendations
- partnerships/affiliate commerce
- community/sharing
- expert Q&A
- collections/tags
- IoT and smart devices

### Platform
- Native mobile application
- English localization

---

# 37. Engineering Working Rules

When a new requirement is introduced:

1. Add it to the specification.
2. Decide whether it belongs in MVP or Future.
3. Record the decision.
4. Update the development tracker.
5. Never silently overwrite an architectural decision.
6. If a technical choice is genuinely unresolved, mark it as pending instead of inventing certainty.

