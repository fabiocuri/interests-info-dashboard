#!/usr/bin/env bash
# Runs once at login: bring up minikube if needed, ensure the app is reachable,
# trigger ONE refresh, and open the dashboard in the browser.
#
# Cost note: the only Anthropic API spend is the single /api/refresh below —
# once per computer start. The app does nothing on its own while idle.
set -u

NS=demo
SVC=interests-info-dashboard
LOCAL_PORT=8000
URL="http://localhost:${LOCAL_PORT}"
LOG="${HOME}/.local/state/interests-info-dashboard-boot.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== boot-launch $(date -Is) ==="

# The snap kubectl is broken on this box; minikube's bundled one works.
kc() { minikube kubectl -- "$@"; }

# 1. Ensure minikube is running.
if ! minikube status >/dev/null 2>&1; then
  echo "starting minikube..."
  minikube start || { echo "minikube start failed"; exit 1; }
fi

# 2. Wait for the deployment to be available.
echo "waiting for deployment..."
kc -n "$NS" rollout status "deploy/${SVC}" --timeout=180s || { echo "rollout not ready"; exit 1; }

# 3. Start a port-forward if one isn't already serving locally.
if ! curl -sf "${URL}/healthz" >/dev/null 2>&1; then
  echo "starting port-forward..."
  nohup minikube kubectl -- -n "$NS" port-forward "svc/${SVC}" "${LOCAL_PORT}:${LOCAL_PORT}" \
    >>"$LOG" 2>&1 &
  # Wait (up to ~30s) for it to come up.
  for _ in $(seq 1 30); do
    curl -sf "${URL}/healthz" >/dev/null 2>&1 && break
    sleep 1
  done
fi

# 4. Trigger exactly one run.
echo "triggering refresh..."
curl -sf -X POST "${URL}/api/refresh" || echo "refresh trigger failed"

# 5. Open the dashboard.
echo "opening browser..."
xdg-open "$URL" >/dev/null 2>&1 || echo "xdg-open failed (open ${URL} manually)"
echo "=== done $(date -Is) ==="
