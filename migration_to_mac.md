# Migration to Mac

Moving this project from the Windows machine to a new Mac. Work through it in order;
step 6 is what tells you it worked.

## 1. Clone — do not copy the folder

- `git clone https://github.com/AssafEzra/plantcare-ai.git`
- `git checkout dev` (the default branch and where work happens)
- **Never copy `.venv` (222 MB) or `frontend/node_modules` (183 MB)** — Windows and
  win32 native binaries, unusable on macOS and the source of confusing failures
- `uv sync`
- `cd frontend && npm install`

Line endings need no attention: `.gitattributes` stores LF and normalises on checkout.

## 2. Carry `.env` by hand — the only file that must travel

- 4 KB, gitignored (`.gitignore:2`), so it is **not** in the clone
- Holds `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_PASSWORD`, `GOOGLE_API_KEY`,
  `RESEND_API_KEY`, `VAPID_PRIVATE_KEY`, `INTERNAL_TICK_SECRET`
- Move it over a secure channel — not email, not chat
- **It must be the current copy.** `deploy.py` pushes any secret whose `.env` value
  differs from the stored one, with no prompt, so a stale `.env` silently overwrites
  production secrets. See step 6.
- `.env` never reaches Cloud Build — `.gcloudignore:36-38` excludes it

## 3. gcloud

- Install the Google Cloud SDK
- `gcloud auth login` → `assiezra@gmail.com`
- `gcloud config set project plantcare-ai-174016`
- Region is `europe-west3`; `deploy.py` passes it, so nothing to configure
- **Then open a brand-new terminal window.** The installer appends to `~/.zshrc`, and
  any shell already running keeps its old `PATH`.

  This is worth taking seriously, because it cost real time on Windows: `gcloud` was
  in the user `PATH` registry entry yet absent from the running process, and
  *restarting Claude Code inside the same terminal did not fix it* — the terminal
  predated the entry too. Only a new terminal picks up a new `PATH`. If `gcloud`
  is not found, that is the first thing to check, not the install.

## 4. Other tooling

- `uv`, and Python ≥ 3.12 (`pyproject.toml` `requires-python`)
- Node + npm (no version pin in `frontend/package.json`)
- `gh auth login` — the GitHub token lives in the Windows keyring and does not travel
- Chrome + the Claude in Chrome extension, and re-grant its site permissions

## 5. Claude Code configuration (none of it is in the repo)

- Copy `~/.claude/CLAUDE.md` and `~/.claude/settings.json`
- Re-add the **Stitch API key** to `~/.claude.json` — user scope only, never a
  tracked `.mcp.json`, never a `VITE_` variable
- Copy the 11 files from
  `~/.claude/projects/C--Users-AE-Desktop-PlantCare-AI/memory/`
  **into the new path's folder.** That directory is named after the project's
  absolute path, so on the Mac it becomes something like
  `-Users-<you>-…-PlantCare-AI`. Put them under the old name and Claude Code will
  look in the new one, find nothing, and carry on without them — silently.

## 6. Verify before trusting the machine

- `./scripts/check.sh` → format, lint, mypy, tests, frontend all green
- `uv run python scripts/deploy.py` — **report only; no `--deploy`**
- In that report, **every secret line must read `unchanged`**. A `CHANGED in .env`
  line means your `.env` drifted from production — resolve it before deploying.
- Compare the printed settings block against the live service:
  `gcloud run services describe plantcare-ai --region=europe-west3`

## Working from both machines

- Git syncs the code. Nothing else syncs — not `.env`, not Claude Code memories
  (they are per-path), not uncommitted work.
- `git pull` before any deploy. Uncommitted changes get a `-dirty` version suffix,
  but a tree that is merely *behind* deploys silently as an older commit.
- Report-only first, every time.
- Simplest of all: pick one deploy machine.

## Branch model

- `dev` — GitHub default; branch all work from here
- `main` — release only, ever fast-forwarded from `dev`; deploy from here
  (`git checkout main && git merge --ff-only dev && git push`)
- `main` is protected but `enforce_admins` is false, so your own fast-forward pushes
  go through. Do not promote via a pull request: `linear history` is required, so
  GitHub would only offer squash or rebase, and either rewrites the SHAs and makes
  `main` diverge from `dev` permanently.
