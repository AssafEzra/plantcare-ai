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
| Scheduler | job `plantcare-tick`, `*/15 * * * *`, Asia/Jerusalem |
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

## 2. Build and deploy

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_SUPABASE_URL=https://<ref>.supabase.co,_SUPABASE_ANON_KEY=<anon key>
```

Both substitutions are required and the build refuses without them. They are *build*
inputs, not runtime ones: Vite replaces `import.meta.env.VITE_*` at build time, so the
Supabase project a bundle talks to is fixed when the image is built. One image is one
environment, and pointing a deployment at a different project means rebuilding.

`VITE_API_BASE_URL` stays empty. The browser asks for a relative `/v1`, which is the
same origin the page came from — which is why there is no CORS configuration anywhere
in this repository.

### The flags that are not tuning

`cloudbuild.yaml` passes four that each prevent a specific failure:

| Flag | Without it |
|---|---|
| `--no-cpu-throttling` | Every agent run hangs. All four agents run in a FastAPI `BackgroundTask` *after* their 202 is sent, with budgets up to 600s for knowledge research. Cloud Run's default request-based CPU allocation throttles the instance to near zero the moment a response goes out, which is exactly when that work starts. |
| `--max-instances=1` | AI rate limits multiply. The limiter keeps its counters in process memory (`app/api/rate_limit.py`), so N instances permit N times the configured limit. `docs/ENVIRONMENTS.md` says what replacing it would take. |
| `--timeout=900` | The scheduler tick is cut off. `POST /v1/internal/tick` runs the sweep synchronously inside the request and a full sweep was measured at 6m11s against a populated database (DEPLOYMENT §3); the default is 300s. |
| `INTERNAL_TICK_INTERVAL_SECONDS=0` | Two schedulers, for no benefit. The in-process timer cannot be relied on here (§3 below), and the cron is the one that works. |

`--min-instances=0` is the cost decision: nothing runs, and nothing is billed, while
nobody is using it. The price is a few seconds on the first request after an idle
period.

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

gcloud scheduler jobs create http plantcare-tick \
  --location=europe-west3 \
  --schedule='*/15 * * * *' \
  --time-zone=Asia/Jerusalem \
  --uri="${SERVICE_URL}/v1/internal/tick" \
  --http-method=POST \
  --headers="X-Internal-Secret=<the internal-tick-secret value>" \
  --attempt-deadline=900s
```

Fifteen minutes because `app/notifications/service.py` treats the send window as a
window rather than an instant on that assumption — a reminder that required the clock
to land exactly on 08:00 would silently not arrive on a day a deploy overlapped it.

Calling it twice changes nothing: `run_tick` is idempotent by construction —
materialisation skips a rule that already holds an open task, the database refuses a
second one regardless, and reminders deduplicate on
`notification_deliveries.dedupe_key`.

Cloud Scheduler's free tier is 3 jobs per billing account, and frequency does not
affect the price. The job doubles as the keep-warm, which is why cold starts are
rarely visible in practice.

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
- **Instance-based billing.** `--no-cpu-throttling` bills for the instance's whole
  life rather than per request, against a monthly free allowance. With
  `--min-instances=0` an idle week costs nothing, but a busy one is the thing to watch
  if a bill appears.
