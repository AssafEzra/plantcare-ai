# Deploying to Hugging Face Spaces

A free, single-container deployment for putting the app in front of testers
*before* PR 24 builds the real production hosting. The topology deviation it
involves is recorded in `PlantCare_AI_Spec/DEPLOYMENT_AND_OPERATIONS.md` §3.

It runs against **DEV Supabase**. Testers create real accounts in the database the
scrub left clean, so take a dump before inviting anyone, and treat
`scripts/scrub_dev_database.py` as the reset button.

## 1. Create the Space

At <https://huggingface.co/new-space>, with:

- **SDK: Docker** — *not* the Streamlit SDK, which runs one process and would
  bring the UI up with no API behind it
- **Visibility: Private** — a private Space is the safe rehearsal. Make it public
  only when you want testers in.

## 2. Set the secrets

Space → Settings → *Variables and secrets*. Nine values have no default and the
process will not start without them (`app/config/settings.py`):

| Secret | Where it comes from |
|---|---|
| `SUPABASE_URL` | Supabase → Project Settings → API |
| `SUPABASE_ANON_KEY` | same page |
| `SUPABASE_SERVICE_ROLE_KEY` | same page. Bypasses RLS — **secret**, never a variable |
| `AI_API_KEY` | your Anthropic key. **Put a spend cap on it first.** |
| `IDENTIFICATION_MODEL` | `claude-opus-5` |
| `KNOWLEDGE_MODEL` | `claude-opus-5` |
| `CARE_MODEL` | `claude-opus-5` |
| `HEALTH_MODEL` | `claude-opus-5` |
| `INTERNAL_TICK_SECRET` | any long random string; it guards `/v1/internal/tick` |

Optional: `RESEND_API_KEY` and `RESEND_FROM_EMAIL` together enable email. Without
both, the app runs with a null email provider rather than failing.

Do **not** set `API_BASE_URL` — the Dockerfile pins it to `http://127.0.0.1:8000`,
which is the whole point of the single container.

`INTERNAL_TICK_INTERVAL_SECONDS` must stay non-zero here: there is no cron
service, so the in-process timer is the only thing that materialises tasks or
marks anything overdue.

## 3. Push this branch to the Space

A Space is a git repository. Authenticate once, then push the branch to its
`main`:

```bash
huggingface-cli login                       # paste a token from hf.co/settings/tokens
git remote add space https://huggingface.co/spaces/<user>/<space>
git push space pr-HF-free-deploy:main
```

The build log is on the Space's page. It takes a few minutes the first time.

## 4. Before you send the link to anyone

- **Turn off open signup** in Supabase → Authentication → Providers, and create
  the tester accounts yourself. A public URL with open signup means any stranger
  who finds it can spend your AI budget; the 10/user/hour limit is per user and
  caps nothing globally.
- **Check email confirmation.** If it is on and no SMTP is configured, testers
  register and can never sign in.
- **Take a database dump.** The free Supabase plan has no point-in-time recovery.

## Known limits of this deployment

- **It sleeps.** A free Space idles out, and so does a free Supabase project. The
  first visitor after a quiet spell waits for both to wake. While asleep nothing
  runs the scheduler sweep, so reminders and overdue transitions only advance
  while somebody is using the app.
- **Requests serialise.** Route handlers are `async def` over synchronous Supabase
  I/O, so one request holds the event loop for its whole duration — about 1.6s for
  a plant dashboard. Fine for a few testers who rarely click at the same instant;
  the fix, when it is needed, is to drop `async` and let FastAPI's threadpool take
  them.
- **One process pair.** Neither half can be restarted or scaled without the other;
  `scripts/start.sh` deliberately kills the container if either dies.
