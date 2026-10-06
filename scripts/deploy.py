r"""Deploy to Cloud Run, taking the application's settings from `.env`.

`.env` is the source of truth. Before this script, `cloudbuild.yaml` carried its
own copy of the settings in a `gcloud run deploy --set-env-vars` line, and
`--set-env-vars` replaces the whole set — so the deployment's configuration lived
in two places that could disagree without saying so.

They did. `KNOWLEDGE_MODEL` was changed to `gemini-3.6-flash` in the Cloud Run
console while `cloudbuild.yaml` still said `gemini-3.5-flash-lite`; the next deploy
would have reverted it silently. One source of truth, reconciled on every deploy,
is the fix.

    uv run python scripts/deploy.py              # report what would be deployed
    uv run python scripts/deploy.py --deploy     # build, push and deploy

Reporting by default, like `scrub_dev_database.py` and `purge_dev_test_accounts.py`.
Read that report: `.env` is what ships now, so an experiment left in it reaches the
service on the next deploy. That is the point of the arrangement, and also its one
sharp edge.

Three kinds of setting are deliberately NOT copied from `.env`:

* **Secrets.** They go to Secret Manager and are referenced by name. A value passed
  through `--set-env-vars` is visible in `gcloud run services describe` and in the
  console, and `SUPABASE_SERVICE_ROLE_KEY` bypasses RLS.
* **Three production overrides**, where the local value is wrong rather than merely
  different — see `OVERRIDES`.
* **Container facts.** `SPA_DIST_DIR` is set by the Dockerfile and `PORT` by Cloud
  Run. Neither should come from a developer's machine.

Everything else is an allowlist rather than a denylist: a new secret added to
`.env` must not reach the service's plain configuration because somebody forgot to
exclude it.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]

PROJECT = "plantcare-ai-174016"
REGION = "europe-west3"
SERVICE = "plantcare-ai"
REPO = "plantcare"
IMAGE = f"{REGION}-docker.pkg.dev/{PROJECT}/{REPO}/{SERVICE}"

#: Settings copied from `.env` to the service, by name. Everything in
#: `app/config/settings.py` that is neither a secret nor a container fact.
ALLOWLIST = (
    "DEFAULT_TIMEZONE",
    "DEFAULT_CONTENT_LANGUAGE",
    "SUPABASE_STORAGE_BUCKET",
    "IDENTIFICATION_PROVIDER",
    "KNOWLEDGE_PROVIDER",
    "CARE_PROVIDER",
    "HEALTH_PROVIDER",
    "IDENTIFICATION_MODEL",
    "KNOWLEDGE_MODEL",
    "CARE_MODEL",
    "HEALTH_MODEL",
    "AI_REQUEST_TIMEOUT_SECONDS",
    "IDENTIFICATION_TIMEOUT_SECONDS",
    "KNOWLEDGE_TIMEOUT_SECONDS",
    "CARE_TIMEOUT_SECONDS",
    "HEALTH_TIMEOUT_SECONDS",
    "AI_MAX_STRUCTURED_RETRIES",
    "RESEND_FROM_EMAIL",
    # Web Push: the public half of the key pair goes to every browser anyway, and
    # the subject is a contact address. The private half is in SECRETS.
    "VAPID_PUBLIC_KEY",
    "VAPID_SUBJECT",
    "AI_RATE_LIMIT_PER_HOUR",
    "AI_RATE_LIMIT_PER_MINUTE",
)

#: Where the local value is wrong for production rather than merely different.
OVERRIDES = {
    # Disables /docs (app/api/main.py). `.env` says development.
    "APP_ENV": "production",
    "APP_DEBUG": "false",
    # Cloud Scheduler drives the sweep. An in-process timer as well would be a
    # second driver for no benefit, and on a scale-to-zero host an unreliable one.
    "INTERNAL_TICK_INTERVAL_SECONDS": "0",
}

#: `.env` name -> Secret Manager secret name. Referenced, never inlined.
SECRETS = {
    "SUPABASE_URL": "supabase-url",
    "SUPABASE_ANON_KEY": "supabase-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "supabase-service-role-key",
    "INTERNAL_TICK_SECRET": "internal-tick-secret",
    "GOOGLE_API_KEY": "google-api-key",
    # Neither is used while every agent is set to google, and each is skipped
    # entirely when its value is absent from .env. Listed so switching a provider
    # is one edit there, not a deploy that fails at runtime on a key that was
    # never shipped.
    "ANTHROPIC_API_KEY": "anthropic-api-key",
    "OPENAI_API_KEY": "openai-api-key",
    "RESEND_API_KEY": "resend-api-key",
    "VAPID_PRIVATE_KEY": "vapid-private-key",
}

#: Not tuning. Each prevents a specific failure; see docs/DEPLOY_CLOUD_RUN.md.
SERVICE_FLAGS = (
    "--allow-unauthenticated",
    # Agent work runs after its 202 response, and request-based CPU allocation
    # would throttle it to near zero exactly when it starts.
    "--no-cpu-throttling",
    # The AI rate limiter counts in process memory; N instances permit N times the limit.
    "--max-instances=1",
    "--min-instances=0",
    "--cpu=1",
    "--memory=1Gi",
    # `/v1/internal/tick` runs the sweep inside the request; 6m11s was measured.
    "--timeout=900",
)


def gcloud_path() -> str:
    found = shutil.which("gcloud")
    if found is None:
        sys.exit(
            "gcloud is not on PATH. Install the Google Cloud SDK, or open a new\n"
            "terminal if it was installed after this one started."
        )
    return found


def run(gcloud: str, args: list[str], *, stdin: bytes | None = None) -> tuple[int, str]:
    """Run gcloud in binary mode, decoding only on the way out.

    Binary deliberately: secret values go in over stdin as bytes, and passing
    `errors=` or `encoding=` to `subprocess.run` quietly switches the whole call to
    text mode — which makes `stdout` a `str` and `input` reject bytes.
    """
    result = subprocess.run([gcloud, *args], input=stdin, capture_output=True)
    out = (result.stdout or b"").decode("utf-8", errors="replace")
    err = (result.stderr or b"").decode("utf-8", errors="replace")
    return result.returncode, out + err


def env_pairs(env: dict[str, str | None]) -> dict[str, str]:
    """The settings the service will carry, resolved."""
    pairs = {}
    for name in ALLOWLIST:
        value = (env.get(name) or "").strip()
        # An empty optional stays absent rather than being set to "". Several
        # settings treat None and "" differently - `email_enabled` is the one that
        # matters, since RESEND_FROM_EMAIL="" would not enable email but would look
        # configured.
        if value:
            pairs[name] = value
    pairs.update(OVERRIDES)
    return pairs


def flag_value(pairs: dict[str, str]) -> str:
    """Render for `--set-env-vars`, escaping if any value contains its separator."""
    body = ",".join(f"{k}={v}" for k, v in pairs.items())
    if any("," in v for v in pairs.values()):
        # gcloud's documented custom-delimiter form.
        return "^@^" + "@".join(f"{k}={v}" for k, v in pairs.items())
    return body


def runtime_service_account(gcloud: str) -> str:
    """The identity a revision runs as, which is what has to read the secrets.

    Derived rather than written down: the address is built from the project
    *number*, not its id, and a wrong constant would only fail at deploy time.
    """
    code, out = run(gcloud, ["projects", "describe", PROJECT, "--format=value(projectNumber)"])
    if code != 0:
        sys.exit(f"could not read the project number: {out[:300]}")
    return f"{out.strip()}-compute@developer.gserviceaccount.com"


def grant_access(gcloud: str, secret: str, account: str) -> None:
    """Let the revision read a secret this script has just created.

    Storing a secret and granting access to it are two operations, and skipping
    the second is invisible until the deploy: Cloud Run refuses the revision with
    `Permission denied on secret ...` *after* the image has been built and pushed,
    so the failure costs a full build. That is how `resend-api-key` and
    `vapid-private-key` failed on the notifications deploy; the five secrets that
    predate it had been granted by hand and so hid the gap.

    Only for secrets created here. An existing secret keeps whatever policy it
    has, because widening access to something already in use is not this script's
    decision to make.
    """
    code, out = run(
        gcloud,
        [
            "secrets",
            "add-iam-policy-binding",
            secret,
            f"--member=serviceAccount:{account}",
            "--role=roles/secretmanager.secretAccessor",
            f"--project={PROJECT}",
        ],
    )
    if code != 0:
        sys.exit(f"could not grant the service account access to {secret}: {out[:300]}")


def sync_secrets(gcloud: str, env: dict[str, str | None], *, apply: bool) -> list[str]:
    """Push any secret whose `.env` value differs from the stored one.

    Compares rather than always adding a version, so a deploy that changes nothing
    does not leave a trail of identical secret versions. Values are never printed.
    """
    present = []
    # Looked up once, and only if something actually has to be created.
    account: str | None = None
    for name, secret in SECRETS.items():
        value = (env.get(name) or "").strip()
        if not value:
            print(f"  {secret:28} absent from .env - not referenced")
            continue
        present.append(name)

        code, stored = run(
            gcloud,
            [
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={secret}",
                f"--project={PROJECT}",
            ],
        )
        if code != 0:
            print(f"  {secret:28} MISSING in Secret Manager - will be created and granted")
            if apply:
                run(
                    gcloud,
                    [
                        "secrets",
                        "create",
                        secret,
                        "--replication-policy=automatic",
                        f"--project={PROJECT}",
                    ],
                )
                run(
                    gcloud,
                    ["secrets", "versions", "add", secret, "--data-file=-", f"--project={PROJECT}"],
                    stdin=value.encode("utf-8"),
                )
                if account is None:
                    account = runtime_service_account(gcloud)
                grant_access(gcloud, secret, account)
            continue

        if stored.strip() == value:
            print(f"  {secret:28} unchanged")
            continue

        print(f"  {secret:28} CHANGED in .env - a new version will be added")
        if apply:
            add, out = run(
                gcloud,
                ["secrets", "versions", "add", secret, "--data-file=-", f"--project={PROJECT}"],
                stdin=value.encode("utf-8"),
            )
            if add != 0:
                sys.exit(f"could not update {secret}: {out[:300]}")
    return present


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT)
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy to Cloud Run from .env.")
    parser.add_argument("--deploy", action="store_true", help="actually deploy; default reports")
    args = parser.parse_args()

    env = dotenv_values(ROOT / ".env")
    if not env:
        sys.exit("No .env found. Copy .env.example and fill it in (see SETUP §5).")

    gcloud = gcloud_path()
    pairs = env_pairs(env)

    tag = git("rev-parse", "--short", "HEAD") or datetime.now(UTC).strftime("%Y%m%d%H%M")
    dirty = git("status", "--porcelain")

    print(f"\nproject {PROJECT} · region {REGION} · service {SERVICE}")
    print(f"image   {IMAGE}:{tag}\n")

    supabase = (env.get("SUPABASE_URL") or "").strip()
    print(f"Supabase project this will talk to:\n  {supabase}\n")

    print("Settings from .env:")
    for key, value in sorted(pairs.items()):
        mark = "  (override)" if key in OVERRIDES else ""
        print(f"  {key:34} {value}{mark}")

    print("\nSecrets (referenced by name, values never shown):")
    present = sync_secrets(gcloud, env, apply=args.deploy)

    if dirty:
        print(
            "\n!! Uncommitted changes in the working tree. `gcloud builds submit`\n"
            "   uploads the working tree, not the commit, so those WILL be deployed."
        )

    if not args.deploy:
        print("\nReport only. Re-run with --deploy to build and deploy.")
        return 0

    anon = (env.get("SUPABASE_ANON_KEY") or "").strip()
    if not supabase or not anon:
        sys.exit("SUPABASE_URL and SUPABASE_ANON_KEY are required; they are baked into the bundle.")

    print("\nBuilding…")
    code, out = run(
        gcloud,
        [
            "builds",
            "submit",
            "--config=cloudbuild.yaml",
            f"--project={PROJECT}",
            f"--region={REGION}",
            f"--substitutions=_SUPABASE_URL={supabase},_SUPABASE_ANON_KEY={anon},SHORT_SHA={tag}",
            ".",
        ],
    )
    print(out.replace(anon, "<anon key>")[-2500:])
    if code != 0:
        return code

    print("Deploying…")
    code, out = run(
        gcloud,
        [
            "run",
            "deploy",
            SERVICE,
            f"--image={IMAGE}:{tag}",
            f"--region={REGION}",
            f"--project={PROJECT}",
            "--platform=managed",
            *SERVICE_FLAGS,
            f"--set-env-vars={flag_value(pairs)}",
            "--set-secrets=" + ",".join(f"{n}={SECRETS[n]}:latest" for n in present),
        ],
    )
    print(out[-2000:])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
