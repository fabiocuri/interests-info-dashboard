# Interests Info Dashboard — Conversation Handoff

State of the project so it can be resumed later. Open Claude Code in this repo and say:
*"Read CONVERSATION_HANDOFF.md and let's continue."*

Last updated: 2026-06-16.

---

## What this is

A small local web app that asks Claude three personal-interest questions, **once per
computer start**, and shows the answers on a **black-and-white newspaper-style** dashboard
that opens automatically in the browser. Deployed to **minikube** (namespace `demo`) so it
shows up in the user's **Headlamp** and **Goldilocks** demos.

## The three tasks (in `app/claude_client.py` → `TASKS`)

1. **AI Engineer — technical deep-dive** (`ai_engineer_tip`): pick any topic from the AI
   engineering / DevOps / software dev world; structured as **Title / Introduction /
   Problem Statement / Tools Out There / Example Scenario**, ≤10 paragraphs. `max_tokens=2000`.
2. **Most talked-about event yesterday** (`world_topic`): ≤2 paragraphs, uses the
   **web_search** tool, anchored to *yesterday's actual date* (injected at runtime).
3. **Short conversation in Lebanese Arabic** (`lebanese_arabic`): ≤10 lines, Arabic
   alphabet, rendered right-to-left in the UI.

## Decisions locked in

- **Run cadence:** once per computer start only. **No scheduler** — a run happens solely
  via `POST /api/refresh`, which the login script triggers once.
- **Model:** `claude-haiku-4-5` (cheapest). Cost controls: `MAX_OUTPUT_TOKENS=600`
  (task 1 overrides to 2000), `WEB_SEARCH_MAX_USES=2`, `HISTORY_FEEDBACK=1` (anti-repeat).
- **Auth:** direct `ANTHROPIC_API_KEY` via a k8s Secret (see below).
- **UI:** monochrome newsprint (`--paper #f7f5ef`, `--ink #16140f`), Playfair Display
  (masthead/headlines), Amiri (Arabic), Georgia (body). Loaded from Google Fonts in the
  browser with Georgia/system fallback.

## Architecture / layout

- `app/main.py` — FastAPI; routes `/`, `/api/runs`, `/api/refresh`, `/healthz`; the
  `article` Jinja filter that bolds the deep-dive sub-heads (HTML-escaped, safe).
- `app/claude_client.py` — the three tasks, web-search tool, anti-repeat, yesterday-date
  injection, per-task `max_tokens`.
- `app/storage.py` — JSON run history on a PVC (`runs.json`), newest-first, capped at `MAX_RUNS`.
- `app/config.py` — env-driven settings.
- `templates/index.html` — the newspaper UI; refresh button polls until done then reloads.
- `k8s/` — `deployment.yaml` (requests right-sized to Goldilocks rec **35m / 100Mi**, limits
  150m/256Mi), `service.yaml`, `pvc.yaml`, `kustomization.yaml`, `secret.example.yaml`
  (placeholder only — never holds the real key).
- `scripts/boot-launch.sh` + `scripts/interests-info-dashboard.desktop` — login autostart.
- `Dockerfile`, `docker-compose.yml` — image build + non-k8s alternative.

## How it's deployed (minikube, namespace `demo`)

- Image built into minikube: `minikube image build -t interests-info-dashboard:latest .`
- Deployment/Service/PVC applied via `minikube kubectl -- apply -k k8s/`.
- Secret created out-of-band from `.env` (value never written to a file or printed):
  ```bash
  KEY=$(python -c "from dotenv import dotenv_values; print(dotenv_values('.env')['ANTHROPIC_API_KEY'])")
  minikube kubectl -- -n demo create secret generic interests-info-dashboard \
    --from-literal=ANTHROPIC_API_KEY="$KEY" --dry-run=client -o yaml | minikube kubectl -- apply -f -
  ```
- After changing `.env` or rebuilding the image: re-create the Secret (if key changed) and
  `minikube kubectl -- -n demo rollout restart deploy/interests-info-dashboard` (env vars are
  read at pod start).
- Goldilocks auto-creates `goldilocks-interests-info-dashboard` VPA in `demo`.

## How to run / view

- **Autostart:** `~/.config/autostart/interests-info-dashboard.desktop` runs
  `scripts/boot-launch.sh` at login → starts minikube if needed → port-forward → one run →
  opens `http://localhost:8000`. Log: `~/.local/state/interests-info-dashboard-boot.log`.
- **Manual:** `bash scripts/boot-launch.sh`, or
  `minikube kubectl -- -n demo port-forward svc/interests-info-dashboard 8000:8000` then open
  `http://localhost:8000` and click **"Print a fresh edition."**

## How content updates (no scheduler)

A "run" = call Claude for all three tasks and append a new timestamped edition to
`runs.json`. The page always shows the newest edition; older ones go to "From the archives".
There is **no timer** — content changes only when something calls `POST /api/refresh`:

1. **Login autostart** (`boot-launch.sh`) — once per desktop login (≈ per computer start).
2. **"Print a fresh edition"** button — manual; polls until done, then reloads.
3. **Direct `POST /api/refresh`** — by hand / curl.

Does **not** trigger a run (so no API spend): reloading the page, pod restarts / rollouts /
minikube restart (the on-startup run was deliberately removed), sleep/wake, or idle time.

Caveat: "once per computer start" is really **once per desktop login**. Multiple logins =
multiple editions. Optional unbuilt follow-up: a date-stamp guard for "at most once per day".

## Environment quirks (important)

- **The snap `kubectl` on this machine produces no output.** Always use
  `minikube kubectl -- ...` instead.
- Cluster ops in the agent need the Bash sandbox disabled (`dangerouslyDisableSandbox`).
- `minikube image build` then `rollout restart` to deploy code changes (tag stays `:latest`,
  `imagePullPolicy: IfNotPresent`).

## Secrets / safety

- `.env` is gitignored and is the only file holding the real key. `.env.example` is a
  placeholder. The Secret is piped via stdin, never saved to disk.
- The API key appeared in plaintext earlier in chat and was rotated by the user. **Still
  worth rotating again** if there's any doubt.

## Commit history (branch `main`, remote `origin`)

- `5885440` newspaper redesign
- `6267cc0` prompt rework (structured deep-dive + yesterday's event)
- `bc6f11b` once-per-boot on Haiku for minimal cost
- `3e20669` FastAPI app + k8s deployment
- `c27c929` initial commit

## Open / optional follow-ups (not done)

- Offered, pending user choice: **stark pure-white** palette instead of warm newsprint;
  **self-hosting the fonts** in the image for full offline support.
- Possible: throttle autostart to "first run of the day only" (currently runs per login).
- User preference recorded: **do not** add `Co-Authored-By: Claude` trailers to commits.
