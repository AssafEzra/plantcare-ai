# Deploying to Google Cloud Run

One container: uvicorn serves the API and the built React application from the same
origin. `Dockerfile` builds both halves — a Node stage runs `npm run build`, and the
Python stage copies the result to `SPA_DIST_DIR`, which `app/api/spa.py` serves.

This replaces `DEPLOY_STREAMLIT_CLOUD.md`. Streamlit Community Cloud cannot host this
app: its static file serving sends anything that is not an image, font, PDF, XML or
JSON as `Content-Type: text/plain` — deliberately — so `index.html` would render as
source and the browser would refuse the bundle. It is also one process publishing one
port, and that port belonged to Streamlit.

It runs against **DEV Supabase**. Testers create real accounts there, so take a dump
before inviting anyone and treat `scripts/scrub_dev_database.py` as the reset button.

> **Local Docker is not needed.** `gcloud builds submit` uploads the source and builds
> in Cloud Build. Only the `gcloud` CLI has to be installed.

## The live deployment

Stood up on 2026-10-03 and serving.

| | |
|---|---|
| URL | <https://plantcare-ai-mv5irloskq-ey.a.run.app> |
| Project | `plantcare-ai-174016` ("PlantCare AI"), billing account `01AC07-9768D2-DAD60C` |
| Region | `europe-west3` (Frankfurt) |
| Service | `plantcare-ai`, `--max-instances=1 --min-instances=0 --no-cpu-throttling` |
| Image | `europe-west3-docker.pkg.dev/plantcare-ai-174016/plantcare/plantcare-ai` |
| Scheduler | jobs `plantcare-tick-morning` (`30 7 * * *`) and `plantcare-tick-evening` (`0 19 * * *`), Asia/Jerusalem — see **3. The scheduler** |
| Database | **DEV** Supabase (`ckwvjyxeennrknwjsujl`) |

Redeploy with the command in §2; nothing in §0 or §1 needs repeating.

### Three things that went wrong the first time

Recorded because none of them announce themselves:

1. **`WORKDIR` creates its directory as root**, whatever `USER` is current, so
   `uv sync` could not create `.venv`. The Dockerfile now `mkdir`s and `chown`s
   before switching user. This bug had been latent since the file was written for
   Hugging Face Spaces, which went paid before anything was built from it.
2. **`.gcloudignore` uses .gitignore syntax, where patterns are not anchored** —
   unlike `.dockerignore`, where they are. A bare `supabase` line also matched
   `app/infrastructure/supabase/`, and the container died on
   `ModuleNotFoundError` before binding a port. Every pattern in that file now
   carries a leading slash, and a bare `*.md` would have taken `prompts/` with it.
3. **Cloud Build pushes `images:` only after every step finishes**, so a deploy
   step in the same build cannot find the tag. The push is its own step now.

And one that only shows up in production: **Google Frontend answers `/healthz`
itself**, so the liveness probe is `/livez`. See `docs/ENVIRONMENTS.md`.

## 0. Once per project

```bash
gcloud config set project <PROJECT_ID>

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com

gcloud artifacts repositories create plantcare \
  --repository-format=docker \
  --location=europe-west3
```

Frankfurt (`europe-west3`) to sit beside the Supabase project, which
`docs/ENVIRONMENTS.md` placed in `eu-central-1` for latency to Israel. A dashboard
makes about 1.6s of round trips; crossing an ocean for each one is the difference
between usable and not.

## 1. Secrets

Runtime secrets go in Secret Manager, never in the image and never in
`cloudbuild.yaml`. The anon key is the exception in the other direction — it is baked
into the bundle at build time because it ships to every browser anyway.

```bash
for name in supabase-url supabase-anon-key supabase-service-role-key \
            internal-tick-secret google-api-key; do
  gcloud secrets create "$name" --replication-policy=automatic
done

# Then one of these per secret, reading from stdin so the value never lands in shell
# history:
printf '%s' '<value>' | gcloud secrets versions add supabase-url --data-file=-
```

`internal-tick-secret` is any long random string; it guards `POST /v1/internal/tick`.

Let the runtime service account read them:

```bash
PROJECT_NUMBER=$(gcloud projects describe <PROJECT_ID> --format='value(projectNumber)')
for name in supabase-url supabase-anon-key supabase-service-role-key \
            internal-tick-secret google-api-key; do
  gcloud secrets add-iam-policy-binding "$name" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
done
```

`RESEND_API_KEY` and `RESEND_FROM_EMAIL` together enable email. Without both the app
runs with a null provider rather than failing, so they are optional — add them the
same way and extend `--set-secrets` when you want reminders actually sent.

### Phone push (VAPID)

Push needs one key pair, generated once and never rotated casually: every phone's
subscription is bound to the public key, so a new pair means every user has to turn
reminders on again.

```bash
npx web-push generate-vapid-keys      # prints a Public Key and a Private Key
```

Put all three in `.env` and let `scripts/deploy.py` reconcile them:

```
VAPID_PUBLIC_KEY=<public key>          # plain env var - it is sent to every browser
VAPID_PRIVATE_KEY=<private key>        # Secret Manager: vapid-private-key
VAPID_SUBJECT=mailto:<your address>    # a contact for the push services
```

Without the pair the app uses a null push provider: Settings says push is not set up
on the server, and deliveries are recorded as SKIPPED.

## 2. Build and deploy

```bash
uv run python scripts/deploy.py            # report what would be deployed
uv run python scripts/deploy.py --deploy   # build, push and deploy
```

Reporting by default, like the other scripts in `scripts/`. **Read the report** — see
the warning at the end of this section.

### `.env` is the source of truth

The service's settings come from `.env` and are reconciled on every deploy. They used
to live in a `--set-env-vars` line in `cloudbuild.yaml` as well, and because that flag
*replaces* the whole set, the two copies could disagree in silence. They did:
`KNOWLEDGE_MODEL` was changed to `gemini-3.6-flash` in the console while this
repository still said `gemini-3.5-flash-lite`, and the next build would have reverted
it without a word. Do not reintroduce hard-coded settings for convenience.

Three kinds of setting are deliberately not copied from `.env`:

- **Secrets** go to Secret Manager and are referenced by name. A value passed through
  `--set-env-vars` is readable in `gcloud run services describe` and in the console,
  and `SUPABASE_SERVICE_ROLE_KEY` bypasses RLS. The script compares each secret
  against `.env` and adds a new version only where they differ, so a deploy that
  changes nothing leaves no trail of identical versions.
- **Three production overrides**, where the local value is wrong rather than merely
  different: `APP_ENV=production` (disables `/docs`), `APP_DEBUG=false`, and
  `INTERNAL_TICK_INTERVAL_SECONDS=0` (Cloud Scheduler drives the sweep).
- **Container facts** — `SPA_DIST_DIR` is set by the `Dockerfile`, `PORT` by Cloud
  Run. Neither should come from a developer's machine.

The copied list is an allowlist in `scripts/deploy.py`, not a denylist, so a new
secret added to `.env` cannot reach the service's plain configuration because somebody
forgot to exclude it.

`cloudbuild.yaml` now only builds and pushes. The three `VITE_` values stay there
because they are genuinely build inputs: Vite replaces `import.meta.env.VITE_*` at
build time, so the Supabase project a bundle talks to is fixed when the image is
built. One image is one environment, and pointing a deployment at a different project
means rebuilding.

> **`.env` is what ships.** An experiment left in it reaches the service on the next
> deploy — that is the point of one source of truth, and also its sharp edge. The
> report prints the resolved settings and the Supabase project before anything runs,
> and warns when the working tree is dirty, because `gcloud builds submit` uploads the
> working tree rather than the commit.

`VITE_API_BASE_URL` stays empty. The browser asks for a relative `/v1`, which is the
same origin the page came from — which is why there is no CORS configuration anywhere
in this repository.

### The flags that are not tuning

`scripts/deploy.py` passes four that each prevent a specific failure:

| Flag | Without it |
|---|---|
| `--no-cpu-throttling` | Every agent run hangs. All four agents run in a FastAPI `BackgroundTask` *after* their 202 is sent, with budgets up to 600s for knowledge research. Cloud Run's default request-based CPU allocation throttles the instance to near zero the moment a response goes out, which is exactly when that work starts. |
| `--max-instances=1` | AI rate limits multiply. The limiter keeps its counters in process memory (`app/api/rate_limit.py`), so N instances permit N times the configured limit. `docs/ENVIRONMENTS.md` says what replacing it would take. |
| `--timeout=900` | The scheduler tick is cut off. `POST /v1/internal/tick` runs the sweep synchronously inside the request and a full sweep was measured at 6m11s against a populated database (DEPLOYMENT §3); the default is 300s. |
| `INTERNAL_TICK_INTERVAL_SECONDS=0` | Two schedulers, for no benefit. The in-process timer cannot be relied on here (§3 below), and the cron is the one that works. |

`--min-instances=0` is the cost decision, and on its own it is not enough — see
**What this actually costs** below. Nothing is billed only while the instance is
genuinely gone, and what keeps it alive is traffic of any kind, including the cron.
The price of scaling to zero is a few seconds on the first request after idle.

## What this actually costs

Read this before changing the cron frequency, because the first version of this
document got it wrong and the bill proved it.

`--no-cpu-throttling` moves the service to **instance-based billing**: charged for
the instance's whole life, not per request. So the bill follows how long the
container is *awake*, and awake is decided by traffic — a page load, a bot, a
probe, or the cron.

Measured on 2026-10-03 with the cron at `*/15 * * * *`: **one instance stayed alive
4 hours 39 minutes continuously.** A 15-minute poke never lets Cloud Run reclaim
it, so the container was awake 24/7.

| | |
|---|---|
| Awake | ~730 h/month |
| Free allowance | 240,000 vCPU-s ≈ **67 h/month** (plus 450,000 GiB-s) |
| Billable | 2,388,000 vCPU-s × $0.000018 + memory |
| **Total** | **≈ $47/month** |

There is no configuration fix: no release track of `gcloud run deploy` has an
idle-timeout flag, so a warm instance cannot be made cheaper. The only lever is how
often something wakes it.

**`--no-cpu-throttling` is not what costs the money.** During a real session the
instance is alive anyway, so always-on CPU is free then and it is what keeps agent
runs working. The cost was entirely the cron waking a container nobody was using.

Hence the cadence below.

## 3. The scheduler

**This is not optional.** Without it nothing materialises care tasks, nothing goes
overdue, no `MISSED` event is written and no reminder is sent — the same failure
FINAL §13 describes, reached a different way.

The API carries its own timer, and on Cloud Run it cannot be trusted: the loop lives
in the FastAPI lifespan, and an instance that has scaled to zero runs no loop. It also
sleeps *before* its first sweep, so an instance that lives under 15 minutes sweeps
zero times no matter what. Hence `INTERNAL_TICK_INTERVAL_SECONDS=0` and a real cron.

```bash
SERVICE_URL=$(gcloud run services describe plantcare-ai \
  --region=europe-west3 --format='value(status.url)')

# Morning: Today and Due by email and push, at 07:30.
gcloud scheduler jobs create http plantcare-tick-morning \
  --location=europe-west3 \
  --schedule='30 7 * * *' \
  --time-zone=Asia/Jerusalem \
  --uri="${SERVICE_URL}/v1/internal/tick" \
  --http-method=POST \
  --headers="X-Internal-Secret=<the internal-tick-secret value>" \
  --attempt-deadline=900s

# Evening: the optional push for today's tasks still open, at 19:00.
gcloud scheduler jobs create http plantcare-tick-evening \
  --location=europe-west3 \
  --schedule='0 19 * * *' \
  --time-zone=Asia/Jerusalem \
  --uri="${SERVICE_URL}/v1/internal/tick" \
  --http-method=POST \
  --headers="X-Internal-Secret=<the internal-tick-secret value>" \
  --attempt-deadline=900s

# The old every-3-days job is replaced by these two:
gcloud scheduler jobs delete plantcare-tick --location=europe-west3
```

**Since the notifications change (migration 0022): twice a day, at 07:30 and 19:00.**
The reminders are now daily - Today and Due each morning, an optional evening push -
and a reminder can only go out on a run, so the every-3-days cadence below would
deliver them up to three days late. The runs sit exactly on the reminder times
because the send window is "at or after the time, until midnight": a 07:30 run sends
the 07:30 reminders, and a later run the same day would catch up anything it missed.

Cost: each run keeps an instance awake for roughly its idle timeout - on the order of
fifteen minutes - so two runs a day is about 15 hours a month, inside the 67-hour free
allowance described above. That figure is an estimate; the billing report is the
check. The times are Jerusalem time: a user in another timezone is reminded at the
first run after their own 07:30.

The history of the previous cadence is kept below because its reasoning about cost
still holds.

**Once every 3 days, at 08:00** — `0 8 */3 * *`. Not fifteen minutes, and the
reasoning that used to be here was wrong.

That reasoning said fifteen minutes was needed because the send window is a window
rather than an instant. Reading `_within_send_window`
(`app/notifications/service.py:186-200`) shows it is an open-ended `>=` comparison:
true from the user's preferred hour until local midnight, a 16-hour span for the
default 08:00. There is no 15-minute band to hit. **Cadence is a latency setting,
not a correctness one** — the unique index on `notification_deliveries.dedupe_key`
is what prevents a double send, and it does that at any frequency.

08:00 rather than midnight so the tick lands exactly when the reminder window
opens. `*/3` on day-of-month restarts each month, so one gap per month is 1–2 days
instead of 3; cron cannot express a true 72-hour period.

What 3 days costs, stated plainly:

- **Nothing for task creation.** `HORIZON_DAYS = 14`
  (`app/domain/rules/recurrence.py:34`) materialises up to a fortnight ahead.
- **Nothing for the task list.** `today_care` is computed live per request from
  `due_at_utc` (`app/api/routers/care_tasks.py:186`), so a due task appears on
  משימות whether or not a sweep has run.
- **A late task keeps its `PENDING` label** for up to 3 days instead of flipping to
  `OVERDUE`, so the "late" band under-reports. The task is still listed and still
  actionable.
- **Reminders arrive up to 3 days late**, and the daily digest only lands on days a
  tick runs, because its key is `digest:{user}:{local day}`.
- **A stuck "analysing" spinner** waits up to 3 days for `reap_abandoned`, which
  only matters if a container died mid-run.

Raise the frequency and the bill rises with it, roughly in proportion to how often
the container is woken. Hourly is in the single-digit dollars; 15 minutes is $47.

Calling it twice changes nothing: `run_tick` is idempotent by construction —
materialisation skips a rule that already holds an open task, the database refuses a
second one regardless, and reminders deduplicate on
`notification_deliveries.dedupe_key`.

Cloud Scheduler's free tier is 3 jobs per billing account, and frequency does not
affect *its* price — but it very much affects Cloud Run's, which is the trap the
section above exists to document. At this cadence the job is no longer a keep-warm,
so expect a cold start of a few seconds on the first request after a quiet spell.

Check it:

```bash
gcloud scheduler jobs run plantcare-tick --location=europe-west3
gcloud run services logs read plantcare-ai --region=europe-west3 --limit=50
```

A successful sweep logs `request.complete` for `/v1/internal/tick` with status 200.
`scheduler.timer_started` must **not** appear — that would mean the in-process timer
is also running.

## 4. Point Supabase Auth at the new origin

`supabase/config.toml` still names the Streamlit app, deliberately: it is pushed to
whichever project is linked, and until this deploy exists that is the host real
testers use. The Cloud Run URL is only knowable after the first deploy.

Once `SERVICE_URL` is real, in `supabase/config.toml`:

- set `site_url` to it,
- add it to `additional_redirect_urls`,
- remove the `*.streamlit.app` entries,

then `supabase config push --project-ref ckwvjyxeennrknwjsujl`. `auth: up_to_date`
means remote matches the file exactly.

Confirmation and password-reset emails link to `site_url` and `sign_up` passes no
`email_redirect_to`, so this value alone decides where a new tester lands. Skip it and
every invitation points at a host that is no longer serving.

## 5. Before you send the link to anyone

The service is `--allow-unauthenticated`, so anyone with the URL can open it.

- **Turn off open signup** in Supabase → Authentication → Providers, and create tester
  accounts yourself. The 10/user/hour AI limit is per user and caps nothing globally,
  so a stranger who finds the URL can spend the whole budget.
- **Check email confirmation.** If it is on and no SMTP is configured, testers
  register and can never sign in.
- **Take a database dump.** The free Supabase plan has no point-in-time recovery.
- **Put a spend cap on the AI key.** `cloudbuild.yaml` points all four agents at
  `google/gemini-3.5-flash-lite` rather than the defaults in `.env.example`, so a
  tester deployment cannot quietly spend an Opus budget. Change all eight variables
  together or not at all — naming a Gemini model without the matching
  `*_PROVIDER=google` boots the Anthropic adapter holding a model name it cannot use.

## Known limits of this deployment

- **A long agent run can still lose its instance.** `--no-cpu-throttling` keeps the
  CPU, but Cloud Run decides an instance is idle from requests in flight, and
  background work is invisible to it. `agent_requests.reap_abandoned` exists for
  exactly this and marks the row rather than leaving it QUEUED forever, so the
  interface says the run did not finish instead of waiting on it.
- **AI quotas reset on a cold start.** The rate limiter is process memory, and
  scaling to zero discards it.
- **Requests serialise.** Route handlers are `async def` over synchronous Supabase
  I/O, so one request holds the event loop for its whole duration — about 1.6s for a
  plant dashboard. Fine for a few testers; the fix, when it is needed, is to drop
  `async` and let FastAPI's threadpool take them.
- **One instance, so one failure.** `--max-instances=1` is there to keep the rate
  limiter honest, and it means there is no redundancy at all.
- **The free Supabase project pauses** after inactivity, independently of this.
- **Instance-based billing, and it has already bitten once.**
  `--no-cpu-throttling` bills for the instance's whole life rather than per
  request. `--min-instances=0` makes an idle week free only if the instance is
  actually allowed to go idle — a 15-minute cron kept it awake 24/7 and cost
  $47/month. The cron frequency is the cost control; see **What this actually
  costs**. Check the bill after any change to it.
