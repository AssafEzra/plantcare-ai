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
| `auth.jwt_expiry` | `43200` (12h) | **`3600` (1h)** | DEV runs long so a testing session survives a working day. A twelve-hour access token in production widens the window a leaked token is useful for, and the refresh token already makes a one-hour expiry invisible to a user. |
| `auth.site_url` / `additional_redirect_urls` | `localhost:8501` | the deployed UI origin | A production project that still allows a localhost redirect is an open redirect into a developer's machine. |

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
