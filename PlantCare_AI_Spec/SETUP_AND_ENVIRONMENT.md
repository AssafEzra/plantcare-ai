# PlantCare AI — Setup & Environment

## 1. Purpose

This document describes how to prepare a local development environment, configure secrets, connect to Supabase, run the application, and work with database migrations.

## 2. Prerequisites

Recommended baseline:

- Python 3.12+
- Git
- Supabase project
- Node.js only if required by selected Supabase CLI tooling
- A supported browser
- Access to configured AI provider credentials
- Resend account for MVP email notifications

## 3. Clone and Branch

```bash
git clone <repository>
cd plantcare-ai

git checkout dev
```

`main` represents production-ready code. `dev` is the normal integration branch.

Feature branches should be created from `dev`:

```text
feature/<short-description>
fix/<short-description>
chore/<short-description>
```

## 4. Python Environment

Example:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies using the repository's package manager configuration.

## 5. Environment Variables

Copy:

```text
.env.example
```

to:

```text
.env
```

Never commit `.env`.

The exact values are environment-specific. Typical configuration includes:

```text
APP_ENV=development
APP_DEBUG=true

SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=

IDENTIFICATION_MODEL=
KNOWLEDGE_MODEL=
CARE_MODEL=
HEALTH_MODEL=

AI_PROVIDER=
AI_API_KEY=

RESEND_API_KEY=
RESEND_FROM_EMAIL=

DEFAULT_TIMEZONE=Asia/Jerusalem
```

Service-role credentials must only be used server-side and must never be exposed to Streamlit browser code.

## 6. Supabase Environments

DEV and PROD must use separate Supabase environments.

Development code and tests must use DEV.

Production data must not be used as a routine development/test database.

## 7. Database Migrations

All schema changes must be represented by version-controlled migrations.

Recommended workflow:

```text
change schema
→ create migration
→ review migration
→ apply to DEV
→ run tests
→ promote to PROD
```

Never make undocumented manual schema changes in PROD.

Migration files should be deterministic and safe to review.

## 8. Storage

Supabase Storage is used for plant images.

Logical path:

```text
plant-images/{user_id}/{plant_id}/{gallery|identification|health}/
```

The application validates file type and size before upload.

Maximum image size:

```text
10 MB
```

Supported types:

```text
JPG / JPEG / PNG / WEBP
```

Original, processed, and thumbnail representations may be retained according to the image lifecycle rules in the final specification.

## 9. Running Locally

The exact command may depend on the final package configuration. The intended development topology is:

```text
Streamlit UI → FastAPI → application services → Supabase
                                      ↘ AI Gateway
                                      ↘ Notification Service
```

Run the API and UI as separate development processes when using the separated architecture.

## 10. Local Development Rules

- Never paste secrets into source code.
- Never commit `.env`.
- Use `.env.example` for variable names only.
- Do not point local development at PROD.
- Do not disable RLS merely to make local development easier.
- Log identifiers and metadata, not secrets.
- Use test accounts and test plants.

## 11. Configuration Validation

Application startup should validate required configuration and fail clearly when a required secret or endpoint is missing.

Optional integrations should be feature-configurable rather than causing the whole application to fail.

## 12. Developer Checklist

Before coding:

- [ ] Repository cloned
- [ ] `dev` checked out
- [ ] Python environment created
- [ ] Dependencies installed
- [ ] `.env` created
- [ ] DEV Supabase configured
- [ ] Database migrations applied
- [ ] Storage configured
- [ ] AI provider configured
- [ ] Resend configured for email testing
- [ ] Tests execute successfully
- [ ] Local UI opens successfully
