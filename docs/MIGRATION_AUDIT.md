# Migration Audit — Streamlit to React

Phase 1 output for the React migration handoff, in the shape its §49 asks for.
Produced by reading the repository at commit `328b894`; every claim below was checked
against code rather than against the existing documentation, because that
documentation predates several decisions.

**Nothing has been migrated. No branch has been created. This is the audit only.**

---

## 1 · Existing architecture

| layer | what is actually there |
|---|---|
| Frontend | Streamlit, confined entirely to `app/ui/`. 7 page modules, 17 components, 3 state modules. Navigation via `st.navigation`/`st.Page` (`app/ui/streamlit_app.py:100-148`). |
| Backend | FastAPI. 13 routers, 67 endpoints, all under `/v1`. Mounted in `app/api/main.py:256-267`. |
| Database | Supabase Postgres, 29 tables, 17 migrations. RLS on every user-owned table. |
| Auth | Supabase Auth, called **directly from the Streamlit layer** (`app/ui/state/session.py`). There is no auth router. The API only *verifies* bearer tokens. |
| Storage | Supabase Storage, one bucket `plant-images` (`app/config/settings.py:52`). |
| AI | 4 agents (identification, knowledge, care, health). Provider per agent and model per agent, both configurable. Structured output with 2 schema retries plus a separate transient-failure budget. |
| Admin | 9 tabs in one Streamlit page (`app/ui/app_pages/admin.py`, 830 lines), served by 10 `/v1/admin/*` endpoints plus 13 admin knowledge endpoints. |
| Deployment | Streamlit Community Cloud, single process. **FastAPI runs on a daemon thread inside the Streamlit process** when `EMBEDDED_API` is set (`app/ui/embedded_api.py`) — a recorded deviation from DEPLOYMENT §3, because that host runs one process from one repository. |

The seam the migration depends on is real: **no module outside `app/ui/` imports
streamlit.** Verified across `app/` and `scripts/`.

---

## 2 · Existing UI inventory

### Pages

| page | lines | flow |
|---|---|---|
| `auth.py` | 87 | Three tabs: sign in, register, forgot password. The only screen that talks to Supabase directly — obtaining a credential is not a business operation. |
| `home.py` | 227 | Action-oriented dashboard: today's care with inline done/skip, plants needing attention, counts, upcoming care. |
| `my_plants.py` | 77 | Plant grid. One call to `/v1/plants`; filtering is server-side via query params. |
| `add_plant.py` | 242 | Three steps: upload 1–4 photographs → identification run with polling → confirmation. Step state lives in `st.session_state` so a rerun cannot lose a half-finished flow. |
| `plant_dashboard.py` | 735 | The hub. Hero image and status, gallery, species and knowledge, care plan and proposals, upcoming tasks, health history and trend, environment form, history timeline, knowledge error reporting. |
| `settings.py` | 147 | Profile (display name, timezone) and notification preferences, plus the user's own delivery log. |
| `admin.py` | 830 | 9 tabs: overview, knowledge drafts, published knowledge, approved sources, user reports, agent monitoring, sent notifications, audit log, accounts (including view-as-user). |

### Components (17)

`agent_progress` (polls `/v1/agent-requests/{id}` through five stages),
`care_plan`, `care_task_card`, `environment_form`, `health_card`,
`health_check_dialog`, `identification_card`, `image_picker`, `layout`,
`plant_card`, `proposal_dialog`, `review_badge`, `session_store`, `sources`,
`status`, `timeline`.

### State (3)

- `session.py` — Supabase auth calls, token refresh, session persistence.
- `api_client.py` — HTTP wrapper, bearer header, `cached_get`, act-as header.
- `view_as.py` — admin impersonation banner and target.

`session_store.py` is a custom Streamlit component that exists only to survive a
page refresh. **React deletes it** — the browser does this natively.

---

## 3 · API inventory

67 endpoints. Everything React needs is here, with the exceptions in §5.

**Profile** (2) — `GET|PATCH /v1/me`

**Plants** (8) — `POST|GET /v1/plants`, `GET|PATCH /v1/plants/{id}`,
`POST .../archive`, `POST .../restore`, `GET|PUT .../environment`.
`GET /v1/plants` accepts `status`, `health_status`, `q`.

**Plant detail** (3) — `GET .../dashboard`, `GET|POST .../history`

**Images** (3) — `GET|POST /v1/plants/{id}/images`, `DELETE .../{image_id}`

**Identification** (4) — `POST .../identification-runs`,
`GET /v1/identifications/{id}`, `POST .../confirm`, `POST .../correct`.
Images per run: 1–4 (`identification.py:79`).

**Care** (7) — `GET .../care-plan`, `GET|POST .../care-plan/proposals`,
`POST .../care-plan/adjustment-proposals`,
`POST /v1/care-plan-proposals/{id}/approve|reject`,
`POST /v1/care-plan-versions/{id}/operational-adjustment`

**Care tasks** (5) — `GET /v1/care-tasks`, `POST .../done|skip`,
`GET /v1/dashboard`, `POST /v1/internal/tick` (secret-gated, not for React)

**Health** (3) — `POST .../health-checks`, `GET /v1/health-assessments/{id}`,
`GET .../health-history`. Images per check: 1–4
(`app/agents/health/contract.py:33-34`).

**Knowledge** (2 user, 13 admin) — `GET /v1/species/{id}/knowledge`,
`POST .../knowledge-reports`; drafts list/detail/approve/reject/retry, research
trigger, versions list/detail/by-species, approved sources create/patch/disable.

**Notifications** (3) — `GET|PUT /v1/notification-preferences`,
`GET /v1/notification-deliveries`

**Admin** (10) — overview, agent-executions, agent-requests, knowledge-reports and
review, notification-deliveries, audit-log, accounts, view-as, anonymize

**Agent polling** (1) — `GET /v1/agent-requests/{request_id}`

---

## 4 · Migration gaps

What React must provide that Streamlit gave for free, or that Streamlit forced and
React need not keep:

| gap | note |
|---|---|
| Session persistence | `session_store.py` works around Streamlit's statelessness. `supabase-js` handles it. Delete, do not port. |
| Auth screens | Call Supabase directly via `supabase-js`, mirroring `session.py`. No backend change. |
| Agent progress | Port the five-stage polling; the endpoint is unchanged. |
| Refresh after mutation | Streamlit re-runs the whole script. React needs explicit cache invalidation after every mutation — done/skip, approve, upload, confirm. |
| `cached_get` identity | Streamlit caches keyed on the acting identity **including the act-as target**. A React query cache must do the same, or an admin viewing as a user sees their own data. |
| Admin as one page | 830 lines of tabs becomes routed sections, not one component. |
| Navigation | §11 defines a 4-item bottom nav and a collapsible desktop sidebar. Streamlit currently lists 5 pages including a separate "Add plant" entry, which §11 removes. Frontend-only. |
| RTL | Currently Streamlit defaults plus `app/ui/styles`. React needs RTL in the CSS architecture per §10. |
| Deep links | Streamlit page URLs are not meaningful; nothing to preserve. §40 satisfied. |

---

## 5 · Backend changes required

Three, all in the gallery, all approved by the user during this audit. Everything
else React needs already exists.

1. **Set an existing image as main.** `PlantUpdateRequest` is `extra: forbid` and
   allows only `name` and `notes`; `main_image_id` is deliberately excluded so no
   client can PATCH it. Needs a dedicated endpoint. No schema change —
   `plants.main_image_id` exists, and deleting the main image already promotes the
   next (`plant_images.py:205-209`).
2. **Gallery ordering.** `plant_images` has no ordering column. Needs a migration
   plus a reorder endpoint.
3. **Protect the last gallery image.** Not enforced: `delete_image` sets
   `main_image_id = None` when nothing remains, so an ACTIVE plant can end with zero
   images. Needs the rule in the delete path.

### Spec claims that do not match the code

Recorded so they are not later mistaken for regressions:

- **Plant limit** (§31) does not exist in any form — no global limit, no per-user
  override, no warning — yet the spec says "a Warning according to the existing
  behavior". **Out of scope by decision.**
- **Google login** (§6) does not exist; only password, register and reset.
  **Out of scope by decision.**
- **Failed plants "cannot be restored"** (§17) contradicts the code, which restores
  them to `PENDING_IDENTIFICATION` deliberately (`status_after_restore`,
  `app/domain/rules/plant_lifecycle.py:89`), and contradicts §30 in the same
  document. **Code wins by decision.**
- **A "configured limit" on gallery size** (§20) — no such setting exists.
- **Header notifications** (§11) has no feed endpoint, only preferences and the
  email delivery log. **Decision: the bell shows today's care tasks.**

### Unresolved, and not a code question

**There is no deployment target once Streamlit is removed.** The application runs
today only because FastAPI is embedded in the Streamlit process. A React SPA plus
FastAPI is two services. Deferred by decision; phases 1–7 are unaffected, but §51's
"PWA works and is installable" cannot be proven until a host exists.

---

## 6 · Decisions taken during this audit

1. **Hosting** — deferred; build and verify locally.
2. **Gallery** — all three backend changes in scope, under the §5 exception.
3. **Plant limit** — out of scope.
4. **Restore** — existing backend behaviour wins.
5. **Google login** — out of scope.
6. **Header notification bell** — today's care tasks, from existing endpoints.

---

## 7 · Verified facts worth keeping to hand

- Identification statuses are exactly `SUCCESS` / `NEEDS_MORE_INFORMATION` /
  `FAILED`, matching the spec.
- Plant statuses: `PENDING_IDENTIFICATION`, `IDENTIFIED`, `KNOWLEDGE_PENDING`,
  `ACTIVE`, `ARCHIVED`.
- Database image constraints: mime in `image/jpeg`, `image/png`, `image/webp`; size
  at most 10 MB. This matches §20, noting that JPG and JPEG are one mime type.
- Rate limits on AI-triggering endpoints: 10/hour, 3/minute.
- Tick interval 900s. Agent timeouts: identification 90s, knowledge 600s, care 180s,
  health 180s.
- 29 tables, with `_select_admin` RLS policies on every user-owned table.
