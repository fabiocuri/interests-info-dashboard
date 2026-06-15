# Interests Info Dashboard

A small, local web app (deployed to minikube) that asks Claude three
personal-interest questions **once per computer start** and shows the answers on
a single dashboard page that opens automatically in your browser.

The three tasks, answered separately each run:

1. **AI Engineer tip** — something to know to be top talent in the field (≤2 paragraphs).
2. **Most spoken-about topic in the world right now** — uses Claude's **web search**
   tool so it reflects current events rather than stale training data (≤2 paragraphs).
3. **Lebanese Arabic conversation** — a short dialogue (≤10 lines) in the Arabic
   alphabet, rendered right-to-left in the UI.

## How it works

- **Backend:** FastAPI. **No background scheduler** — a run happens only when
  `POST /api/refresh` is called. The login script triggers exactly one run per
  computer start, so API spend is one batch of calls per boot and nothing while idle.
- **LLM:** Anthropic Python SDK, model `claude-haiku-4-5` (cheapest tier). Cost is
  kept minimal by: capping output at `MAX_OUTPUT_TOKENS` (600), limiting the
  web-search task to `WEB_SEARCH_MAX_USES` (2) searches, and feeding back only
  `HISTORY_FEEDBACK` (1) prior answer for anti-repeat.
- **Storage:** a JSON file (`runs.json`) on a PVC — survives restarts.
- **Frontend:** one HTML page showing the latest run plus collapsible history, with
  a **Refresh now** button. It does not auto-refresh (data only changes on boot).

## Run once per computer start (autostart)

`scripts/boot-launch.sh` is wired to run at login via
`~/.config/autostart/interests-info-dashboard.desktop`. On each login it:

1. starts minikube if it isn't already running,
2. waits for the Deployment, port-forwards the Service to `localhost:8000`,
3. triggers **one** `POST /api/refresh`, and
4. opens `http://localhost:8000` in your browser.

Install/refresh the autostart entry:

```bash
chmod +x scripts/boot-launch.sh
cp scripts/interests-info-dashboard.desktop ~/.config/autostart/
```

Logs land in `~/.local/state/interests-info-dashboard-boot.log`. To run it by hand:
`bash scripts/boot-launch.sh`.

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

Then open http://localhost:8000 and click **Refresh now** to populate it (there's
no scheduler, so nothing runs until you trigger it).

## Configuration

All optional, set in `.env` (defaults shown):

| Var | Default | Meaning |
|-----|---------|---------|
| `ANTHROPIC_API_KEY` | — | **Required.** Your Anthropic API key. |
| `MODEL` | `claude-haiku-4-5` | Model used for every task. |
| `MAX_OUTPUT_TOKENS` | `600` | Hard cap on output tokens per task. |
| `WEB_SEARCH_MAX_USES` | `2` | Max web searches for the world-topic task. |
| `MAX_RUNS` | `50` | Runs kept on disk / shown in history. |
| `HISTORY_FEEDBACK` | `1` | Recent answers per task fed back for anti-repeat. |

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
