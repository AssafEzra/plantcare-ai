# Deploying to Streamlit Community Cloud

A free deployment for putting the app in front of testers *before* PR 24 builds
the real production hosting. Free with no card, and it deploys straight from this
GitHub repository.

Community Cloud runs **one process**, so the API runs inside the Streamlit
process on a daemon thread (`app/ui/embedded_api.py`, switched on by
`EMBEDDED_API`). The deviation and what it costs are recorded in
`PlantCare_AI_Spec/DEPLOYMENT_AND_OPERATIONS.md` §3.

> Hugging Face Spaces was the first plan and is no longer free: its own creation
> page now says "Gradio and Docker Spaces require a paid plan", leaving only
> Static, which runs no Python. The `Dockerfile` and `scripts/start.sh` in this
> repository are kept because they are host-agnostic — they are what a container
> host such as Cloud Run would use, and they need no application code at all.

It runs against **DEV Supabase**. Testers create real accounts in the database the
scrub left clean, so take a dump before inviting anyone, and treat
`scripts/scrub_dev_database.py` as the reset button.

## 1. Create the app

At <https://share.streamlit.io> → *Create app* → *Deploy from GitHub*:

| Field | Value |
|---|---|
| Repository | `AssafEzra/plantcare-ai` |
| Branch | `pr-HF-free-deploy` (switch to `dev` once it is merged) |
| Main file path | `app/ui/streamlit_app.py` |
| Python version | 3.12 or newer |

Dependencies come from `requirements.txt`, which is generated from `uv.lock` —
regenerate it with `uv export --format requirements-txt --no-dev --no-hashes -o
requirements.txt` whenever a dependency changes, or Community Cloud will install
the old set. Its `-e .` line matters: it puts the repository itself on the path,
which is what keeps `prompts/` findable at runtime.

## 2. Set the secrets

*Advanced settings → Secrets*, in TOML. Streamlit promotes top-level string
values to environment variables at server bootstrap, before the app script runs,
which is how `pydantic-settings` sees them.

```toml
SUPABASE_URL = "https://<ref>.supabase.co"
SUPABASE_ANON_KEY = "..."
SUPABASE_SERVICE_ROLE_KEY = "..."     # bypasses RLS - secret, never public
ANTHROPIC_API_KEY = "..."             # put a spend cap on it first
IDENTIFICATION_MODEL = "claude-opus-5"
KNOWLEDGE_MODEL = "claude-opus-5"
CARE_MODEL = "claude-opus-5"
HEALTH_MODEL = "claude-opus-5"

# Optional. Vendor per agent - anthropic (default) | google | openai. Add the
# matching GOOGLE_API_KEY or OPENAI_API_KEY when you point one at another vendor.
# IDENTIFICATION_PROVIDER = "google"
INTERNAL_TICK_SECRET = "<any long random string>"

# The two that make this a single-process deployment.
EMBEDDED_API = "true"
API_BASE_URL = "http://127.0.0.1:8000"
```

An existing deployment whose secret is still `AI_API_KEY` keeps working: it is
accepted as a fallback for `ANTHROPIC_API_KEY`. Rename it when convenient - the
fallback exists so a push cannot break the app before the secret is edited.

`RESEND_API_KEY` and `RESEND_FROM_EMAIL` together enable email. Without both, the
app runs with a null email provider rather than failing.

Leave `INTERNAL_TICK_INTERVAL_SECONDS` alone. There is no cron service here, so
the API's own timer is the only thing that materialises tasks or marks anything
overdue.

## 3. Before you send the link to anyone

Community Cloud apps are **public** — anyone with the URL can open it.

- **Turn off open signup** in Supabase → Authentication → Providers, and create
  the tester accounts yourself. Otherwise any stranger who finds the URL can
  spend your AI budget: the 10/user/hour limit is per user and caps nothing
  globally.
- **Check email confirmation.** If it is on and no SMTP is configured, testers
  register and can never sign in.
- **Take a database dump.** The free Supabase plan has no point-in-time recovery.

## Known limits of this deployment

- **One process, so one failure.** The API and the UI share a process: an
  unhandled crash takes both, and neither can be restarted or scaled alone.
- **It sleeps.** Community Cloud idles an unused app out, and a free Supabase
  project pauses too. While asleep nothing runs the scheduler sweep, so reminders
  and overdue transitions only advance while somebody is using the app.
- **Requests serialise.** Route handlers are `async def` over synchronous
  Supabase I/O, so one request holds the event loop for its whole duration —
  about 1.6s for a plant dashboard. Fine for a few testers who rarely click at the
  same instant; the fix, when it is needed, is to drop `async` and let FastAPI's
  threadpool take them.
- **Resources are modest.** Image processing and four agents in the same process
  as the UI. If it falls over under real use, that is the signal to move to a
  container host with the `Dockerfile` already in this repository.
