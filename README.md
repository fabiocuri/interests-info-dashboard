# Personal Dashboard

A small, local web app (deployed to minikube) that serves as a personal
dashboard — professional, personal, and cultural — in a clean light-card layout.
It combines a few **free** live panels with a few **Claude-powered** panels, and
keeps API cost visible and under your control.

## Panels

**Claude-powered (cost API credits):**

1. **Engineering — learn a tool** — teaches one concrete, named tool, protocol, or
   concept rotated across networking/firewalls, Linux & security, DevOps/CI-CD, IaC,
   observability, containers/Kubernetes, databases, and web protocols. Two brief
   sections — *Example Scenario* then *Tools Out There* — and every tool comes with a
   clickable link.
2. **Most talked-about event yesterday** — uses Claude's **web search** tool so it
   reflects current events, in flowing prose (≤2 paragraphs).
3. **Lebanese Arabic conversation** — a short dialogue (≤10 lines) in the Arabic
   alphabet, rendered right-to-left in a clean naskh-sans font.
4. **World map explorer** — a clickable 2D world map with an **era dropdown**
   (1940s → Nowadays). Click a country to get an interesting fact and a music
   recommendation from that decade, with a **Spotify player** embedded for the song.
   Fact and music are **independent**: each has its own ↻ refresh, and changing the era
   re-queries only the music. Every pick is **fresh** (anti-repeat), so you keep getting
   something new.

**Free (no Claude calls):**

5. **Gmail inbox** — read-only over IMAP; latest messages, unread/total counts.
6. **Today's agenda** — read-only from a Google Calendar secret iCal feed; expands
   recurring events and groups them into Today / Tomorrow / upcoming in your local time.
7. **API spend meter** — estimates Claude cost (today / 7-day / month / all-time) from
   locally recorded token usage, with a per-section breakdown of what's driving spend,
   and an optional **manual balance** figure (Anthropic has no balance API).

## Refresh model (cost tiers)

There is **no background scheduler**; content changes only when something triggers it:

| Action | Cost | What it does |
|--------|------|--------------|
| **Sync** (inbox / agenda) + auto every 90s/5min | 🆓 free | Re-fetch mail / calendar only |
| Map country click | 💲 one call (fresh each time) | Era-scoped fact + music for that country |
| Per-section **↻ Refresh** | 💲 one call | Regenerate just that panel, amend current edition |
| **Refresh all** | 💲 three calls | Regenerate all content panels as a new edition |
| Login autostart | 💲 three calls | One "Refresh all" per computer start |

## How it works

- **Backend:** FastAPI. The login script triggers one "Refresh all" per computer start;
  otherwise nothing calls Claude unless you click.
- **LLM:** Anthropic Python SDK, model `claude-haiku-4-5` (cheapest tier). Cost is kept
  minimal via `MAX_OUTPUT_TOKENS`, `WEB_SEARCH_MAX_USES`, and `HISTORY_FEEDBACK` (1)
  prior answer for anti-repeat.
- **Storage (on a PVC, survives restarts):** `runs.json` (editions), `spend.json` (token
  usage), `countries.json` (per country+era music history, for anti-repeat).
- **Inbox:** Python stdlib `imaplib`, opened read-only so viewing never marks mail read.
- **Agenda:** `icalendar` + `recurring-ical-events` parse the secret iCal feed.
- **Music:** Spotify Client-Credentials search (field-filtered, artist-verified) turns the
  recommended song into an embeddable track; falls back to a Spotify search link.
- **Frontend:** one light-card HTML page; the world map is an SVG built from the
  `world-atlas` dataset via `topojson-client` (loaded from a CDN).

## Run it on Kubernetes (minikube)

Deploys into the `demo` namespace so Headlamp and Goldilocks pick it up.

```bash
cp .env.example .env            # fill in your values (see Configuration)

# 1. Build the image straight into minikube (no registry needed)
minikube image build -t interests-info-dashboard:latest .

# 2. Create the Secret from .env — all keys, quotes stripped, value never written to disk
python3 -c '
import json
from dotenv import dotenv_values
v = dotenv_values(".env")
keys = ["ANTHROPIC_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "CALENDAR_ICS_URL",
        "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "CLAUDE_API_BALANCE"]
sd = {k: v[k] for k in keys if v.get(k)}
print(json.dumps({"apiVersion": "v1", "kind": "Secret",
  "metadata": {"name": "interests-info-dashboard", "namespace": "demo"},
  "type": "Opaque", "stringData": sd}))
' | minikube kubectl -- apply -f -

# 3. Apply the manifests
minikube kubectl -- apply -k k8s/

# 4. View it
minikube kubectl -- -n demo port-forward svc/interests-info-dashboard 8000:8000
# then open http://localhost:8000
```

After changing `.env` (new key) or rebuilding the image: re-run step 2 if a value
changed, then `minikube kubectl -- -n demo rollout restart deploy/interests-info-dashboard`
(env vars are read at pod start).

Goldilocks auto-creates a `goldilocks-interests-info-dashboard` VPA; view it in the
Goldilocks dashboard or Headlamp. Manifests live in `k8s/` (PVC, Deployment, Service,
kustomization). The Secret is created out-of-band on purpose — `k8s/secret.example.yaml`
documents its shape but never holds real values.

## Run once per computer start (autostart)

`scripts/boot-launch.sh` runs at login via
`~/.config/autostart/interests-info-dashboard.desktop`. On each login it starts minikube
if needed, port-forwards the Service to `localhost:8000`, triggers one **Refresh all**,
and opens the browser. Logs: `~/.local/state/interests-info-dashboard-boot.log`.

```bash
chmod +x scripts/boot-launch.sh
cp scripts/interests-info-dashboard.desktop ~/.config/autostart/
```

## Configuration

Set in `.env` (gitignored). Only `ANTHROPIC_API_KEY` is required; the inbox and agenda
panels stay hidden until their credentials are present.

| Var | Default | Meaning |
|-----|---------|---------|
| `ANTHROPIC_API_KEY` | — | **Required.** Your Anthropic API key. |
| `GMAIL_ADDRESS` | — | Gmail address for the inbox panel. |
| `GMAIL_APP_PASSWORD` | — | Google **app password** (not your login password; needs 2-Step Verification). |
| `CALENDAR_ICS_URL` | — | Google Calendar "secret address in iCal format". |
| `SPOTIFY_CLIENT_ID` | — | Spotify app id (for the embedded player). Blank = a search link instead. |
| `SPOTIFY_CLIENT_SECRET` | — | Spotify app secret. |
| `CLAUDE_API_BALANCE` | — | Manual balance to display (no balance API exists); dashboard subtracts tracked spend. |
| `MODEL` | `claude-haiku-4-5` | Model used for every Claude call. |
| `MAX_OUTPUT_TOKENS` | `600` | Hard cap on output tokens per task (deep-dive overrides to 2000). |
| `WEB_SEARCH_MAX_USES` | `2` | Max web searches for the world-topic task. |
| `MAX_RUNS` | `50` | Editions kept on disk / shown in history. |
| `HISTORY_FEEDBACK` | `1` | Recent answers per task fed back for anti-repeat. |
| `IMAP_HOST` | `imap.gmail.com` | IMAP server for the inbox. |
| `INBOX_FETCH_COUNT` | `8` | Messages shown in the inbox panel. |
| `AGENDA_DAYS` | `7` | Calendar look-ahead window. |
| `AGENDA_MAX` | `15` | Max events shown in the agenda. |
| `CURRENCY_SYMBOL` | `$` | Symbol for the spend meter. |
| `PRICE_INPUT_PER_MTOK` | `1.0` | Est. price per million input tokens. |
| `PRICE_OUTPUT_PER_MTOK` | `5.0` | Est. price per million output tokens. |
| `PRICE_WEB_SEARCH_PER_1K` | `10.0` | Est. price per 1,000 web searches. |

> The spend meter is a **local estimate of calls made through this dashboard since the
> meter was added** — it will not match your Anthropic account's billing history.

## Endpoints

- `GET /` — the dashboard.
- `GET /api/runs` — full edition history as JSON.
- `POST /api/refresh` — regenerate all content panels (new edition).
- `POST /api/refresh/{task_key}` — regenerate one panel (amend current edition).
- `GET /api/inbox` — live Gmail inbox snapshot (free).
- `GET /api/agenda` — upcoming calendar events (free).
- `GET /api/country/fact?name=…` — a fresh interesting fact for a country.
- `GET /api/country/music?name=…[&decade=1960s]` — a fresh era-scoped music pick + Spotify track.
- `GET /healthz` — health check; reports per-task running state.

## Local development (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload
```

## Security / secrets

`.env` is gitignored and is the only file that holds real values. `.env.example` and
`k8s/secret.example.yaml` are placeholders only. The Secret is created by piping JSON via
stdin — values are never written to a file or printed. The Gmail app password and the
calendar iCal URL are both sensitive (the iCal URL grants read access to your calendar);
keep them out of git.
