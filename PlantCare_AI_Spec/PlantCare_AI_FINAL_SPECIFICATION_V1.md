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

**An administrator's navigation is the operator's application (revised PR 33), per
§37.** The admin panel shipped as a sixth entry beside בית, הצמחים שלי, הוספת צמח
and הצמח שלי, which made it read as one more tab of a plant-care app rather than
the thing an operator opens. An ADMIN now sees **ניהול** — the landing page at
sign-in — and **הגדרות**, and nothing else. Settings stays because an
administrator still has a timezone, a display name and notification preferences,
and those live nowhere else.

Presentation only. Every plant route remains the caller's own by RLS and every
admin route remains gated server-side (§22, §26): an administrator who typed a
plant URL would see their own plants, exactly as before. Hiding navigation has
never been the control, and this does not make it one.

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

**Upcoming care is on the page (revised PR 32), per §37.** It shipped inside a
collapsed expander, which for a dashboard whose whole promise is "understand in
seconds" is the same as not being on it. The **next three** are rendered outright
beneath today's work; anything further stays one click away, so nothing is lost
and the plant grid stays on the first screen.

They carry no Done or Skip. Completing a task before it is due anchors the entire
recurrence to today (A8), so a button there would quietly move the schedule — the
plant dashboard applies the same rule, offering the actions only on work that is
actually due or overdue.

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

**Research is visible before review (revised PR 33), per §37**

The gate is unchanged: the Knowledge Agent never publishes, `knowledge_versions`
is written only by an administrator approving a draft, and source verification
remains part of that review.

What changed is what happens *while* a draft waits. A plant used to sit in
`KNOWLEDGE_PENDING` with no knowledge, no care plan and no schedule until a human
happened to look — which, for a single-operator MVP, is indistinguishable from the
product not working. Finished research (`READY_FOR_REVIEW`) is now shown to the
owner of a plant of that species, marked **ממתין לאישור מומחה**, and the Care
Agent may build a plan from it.

Three things make that honest rather than a quiet removal of the gate:

1. **Provenance stays exact.** `care_plan_versions` gains `knowledge_draft_id`;
   a version cites a draft *or* a published version, never both (check
   constraint) and never rewritten afterwards (the column joins the
   content-immutable set).
2. **Visibility is scoped.** A new RLS policy admits `READY_FOR_REVIEW` only, and
   only for a species the reader owns a plant of. SELECT only — writes stay
   admin-only, and FINAL §10's "users report errors, never edit" is untouched.
   This is the first time a non-admin can read unreviewed AI content, and it is
   the change in PR 33 that most warrants review.
3. **Rejection is handled.** See A17 below.

A pending article shows no version number and no source list: there is no
published version yet, and verification is part of the review it has not had.
Claiming either would be exactly the overclaiming the badge exists to prevent.

**A17 revised.** A rejected draft may now already be carrying live care plans, so
rejection has a consequence it did not before. The plan is **not** cancelled —
leaving the plant with no schedule at all is worse than one built on advice an
administrator disliked. Instead:

* the plant page says the professional information behind the plan was not
  approved and a corrected version is being prepared;
* one fresh research run is queued automatically, and only when the rejected draft
  is the species' newest — so rejecting the replacement does not start a third,
  and an administrator wanting another uses Retry deliberately;
* the state is *derived* from the draft's status through
  `care_plan_versions.knowledge_draft_id`, never copied onto the plan, so there is
  no second record of it to drift.

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

**An adjustment leaves the rule coherent (PR 33), per §37.** A weekday anchor only
means something on an interval that is a multiple of seven (A7), and `care_rules`
has a CHECK saying so. The adjustment copied the weekday verbatim while applying
the new interval, so "every 7 days on Sunday" changed to five days produced a row
Postgres refused — a 500. Every one of a real user's plants had at least one
weekly rule anchored to a day, so the control was unusable on all of them.

The weekday is **dropped**, not the change refused. The user is choosing a
frequency; the scheduler already ignores a weekday that does not divide into the
interval, so keeping it would store something with no effect, while rejecting
would claim they cannot pick five days when they can.
`domain/rules/care_rule_validation.py` has encoded this rule since PR 16 — this
path simply never consulted it.

The same reproduction exposed a partial write: the version row was inserted before
the rules, so a refused copy left a PROPOSED version with no rules in it and
consumed a version number. The rules are now built and normalised before anything
is written, and a failure during the copy removes the version it belongs to
(§25: nothing partial survives).

**A blocked save says why (PR 33), per §37.** Reported from real use: *"manual
changing in שינוי תדירות או שעה does nothing, it wont let you save changes"*. The
save button required both a changed interval and a description, and enforced both
in silence — so a user who changed 7 days to 5 found a greyed-out primary button
and no reason beside it, which is indistinguishable from a broken one. Both
conditions are real (a version after the first cannot be written without a change
summary, and an adjustment with no override is not an adjustment); the field is
now marked mandatory and the missing half is named under the button.

Worth restating here because it is the other half of the same report: an
operational adjustment produces a **proposal**, not an applied change. The
schedule moves when that proposal is approved — which is what cancels the
outstanding tasks (A5) and materialises the new ones.

**Presented in a window, with what changes (revised PR 33), per §37.** The
approve/reject decision sat inline on the plant page beside the health card and
the timeline, and showed the proposed plan in full without ever saying how it
differed from the one already running — leaving the user to read two schedules
side by side and notice for themselves that watering had moved from seven days to
five.

The plant page now shows a one-line summary and a button; the decision opens as a
dialog containing, in order: the agent's own `change_summary` sentence (the
*why*), the computed difference against the active plan (the *what*), then the
recommendations and the full schedule, then approve and reject.

The difference is computed in `domain/services/care_plan_diff.py` — pure, no
clock, no database, no model — for the same reason `recurrence.py` is pure: a
comparison a user leans on to make a decision must not be something a model
rephrases differently each run. Rules are compared on interval, time and weekday;
reworded `instructions` are deliberately not a change, since the agent rewords the
same advice run to run and reporting that would bury the differences that matter.
A first plan has nothing to diff and simply shows the plan.

`proposal_card` was deleted rather than left unused — a second renderer of the
same proposal is precisely the shape that let two screens disagree about the same
task in PR 31.

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

**Implemented in PR 30 (§37).** `PUT /v1/plants/{id}/environment` shipped in PR 11
and no screen ever called it: תנאי הגידול displayed whatever was stored, said
"עדיין לא הוגדרו תנאי גידול" when nothing was, and offered no way to change that.
Reported as *"i couldnt add or edit תנאי הגידול"*. Worse, the caption underneath
promised exactly the flow drawn above — a change triggers a review of the care
plan — while nothing could make a change and nothing reviewed anything.

The plant dashboard now carries the form, and a successful save requests an
`ENVIRONMENT_CHANGE` proposal, so the diagram's first arrow exists. The request is
made only when the plant already has an active plan: queueing one for a plant
still waiting for its first would put two competing proposals in front of the
user. Every field stays optional (§18) — someone who knows their plant sits on a
north-facing windowsill should not have to invent a humidity reading to say so.

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

**Corrected in PR 32, per §37 — nothing was calling the scheduler**

Reported from real use: *"after creating a care plan it doesnt any schedule
tasks"*. Confirmed against DEV: an account with three active plants, two active
plan versions and eight active care rules had **zero rows** in `care_tasks`.

`scheduler.materialise` was reachable from exactly one place — `POST
/v1/internal/tick` — and nothing called it, because PR 24 (the Railway cron
service) is parked. So the entire scheduler was built, tested, and unreachable:
no tasks, no OVERDUE transitions, no MISSED events, and no reminders.

Two changes, because fixing only the first leaves the app broken a week later:

1. **Approving a plan materialises immediately.** `care.approve` calls
   `scheduler.materialise` scoped to the plan's owner, so the first task exists by
   the time the response is written — which is when the user looks. It is
   idempotent and deliberately non-fatal: the version is genuinely ACTIVE by then,
   and the tick materialises the same rules on its next pass, so a transient
   failure must not turn an approved plan into an error.

2. **The API runs the sweep itself.** The tick body moved out of the router into
   `app/orchestration/services/tick.py`, and the FastAPI lifespan starts a timer
   that calls it every `INTERNAL_TICK_INTERVAL_SECONDS` (default 900; `0` disables
   it, which is what tests and CI use). This is a deviation from the deployment
   plan's cron-only design and is recorded in `DEPLOYMENT_AND_OPERATIONS §5`: the
   cron does not replace the timer so much as make it redundant, since `run_tick`
   is idempotent and either alone produces the same state. An API deployed without
   a cron must not be silently inert.

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

**Every assessment shows when it ran (added PR 33), per §37.** The results card
carried no date at all, so a check from three weeks ago was indistinguishable from
one taken this morning — and an assessment is a statement about a moment: "the
lower leaves are yellowing" means something different from a week ago than from an
hour ago. `created_at` had been on the response since PR 21 and no screen read it.
Rendered as an absolute date *and time* in the reader's own zone: two checks on one
day are ordinary, and a relative phrase ("3 days ago") makes the arithmetic the
reader's problem.

**How a check is started (revised PR 32), per §37**

Reported from real use: *"when starting a health check it should lead to a new
window and give option to load pic, not just select one"*.

The first implementation offered a multiselect over images already in the plant's
gallery and nothing else. That is the wrong shape for what this section describes:
a health check is prompted by something the user has *just noticed*, and the
photograph that shows it does not exist yet. A plant whose gallery was empty
reached a dead end — "you need to upload a photograph first", with nothing there
to upload with.

The check now opens in a dialog offering both: photographs taken now, uploaded on
submit under `context_type=health`, and any existing gallery images the user also
wants included — up to four in total, which is the limit this section already
sets. A dialog rather than a page because the result lands on the plant page the
user is already looking at; sending them elsewhere and back would lose the context
that makes the answer meaningful.

Health images are uploaded as `health`, not `gallery`: evidence for one assessment
is not a portrait of the plant. See §20 for why the four-image cap counts a
submission rather than the plant's history.

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

**Marking is the agent's job, and Health was not doing it (fixed PR 32).** Only the
identification workflow set `plant_images.ai_used`, so a health assessment could
cite a photograph the user was then permitted to hard-delete — the retention rule
above was enforced for one agent out of two. Health now marks its images on a
successful assessment, in the same place identification does.

### Photographs may be taken in the app (added PR 33), per §37

`st.file_uploader` was the only way in. On a phone that is already adequate — the
OS picker offers "Take Photo" — but on a desktop it means hunting for a file, and
on either it means leaving the app to get a picture of the thing you are looking
at right now. A health check in particular is *always* about something just
noticed.

Add Plant and the health check now offer both, as tabs over one shared list, with
the four-image cap common to both sources. A capture is previewed and joins the
batch only when the user keeps it, so a mistimed shot never silently ships.

Two constraints worth recording:

* `st.camera_input` returns **one** photograph at a time, so captures accumulate
  in session state rather than in the widget.
* It requires a **secure context**. `getUserMedia` is refused over plain http, so
  the camera is simply absent on `http://192.168.x.x:8501` — a phone pointed at a
  development server on the LAN. It works on `localhost` and over https, which is
  every deployment. The uploader is always present, so nothing is ever
  unreachable; the camera is an addition, never the only route.

Capture is requested at 1080p rather than left to the widget's display size: the
pipeline works to a 1600px long edge and identification quality is the product, so
a capture sized to a narrow column would be a poor photograph by construction.

### Upload limits are per submission, not per plant

Four images per context is the ceiling on **one submission**, not on the plant's
lifetime. Counting every image a plant had ever had in a context made the *second*
health check impossible: four health images already existed, so the fifth upload
was refused with "אפשר להעלות עד 4 תמונות" — and would have been refused for the
life of the plant.

The cap now counts only images not yet consumed by an agent (`ai_used = false`).
A gallery image is permanent by nature and always counts; health and
identification images are evidence for one run and stop occupying a slot once the
assessment or identification that used them exists.

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

**Physical deletion is not merely discouraged - it is impossible.** Discovered in
PR 26 while cleaning the development database. Every user-owned table cascades
from `auth.users`, but `system_events`, `care_events` and the health tables carry
triggers that refuse DELETE outright (§1.5). So the cascade promises a removal the
trigger forbids, and deleting any account that ever created a plant fails at the
database with "Table system_events is append-only".

The two rules cannot both hold and immutability is the one that wins, which is the
right outcome: this section already says not to delete the account record. Worth
stating plainly all the same, because the `ON DELETE CASCADE` in the schema reads
like a promise the database will not keep, and because anything that needs rows
genuinely gone - a development database full of test accounts - has to disable
those triggers deliberately, as an administrative act, rather than expecting a
cascade to do it.

**The catalogue and the audit log too (added PR 34), per §37.** The sentence above
about a published knowledge version — "cannot be deleted at all" — is true of the
product and false of the repository, and the difference is worth naming rather than
leaving for someone to discover.

Deleting accounts turned out to be a fraction of the problem. Neither the knowledge
catalogue nor the image bucket is owned by a user: `species` belongs to nobody, so
`knowledge_versions`, `knowledge_drafts` and `knowledge_sources` hang off a row no
cascade ever reaches, and storage objects are files rather than rows. By PR 33 the
development database held 851 species named `Testus vfmxhivfsmgffv`, 365 knowledge
versions published about them, 2,130 image files belonging to accounts deleted weeks
earlier, and an audit log in which 234 of 237 entries pointed at rows that no longer
existed. No user could reach any of it and every administrator saw all of it.

So `scripts/scrub_dev_database.py` also disables `knowledge_versions_no_delete`,
`knowledge_sources_immutable` and `admin_audit_log_immutable` — a deviation from the
rule above and from §1.5, on the same terms as the paragraph before it. Those rules
protect the provenance of real records; neither was written to preserve
`Testus ddcbbdibeg` on a development database. **Nothing in the product deletes any
of them**, and the guard is unchanged: the script names the DEV project and exits if
the configured Supabase URL is anything else.

Two properties of that script matter beyond DEV. It classifies three ways rather than
two — known test, known real, and *unclassified*, which it reports and never deletes.
An allowlist of real accounts is wrong the moment the product has users, and a pure
deny-list is silent when a suite adopts a naming convention nobody wrote down, which
is how twenty-six PRs of residue went unnoticed. And it removes bucket objects through
the Storage API rather than by deleting `storage.objects` rows, which would leave the
files themselves in place — invisible to every listing and still counted against the
quota.

This is interim tooling. Pattern-matching species works only because a fixture chooses
the `Testus` prefix; a test that identifies a real photograph creates a real species
name, and nothing will separate it from a user's. The durable fix is the separate
production project (PR 24), after which real accounts do not live in the database the
suites write to, and DEV can simply be emptied.

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

**Session persistence across a browser refresh (added PR 32).**
Reported from real use: reloading the page signed the user out. `st.session_state`
lives for one Streamlit session and a refresh starts a new one, so the auth session
— held there and nowhere else — vanished on F5.

Decision: the Supabase **refresh token** is persisted in a browser cookie
(`pc_refresh_token`, `SameSite=Lax`, `Secure` over https, 12 hours) and the session
is rebuilt from it before routing.

- A cookie rather than `localStorage` because Streamlit reads cookies from the
  connection headers, so the value is available on the **first script run** of a
  new session. Reading `localStorage` requires a component to report back, which
  costs a rerun — and a rerun means either a flash of the sign-in form or a blank
  page while the browser answers.
- Streamlit can read cookies but cannot write them, so the write is done by a
  small Custom Component v2 (`app/ui/components/session_store.py`). Because the
  cookie is written by JavaScript it cannot be `HttpOnly`; the exposure is the
  same as `supabase-js` accepts by default in every browser app.
- Only the *refresh* token is stored — never the access token, never the password,
  never the email. An access token is short-lived and re-derived on load, so the
  stored value is one round trip from being useless rather than immediately
  authoritative.
- The token rotates on every renewal and the cookie is rewritten each time; a
  stale copy would otherwise produce a delayed version of the same logout.
- Cleared on sign-out, and discarded the moment Supabase rejects it.

**Session lifetime: twelve hours idle (added PR HF).**
Reported from real use once the cookie started working on the deployed app: *"now it
never signs off even after a few hours"*. The cookie had been written with a
thirty-day lifetime **and** rewritten on every renewal, so the thirty days restarted
on each visit - a session no amount of time could end. Nothing on the server ended it
either: the project had neither a time-box nor an inactivity timeout.

Decision: **twelve hours from the last visit**, not an absolute cap. A working day is
never interrupted; a machine left alone overnight asks for the password again.

- `session_store.MAX_AGE_SECONDS` is the browser half. Idle rather than absolute
  because the cookie is rewritten on every restore and every rotation.
- `auth.sessions.inactivity_timeout = "12h"` would be the server half, and the only
  half that *revokes*: without it a copied cookie value stays usable however quickly
  the browser forgot it. **It is not in force.** Session timeouts are a paid-plan
  feature on hosted Supabase and the project's plan refuses them - `supabase config
  push` returns `402 "User sessions can only be configured on Pro Plans and up"` -
  so the value sits commented in `supabase/config.toml` and the browser is the whole
  of the enforcement. Recorded rather than left as an assumption, because the two
  halves protect against different things and only one of them is present.
- `auth.jwt_expiry` is `3600` in every environment. DEV's previous `43200` made the
  idle window dishonest: the cookie is only rewritten when the token rotates or the
  page reloads, so a tester working in a single never-reloaded tab carried a clock
  anchored at sign-in and could be asked to sign in after two idle hours rather than
  twelve.

The spec fixes no session lifetime, so these are configuration decisions recorded
here rather than deviations (FINAL 37).

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

**Added in PR 31 (§37) — a worker that dies leaves a request nobody closes.**
Agent work runs in FastAPI `BackgroundTasks`, inside the API process, so a restart
— a deploy, a crash, a reload — kills every run in flight and its `agent_requests`
row stays QUEUED or PROCESSING for good. Nothing reaped them: the row is written
by the request that started it and updated by the worker that died with it.

The user-visible result is worse than an error. The client polls, gives up
politely, reports "still running", and reports it again on every visit, about a
run that ended hours ago.

`POST /v1/internal/tick` now fails any request older than its own agent's budget
plus five minutes, with `AGENT_ABANDONED`. Per agent, because "too long" means
four different things here. Found in PR 31 when a research request sat in
PROCESSING for three hours across several reloads — and a deployment does exactly
what a reload does, which makes this a production concern rather than a
development accident.

**Added in PR 30 (§37) — a 202 that nothing waits on is a 202 that failed
silently.** §24 makes every agent call asynchronous: 202 with an
`agent_request_id`, then the client polls `/v1/agent-requests/{id}`. Only the Add
Plant wizard ever did. The health check and both care-plan proposal routes fired
their 202, told the user "the results will appear here in a moment", and never
looked again — so a failed run said nothing at all, and a successful one appeared
only if the user happened to reload. Reported as *"did a health check and nothing
happened. didnt get result or status update."*

The polling now lives in one component every caller uses, because §25's "visible
failure" is unachievable by a page that never looks at the outcome. A run that has
not finished is reported as still running, never as failed: Knowledge takes
minutes and Care took 105 seconds on its first live run.

**Amended in PR 29 (§37): timeouts are per agent, alongside the models.**

```text
IDENTIFICATION_TIMEOUT_SECONDS=90
KNOWLEDGE_TIMEOUT_SECONDS=600
CARE_TIMEOUT_SECONDS=180
HEALTH_TIMEOUT_SECONDS=180
```

The gateway listed "timeouts" as one of its jobs and PR 12 implemented that as a
single client-wide `AI_REQUEST_TIMEOUT_SECONDS=90`. The four agents do work of
very different sizes: identification is a vision call returning three candidates,
measured at about thirty seconds; Knowledge research writes the thirteen prose
sections of §10 in Hebrew with source retrieval behind it. The first real research
run in DEV was cut off at 90,354 ms with `AGENT_TIMEOUT`. A timeout is deliberately
not retried — retrying will not make a slow response fast — so the draft went
FAILED, the plant stayed `KNOWLEDGE_PENDING`, and the administrator had nothing to
approve. Reported by a user as "why was no knowledge draft created?"

`AI_REQUEST_TIMEOUT_SECONDS` remains, as the client default for provider calls
that are not agent-scoped.

**All four are now measured** against the live API, by PR 31's browser suite and
by real use:

| Agent | Observed | Budget |
|---|---|---|
| Identification | 16-32 s | 90 s |
| Health | 73 s | 180 s |
| Care | 106 s | 180 s |
| Knowledge research | 262 s | 600 s |

Each budget is roughly twice its observed run: enough room for a slow day, not so
much that a user waits on something that is never coming.

**And the request is streamed.** Not to consume it incrementally — an agent needs
a complete, schema-valid document before it can do anything — but because a
streamed request is measured chunk to chunk rather than end to end, so a long
generation that is visibly still producing tokens is not killed for taking a
while. Raising the number alone would have left the same failure waiting at a
larger size.

Neither could be caught by the suite as it stood: a mock provider answers
instantly, so every test of a timeout tests the gateway's handling of one rather
than whether the budget is right, and no test looked at *how* the request was
made. `tests/unit/test_anthropic_provider.py` now substitutes the SDK client and
asserts on the request itself.

**Corrected in PR 30 — streaming moved where validation happens.** `messages.parse()`
returned a message that the provider then validated, so a schema violation became
a `SchemaValidationFailedError` and the two retries applied. The streaming helper
validates *during accumulation*, inside `get_final_message()`, and raises
pydantic's `ValidationError` straight out of the iterator — which is not one of
the provider's error types, so it escaped the gateway's handlers entirely: **no
retry, no `agent_executions` row, and a flat `AGENT_FAILED` on the request**. Both
§23's retry budget and §25's "the failure is visible" were switched off for all
four agents by a change that looked like it only touched transport. The provider
now converts it, and a test pins it.

Found when a Health check returned `priority: 6` against a `le=5` bound — a
plausible reading of an unlabelled 1-5 field as "the sixth recommendation". Both
bounded scales in the Health contract now describe themselves in the schema the
model is given.

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

**Browsable, not lookup-only (revised PR 32).** The screen originally shipped as a
single text box asking for a species UUID, which on a database of hundreds of
species made the published catalogue unreachable unless the administrator already
knew an id — and once found it showed a version number, a date and a badge, never
the text. `GET /v1/species/{id}/knowledge` had returned both content and sources
since PR 15; the admin screen read neither.

The tab now lists every species that has published knowledge — scientific and
common name, language, version, publication date, and the number of plants
depending on it — searchable by either name, each opening a reader with the full
sections, per-section confidence, and every source with its class. Lookup by
species id remains, as history for one species.

New endpoints: `GET /v1/admin/knowledge-versions` (the catalogue, optional `q`)
and `GET /v1/admin/knowledge-versions/detail/{version_id}` (one version in full).

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

