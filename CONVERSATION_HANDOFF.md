# Personal Dashboard — Conversation Handoff

State of the project so it can be resumed later. Open Claude Code in this repo and say:
*"Read CONVERSATION_HANDOFF.md and let's continue."*

Last updated: 2026-06-16.

---

## What this is

A local **personal dashboard** (professional / personal / cultural) deployed to
**minikube** (namespace `demo`, for the user's Headlamp + Goldilocks demos). Clean
light-card UI. Mixes **free** live panels with **Claude-powered** panels, and keeps
API cost visible. It opens automatically in the browser at login.

## Panels

**Claude-powered (paid):**
1. **AI / DevOps tool deep-dive** (`ai_engineer_tip`) — one concrete, named tool/protocol
   (IaC, observability, GPUs, networking, security, MCP…), structured *Title / Introduction
   / Problem Statement / Tools Out There / Example Scenario*, ≤10 paragraphs, `max_tokens=2000`.
2. **Most talked-about event yesterday** (`world_topic`) — web_search tool, flowing prose
   ≤2 paragraphs, anchored to yesterday's date (injected at runtime).
3. **Lebanese Arabic conversation** (`lebanese_arabic`) — ≤10 lines, RTL, Noto Sans Arabic.
4. **Globe explorer** (`country_brief`) — interactive globe.gl; click a country → Claude fact
   + music pick. Cached per country in `countries.json` (re-click is free).

**Free (no Claude):**
5. **Gmail inbox** — read-only IMAP (`imaplib`), opened `readonly=True`.
6. **Today's agenda** — Google Calendar secret iCal feed (`icalendar` + `recurring-ical-events`).
7. **API spend meter** — estimates cost from recorded token usage (`spend.json`), with a
   per-section breakdown. Local estimate only; does NOT match the Anthropic billing console.

## Refresh model (no scheduler)

- **Sync** (inbox/agenda) — free; also auto-refresh (inbox 90s, agenda 5min).
- **Globe click** — one Claude call, then cached.
- **Per-section ↻ Refresh** — `POST /api/refresh/{task_key}`; one call; amends the latest edition.
- **Refresh all** — `POST /api/refresh`; three calls; new edition. The login script calls this once.

## Architecture / layout

- `app/main.py` — FastAPI; routes `/`, `/api/runs`, `/api/refresh`, `/api/refresh/{task}`,
  `/api/inbox`, `/api/agenda`, `/api/country`, `/healthz`. Per-task `_tasks_state`; the
  `article` Jinja filter (paragraph grouping + bold sub-heads, RTL line breaks); `_TASK_LABELS`.
- `app/claude_client.py` — TASKS, `run_task` (returns `(text, usage)`), `run_single_task`,
  `run_all_tasks`, `country_brief`, usage accumulation.
- `app/email_client.py` — IMAP inbox fetch (never raises; errors as data).
- `app/calendar_client.py` — ICS fetch + recurrence expansion (never raises).
- `app/storage.py` — `runs.json` (editions), `update_answer` (per-section amend),
  `record_spend` / `spend_summary` (with `by_task` breakdown), `get_country` / `set_country`.
- `app/config.py` — env-driven settings (Anthropic, Gmail, Calendar, pricing).
- `templates/index.html` — light-card UI; stat strip; agenda + inbox + content + spend + globe
  cards; per-card refresh; client-side fetch for inbox/agenda/globe; globe.gl + topojson via CDN.
- `k8s/` — `deployment.yaml` (requests 35m/100Mi, limits 150m/256Mi), `service.yaml`, `pvc.yaml`,
  `kustomization.yaml`, `secret.example.yaml` (placeholders only).
- `scripts/boot-launch.sh` + `.desktop` — login autostart.

## Deploy (minikube, namespace `demo`)

```bash
minikube image build -t interests-info-dashboard:latest .
# Secret from .env (all keys, quotes stripped, never written to disk):
python3 -c '
import json
from dotenv import dotenv_values
v = dotenv_values(".env")
keys = ["ANTHROPIC_API_KEY","GMAIL_ADDRESS","GMAIL_APP_PASSWORD","CALENDAR_ICS_URL"]
print(json.dumps({"apiVersion":"v1","kind":"Secret",
  "metadata":{"name":"interests-info-dashboard","namespace":"demo"},
  "type":"Opaque","stringData":{k:v[k] for k in keys if v.get(k)}}))
' | minikube kubectl -- apply -f -
minikube kubectl -- apply -k k8s/
minikube kubectl -- -n demo rollout restart deploy/interests-info-dashboard
minikube kubectl -- -n demo port-forward svc/interests-info-dashboard 8000:8000
```

`envFrom: secretRef` injects all keys; env is read at pod start, so re-create the Secret
(if a value changed) and `rollout restart` after edits.

## Environment quirks (important)

- **The snap `kubectl` produces no output** — always use `minikube kubectl -- …`.
- Cluster/minikube/docker commands in the agent need the Bash sandbox disabled.
- Port-forward to `svc/` dies when the pod is replaced (rollout) — restart it after each
  rollout. Avoid `pkill` matching the agent's own background forwards (causes exit 144).
- `minikube image build` then `rollout restart` to ship code (tag stays `:latest`,
  `imagePullPolicy: IfNotPresent`).

## Secrets / safety

- `.env` (gitignored) is the only file with real values. `.env.example` /
  `secret.example.yaml` are placeholders. Secret piped via stdin, never to disk.
- Sensitive: `ANTHROPIC_API_KEY`, `GMAIL_APP_PASSWORD`, `CALENDAR_ICS_URL` (the iCal URL
  grants read access to the calendar).

## Open / optional follow-ups (not done)

- Other panel ideas offered: GitHub panel, cluster-health panel, weather, tasks/TODO,
  Arabic spaced-repetition, "on this day", dark mode, PWA/mobile, work-vs-home boards.
- Throttle autostart to "first run of the day only" (currently per login).
- Self-host fonts + globe assets for full offline support (currently CDN).
- User preference: **do not** add `Co-Authored-By: Claude` trailers to commits.
