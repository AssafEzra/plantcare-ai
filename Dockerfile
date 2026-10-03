# PlantCare AI as a single container, for Google Cloud Run.
#
# DEPLOYMENT §2 draws the UI and the API as two services with private networking
# between them. This is the collapsed form of that, and it collapses along a
# different seam than the Streamlit deployment did: there, the API ran inside the
# UI's process and the two spoke over loopback. Here the UI is a directory of
# static files with no process of its own, and the only thing shared is an origin.
#
# Sharing the origin is what the frontend was built for, not a concession to the
# host: `VITE_API_BASE_URL` is empty, so the browser asks for a relative `/v1`;
# there is no CORS middleware anywhere in `app/`; and the service worker's
# navigation denylist is the same `/v1` prefix every router is mounted under.
#
# Recorded as a deviation in DEPLOYMENT_AND_OPERATIONS §3, per FINAL §37.

# --- the interface -----------------------------------------------------------
#
# `npm run build` is `tsc -b && vite build`, so a type error or an unused local
# fails the image rather than shipping. The three VITE_ values are *baked in* -
# Vite replaces `import.meta.env.VITE_*` at build time, so they cannot be supplied
# as Cloud Run environment variables and one image is one environment. The anon
# key is public by design (see frontend/.env.example); the service-role key must
# never appear here.
FROM node:22-slim AS web

WORKDIR /build

# Manifest before source, so editing a component does not reinstall React.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
# Empty on purpose: same-origin, relative `/v1`. Declared so a build cannot
# inherit a stray value from the environment.
ARG VITE_API_BASE_URL=""
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# --- the application ---------------------------------------------------------

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# An unprivileged UID 1000. Creating that user here rather than inheriting root
# means the virtualenv and the application tree belong to the account that
# actually runs the process.
RUN useradd --create-home --uid 1000 user
USER user

ENV HOME=/home/user \
    PATH=/home/user/plantcare/.venv/bin:$PATH

WORKDIR /home/user/plantcare

# Dependencies before source, so editing a module does not reinstall FastAPI.
COPY --chown=user pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=user app ./app
COPY --chown=user prompts ./prompts
COPY --chown=user scripts/start.sh ./scripts/start.sh

# `prompts/` sits beside `app/` deliberately: app/infrastructure/ai/prompts.py
# resolves PROMPTS_ROOT as `parents[3] / "prompts"`, so the container has to
# reproduce the repository's layout. This second sync installs the project itself
# in editable mode, which keeps `__file__` pointing at this tree rather than at a
# copy under site-packages - if it did not, every prompt lookup would fail.
RUN uv sync --frozen --no-dev

# The built interface, served by the API from this path. `app/api/spa.py` refuses
# to start if there is no index.html in it, which turns a broken frontend build
# into a startup failure rather than a 404 on every page.
COPY --from=web --chown=user /build/dist ./static
ENV SPA_DIST_DIR=/home/user/plantcare/static

# Cloud Run injects PORT and routes to it; 8080 is its default and the fallback
# `start.sh` uses when nothing sets it.
#
# The in-process scheduler is OFF here, which is the opposite of the Streamlit
# deployment's setting and for a concrete reason: Cloud Run scales to zero, and a
# timer in a process that does not exist runs no sweep. Cloud Scheduler calls
# `POST /v1/internal/tick` instead - see docs/DEPLOY_CLOUD_RUN.md.
ENV PORT=8080 \
    INTERNAL_TICK_INTERVAL_SECONDS=0

EXPOSE 8080

CMD ["bash", "scripts/start.sh"]
