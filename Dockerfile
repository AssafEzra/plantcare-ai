# PlantCare AI as a single container, for Hugging Face Spaces (Docker SDK).
#
# DEPLOYMENT §2 draws the UI and the API as two services with private networking
# between them. Free hosting offers one service and no private network, so both
# processes run here in one container and talk over loopback instead. Recorded as
# a deviation in DEPLOYMENT_AND_OPERATIONS, per FINAL §37.
#
# Only Streamlit is published. FastAPI listens on 127.0.0.1 and cannot be reached
# from outside the container - which is the property the two-service design was
# buying in the first place, obtained here for free.

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Spaces runs the container as an unprivileged UID 1000. Creating that user here
# rather than inheriting root means the virtualenv and Streamlit's cache belong to
# the account that actually runs the process.
RUN useradd --create-home --uid 1000 user
USER user

ENV HOME=/home/user \
    PATH=/home/user/plantcare/.venv/bin:$PATH

WORKDIR /home/user/plantcare

# Dependencies before source, so editing a page does not reinstall Streamlit.
COPY --chown=user pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=user app ./app
COPY --chown=user prompts ./prompts
COPY --chown=user .streamlit ./.streamlit
COPY --chown=user scripts/start.sh ./scripts/start.sh

# `prompts/` sits beside `app/` deliberately: app/infrastructure/ai/prompts.py
# resolves PROMPTS_ROOT as `parents[3] / "prompts"`, so the container has to
# reproduce the repository's layout. This second sync installs the project itself
# in editable mode, which keeps `__file__` pointing at this tree rather than at a
# copy under site-packages - if it did not, every prompt lookup would fail.
RUN uv sync --frozen --no-dev

# The whole point of the single container: the UI's API calls become loopback,
# with no TLS handshake and no public API surface.
ENV API_BASE_URL=http://127.0.0.1:8000 \
    PORT=7860

EXPOSE 7860

CMD ["bash", "scripts/start.sh"]
