# PlantCare AI — Deployment & Operations

## 1. Purpose

This document defines the production deployment model, environment separation, secrets handling, migrations, monitoring, and operational practices for PlantCare AI.

## 2. Environments

There are two primary environments:

```text
DEV
PROD
```

Each environment has its own:

- Supabase project/database;
- Supabase Auth configuration;
- Storage;
- application configuration;
- AI configuration where appropriate;
- email configuration where appropriate.

Production data must never be used as ordinary development test data.

## 3. Deployment Topology

Recommended MVP topology:

```text
                    ┌───────────────┐
                    │   Streamlit   │
                    │      UI       │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    FastAPI    │
                    └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
         Supabase       AI Gateway   Notifications
         DB/Auth/       Providers      / Resend
         Storage
```

Railway is the preferred initial hosting direction for Python services, subject to final deployment configuration.

### The scheduler tick has two drivers (added PR 32, per FINAL §37)

The plan gave the sweep one driver: a Railway cron service calling
`POST /v1/internal/tick` every ~15 minutes. That service is part of PR 24, which is
parked — so in practice **nothing ever called the tick**, and the consequence
reached a user: approving a care plan produced an active plan with no tasks, and
the overdue sweep, MISSED events and reminders never ran at all (FINAL §13).

The API therefore carries its own timer. The tick body lives in
`app/orchestration/services/tick.py` and has two callers:

| Driver | Where | Controlled by |
|---|---|---|
| Cron service | `POST /v1/internal/tick`, shared secret | Railway cron (PR 24) |
| In-process timer | FastAPI lifespan task | `INTERNAL_TICK_INTERVAL_SECONDS` (default 900; `0` disables) |

They do not conflict. `run_tick` is idempotent — materialisation skips a rule that
already has a pending task and the database refuses a second one regardless, and
reminders are deduplicated on `notification_deliveries.dedupe_key` — so a cron
firing while the timer runs produces the same state as either alone. The same
property makes it safe under multiple uvicorn workers.

Operational notes:

- The sweep is synchronous Supabase I/O and runs in a worker thread, so it never
  blocks the event loop.
- Every exception is logged and swallowed. A transient database error must not
  leave the process with no scheduler until someone restarts it.
- Set `INTERNAL_TICK_INTERVAL_SECONDS=0` on a deployment that would rather have
  only the cron.
- Tests and CI set it to `0`. A background timer inside a test process writes to
  DEV on its own schedule and makes failures irreproducible.
- **Duration scales with the number of plans, not with traffic.** Measured against
  DEV on 2026-09-06, before and after purging the accounts the integration suite
  had left behind:

  | DEV state | Accounts | One full sweep |
  |---|---|---|
  | Polluted | 1,504 | **6m11s** (39 materialised, 34 marked overdue) |
  | Purged | 10 | **5.2s** |

  The first figure is the one to plan against, not the second: it is what the
  sweep costs when the database is full, and 6m11s against a 900s interval is
  thin headroom. The loop sleeps *between* runs so two can never overlap, but a
  production database will grow past DEV's worst case. Re-measure before raising
  the interval's workload, and watch the `scheduler.timer_tick` duration in logs.

  A second run immediately after the first materialised **0** tasks, which is the
  idempotence the two-driver design depends on.
- **A rule already holding an open task is skipped** — PENDING *or* OVERDUE. The
  original guard and index covered PENDING alone, so the first sweep that marked a
  task overdue freed its rule and every tick after that added a copy. Corrected in
  migration `20260906000100`; see FINAL §13.

### The tester deploy collapses the two services into one (added PR HF, per FINAL §37)

The topology above is two services with private networking between them, and that
remains the shape PROD should have. It is not a shape any free host offers: free
tiers give you one always-on service and no private network between services, so
the two-box design cannot be expressed there at all.

Two collapsed forms exist in the repository, both pre-PR-24 and neither a target:

| | Two services (PROD, PR 24) | One container | One process |
|---|---|---|---|
| Where | Railway et al. | `Dockerfile`, `scripts/start.sh` | `app/ui/embedded_api.py` |
| Host | paid | any container host | Streamlit Community Cloud |
| API runs | own service | own process, same container | daemon thread in the UI process |
| UI reaches API by | private address | `127.0.0.1:8000` | `127.0.0.1:8000` |
| API is public | no | no | no |
| Scale/restart halves alone | yes | no | no |
| Crash isolation | yes | partial - `start.sh` kills both | none - one process |
| Application code touched | none | none | `embedded_api.py` + one call |

**The tester deployment is the third column**, because Hugging Face Spaces - the
container plan - stopped being free: its creation page now states that Gradio and
Docker Spaces require a paid plan, leaving only Static, which runs no Python. The
container files are kept, unused, because they are host-agnostic and are what a
move to Cloud Run or similar would use.

What the deviation costs is independent scaling, independent restart, and crash
isolation. What it does not cost is the security property the two-service design
was bought for: the API binds to `127.0.0.1`, only Streamlit's port is served, and
nothing outside can reach FastAPI. `SUPABASE_SERVICE_ROLE_KEY` and `AI_API_KEY`
sit in that process exactly as they sit on a developer's machine today, and the
browser still never sees either.

Nor does it move the seam PROJECT_STRUCTURE §7 draws: the UI still speaks HTTP to
the API and still holds no business logic. `embedded_api.py` starts a server; it
does not let a page reach past one.

Three operational notes specific to the single-process deployment:

- **`st.cache_resource` is what makes the server start once.** Streamlit re-runs
  the whole script on every interaction, so an unguarded call would try to bind
  the port again on the first click.
- **The in-process tick is the only scheduler.** There is no cron service, so
  `INTERNAL_TICK_INTERVAL_SECONDS` must stay non-zero. A free host sleeps when
  nobody is using it, and a sleeping process runs no sweep - so reminders and
  overdue transitions advance only while somebody is using the app. Acceptable for
  testers; not acceptable for PROD.
- **Route handlers are `async def` over synchronous Supabase I/O**, so requests
  serialise on the event loop. Invisible with one user; with several testers
  acting at once, a plant dashboard's ~1.6s of round trips is 1.6s during which
  nobody else's request progresses. The fix, when it is needed, is to drop `async`
  and let FastAPI use its threadpool.

## 4. CI/CD

Recommended flow:

```text
feature branch
→ pull request
→ automated tests
→ review
→ merge to dev
→ deploy DEV
→ acceptance
→ merge/release to main
→ deploy PROD
```

Production deployment should not occur directly from an unreviewed feature branch.

## 4a. Environment configuration that must differ between DEV and PROD

**Added in PR 20, per FINAL_SPECIFICATION §37.** `supabase/config.toml` is one file pushed to
whichever project is linked, so any value that should differ by environment is a release-checklist
item rather than something the file can express.

| Setting | DEV | PROD | Why |
|---|---|---|---|
| `auth.site_url` / `additional_redirect_urls` | `localhost:8501` | the deployed UI origin | A production project that still allows a localhost redirect is an open redirect into a developer's machine. |
| `auth.sessions.inactivity_timeout` | commented out | `12h` | The server-side half of the twelve-hour idle window (FINAL 22), and the only half that revokes. Paid-plan only: pushing it to the free DEV project returns `402 "User sessions can only be configured on Pro Plans and up"`, and because that fails the entire auth update, an uncommented value blocks every other setting in the file from reaching the project. Uncomment when PROD is on a paid plan. |
| `auth.site_url` | the deployed tester app | the production UI origin | Confirmation and password-reset emails link to whatever this says, and `sign_up` passes no `email_redirect_to`. DEV pointed at `localhost:8501` until PR HF, which sent every tester's confirmation link to their own machine. |

`auth.jwt_expiry` was a row here until PR HF, `43200` on DEV against `3600` on PROD, so
that a testing session survived a working day. The refresh-token cookie does that job
now, and the long expiry had begun to undermine it - it is `3600` in both environments
and no longer needs a checklist line.

**Verify before promoting to PROD:** `supabase config push` against the production project with
these values corrected, then confirm in the dashboard. The spec fixes no session lifetime, so both
values are deliberate choices rather than deviations.

## 5. Secrets

Secrets belong in the deployment platform's secret/environment-variable manager.

Never commit:

- API keys;
- Supabase service-role keys;
- email provider keys;
- AI provider credentials;
- JWT signing secrets;
- database passwords.

Rotate compromised credentials immediately.

## 6. Database Migrations

Production migrations must be:

- version controlled;
- reviewed;
- tested against DEV first;
- applied in a controlled deployment step.

Migration order should be compatible with currently deployed application versions whenever rolling deployment is possible.

Destructive schema changes should normally use a staged approach:

```text
add new structure
→ deploy compatible code
→ migrate data
→ remove old structure later
```

## 7. Storage Operations

Monitor:

- upload failures;
- invalid files;
- processing failures;
- storage growth;
- access-denied events.

Image lifecycle rules must follow the final privacy specification.

AI-used images that are removed from the user's visible experience remain retained for history/audit and are accessible only to Admin as required by the policy.

## 8. Monitoring

At minimum monitor:

### Application

- request count;
- latency;
- HTTP errors;
- authentication failures;
- unhandled exceptions.

### AI

- Agent executions;
- success/failure;
- retries;
- latency;
- token usage;
- estimated cost;
- model and prompt versions.

### Database

- connection errors;
- slow queries;
- migration failures;
- RLS/access errors.

### Notifications

- email attempts;
- successful sends;
- failures;
- duplicate-prevention/idempotency events.

## 9. Logging

Logs should contain enough information to troubleshoot requests without exposing secrets or unnecessary personal information.

Useful fields:

```text
timestamp
environment
request_id
user_id (where operationally appropriate)
plant_id (where operationally appropriate)
agent_type
status
duration
error_code
```

Do not log:

- passwords;
- API keys;
- raw authentication tokens;
- full sensitive prompts/responses unless explicitly required and protected.

## 10. Alerts

Recommended initial alerts:

- sustained API 5xx errors;
- repeated AI failures;
- migration failure;
- database connectivity failure;
- unusually high AI cost;
- notification provider failure;
- storage processing failure.

## 11. Rollback

Application rollback should be possible to the previous known-good deployment.

Database rollback is more complicated and should not rely on blindly reversing migrations.

Prefer forward-compatible corrective migrations.

## 12. Incident Procedure

For a production incident:

```text
detect
→ assess severity
→ contain
→ restore service
→ investigate
→ fix
→ verify
→ document
```

Security incidents require immediate credential rotation where applicable.

## 13. Backups and Recovery

Supabase backup and recovery capabilities should be enabled according to the selected production plan.

**The selected plan is Free (decided before PR 24).** That is a deliberate cost
decision with two consequences this document has to state plainly rather than
leave implied:

- **There is no point-in-time recovery.** "Confirm a recent recoverable backup"
  below cannot be satisfied the way it reads. Until the project is upgraded, the
  recovery position before a high-risk migration is the migration being reversible
  by a forward fix, plus whatever the free tier retains - not a restore.
- **A free project pauses after inactivity.** A paused project is indistinguishable
  from an outage to a user, and the first request after it wakes is slow.

Neither is a reason not to ship an MVP with no real users yet. Both become
release-checklist items the moment there are: **upgrade to a paid plan before real
user data exists**, alongside the `auth.jwt_expiry` divergence in §4a.

Before high-risk migrations:

- confirm a recent recoverable backup;
- verify migration against DEV;
- document recovery steps.

## 14. Admin Operations

Admin access is restricted to authorized Admin users.

Admin capabilities include:

- Knowledge Draft review;
- Knowledge publication;
- Approved Source management;
- Knowledge error handling;
- Agent monitoring;
- access to retained AI-used images where policy permits.

Published Knowledge Versions should not be deleted.

## 15. Operational Principle

Production operations must preserve the same domain rules as development.

Do not solve operational problems by bypassing:

- RLS;
- Agent contracts;
- approval workflows;
- immutable history;
- environment separation.
