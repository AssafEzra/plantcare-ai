# Environments

Two entirely separate Supabase projects. Local development points at DEV, never PROD
(`SETUP_AND_ENVIRONMENT §6`, `DEPLOYMENT_AND_OPERATIONS §2`).

| | DEV | PROD |
|---|---|---|
| Supabase project | `plantcare-dev` | not yet created (Phase 17) |
| Project ref | `ckwvjyxeennrknwjsujl` | — |
| Region | `eu-central-1` (Frankfurt) | `eu-central-1` |
| Organization | `plantcare` | `plantcare` |
| Purpose | all development and automated tests | production only |

Frankfurt was chosen for latency to Israel (~50-70 ms); both environments must share a
region so latency behaviour matches.

## Variables

Names live in `.env.example`; values never do. `app/config/settings.py` is the only module
that reads them — a ruff `banned-api` rule rejects `os.environ` anywhere else.

| Variable | Owner | Notes |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | per environment | anon key is safe in the UI process |
| `SUPABASE_SERVICE_ROLE_KEY` | per environment | **server-side only**, never reaches Streamlit |
| `SUPABASE_DB_PASSWORD` | per environment | Supabase CLI + integration tests only |
| `AI_API_KEY`, `*_MODEL` | shared or per environment | all four agents default to `claude-opus-5` |
| `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | per environment | optional — a null email provider is used when unset |
| `INTERNAL_TICK_SECRET` | per environment | guards `POST /v1/internal/tick` |

## Applying migrations

```bash
supabase link --project-ref <ref>
supabase db push          # DEV first, always
```

Migrations are version-controlled in `supabase/migrations/` and reviewed before they reach
PROD. Never make an undocumented manual schema change. Corrections are forward-fix
migrations, not edits to an applied file (`DEPLOYMENT §11`).

## Integration tests

`tests/integration/` connects directly to DEV through the session pooler
(`aws-0-eu-central-1.pooler.supabase.com:5432`) to exercise triggers and RLS. It drops from
`postgres` to the `authenticated` role before testing any policy — a superuser bypasses RLS
and would make every policy assertion vacuously pass. These tests are excluded from CI,
which has no database.

## Known gaps

- PROD project not created (Phase 17).
- `AI_API_KEY` is a placeholder; a real key is needed before Phase 8.
- No seed data yet (Phase 2, PR 6).

## Auth settings

Held in `supabase/config.toml` and applied with `supabase config push --project-ref <ref>`,
so they are reviewable and reproducible rather than clicked into a dashboard.

| Setting | Value | Why |
|---|---|---|
| `enable_confirmations` | `true` | FINAL §22 lists email verification in MVP scope; Supabase defaults it off |
| `minimum_password_length` | `8` | 6 is Supabase's floor and weak for an account holding personal data |
| `otp_length` | `8` | keeps the stronger remote default rather than the CLI's 6 |
| `max_frequency` | `60s` | 1s permits trivial mail-bombing of an inbox through repeated signup |
| `site_url` | `http://localhost:8501` | Streamlit's port; verification and reset links resolve here |

`supabase config push` reporting `auth: up_to_date` means remote matches this file exactly.
