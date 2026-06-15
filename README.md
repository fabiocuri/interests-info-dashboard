# Interests Info Dashboard

A small, local, Dockerized web app that periodically asks Claude three
personal-interest questions and shows the answers on a single dashboard page.

The three tasks, answered separately each run:

1. **AI Engineer tip** — something to know to be top talent in the field (≤2 paragraphs).
2. **Most spoken-about topic in the world right now** — uses Claude's **web search**
   tool so it reflects current events rather than stale training data (≤2 paragraphs).
3. **Lebanese Arabic conversation** — a short dialogue (≤10 lines) in the Arabic
   alphabet, rendered right-to-left in the UI.

## How it works

- **Backend:** FastAPI + APScheduler. A refresh runs **on startup** (if there's no
  data yet) and then **every 6 hours** (configurable via `REFRESH_HOURS`).
- **LLM:** Anthropic Python SDK, model `claude-opus-4-8`. Task 2 enables the
  server-side `web_search` tool.
- **Anti-repeat:** the last few answers per task are fed back to Claude so tips and
  Arabic scenarios stay fresh (configurable via `HISTORY_FEEDBACK`).
- **Storage:** a JSON file (`runs.json`) on a Docker named volume — survives restarts.
- **Frontend:** one HTML page showing the latest run plus collapsible history,
  auto-refreshing in the browser every 5 minutes. A **Refresh now** button triggers
  an on-demand run.

## Run it on Kubernetes (minikube)

Deploys into the `demo` namespace so Headlamp and Goldilocks pick it up. The
namespace must carry the `goldilocks.fairwinds.com/enabled=true` label (already
set in this cluster) and the Deployment declares resource requests/limits so
Goldilocks/VPA can recommend right-sizing.

```bash
cp .env.example .env            # set ANTHROPIC_API_KEY

# 1. Build the image straight into minikube (no registry needed)
minikube image build -t interests-info-dashboard:latest .

# 2. Create the Secret from .env (kept out of git; quotes stripped)
KEY=$(python -c "from dotenv import dotenv_values; print(dotenv_values('.env')['ANTHROPIC_API_KEY'])")
minikube kubectl -- -n demo create secret generic interests-info-dashboard \
  --from-literal=ANTHROPIC_API_KEY="$KEY" \
  --dry-run=client -o yaml | minikube kubectl -- apply -f -

# 3. Apply the manifests
minikube kubectl -- apply -k k8s/

# 4. View it
minikube kubectl -- -n demo port-forward svc/interests-info-dashboard 8000:8000
# then open http://localhost:8000
```

Goldilocks auto-creates a `goldilocks-interests-info-dashboard` VPA for the
Deployment; view recommendations in the Goldilocks dashboard or in Headlamp.

The manifests live in `k8s/` (PVC, Deployment, Service, kustomization). The
Secret is created out-of-band on purpose — `k8s/secret.example.yaml` documents
its shape but never holds a real key.

## Run it with Docker (alternative, no cluster)

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY
docker compose up --build
```

Then open http://localhost:8000

The first run kicks off on startup; the page says so and auto-refreshes once the
answers land (a run takes ~30s, mostly the web-search task).

## Configuration

All optional, set in `.env` (defaults shown):

| Var | Default | Meaning |
|-----|---------|---------|
| `ANTHROPIC_API_KEY` | — | **Required.** Your Anthropic API key. |
| `MODEL` | `claude-opus-4-8` | Model used for every task. |
| `REFRESH_HOURS` | `6` | Hours between automatic refreshes. |
| `MAX_RUNS` | `50` | Runs kept on disk / shown in history. |
| `HISTORY_FEEDBACK` | `3` | Recent answers per task fed back for anti-repeat. |
| `PAGE_REFRESH_SECONDS` | `300` | Browser auto-refresh interval. |

## Endpoints

- `GET /` — the dashboard.
- `GET /api/runs` — full run history as JSON.
- `POST /api/refresh` — trigger a refresh now (returns immediately).
- `GET /healthz` — health check.

## Local development (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload
```
