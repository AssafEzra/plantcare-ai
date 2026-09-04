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
Image quality validation
   ↓
Optional note
   ↓
Context assembly
   ↓
Health Agent
   ↓
Structured result
   ↓
User sees findings
   ↓
Optional Care adjustment proposal
   ↓
User approval
   ↓
Immutable Health Assessment saved
```

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

