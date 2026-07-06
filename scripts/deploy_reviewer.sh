#!/usr/bin/env bash
# Deploy the reviewer demo stack (frontend :8000) on this server. Idempotent.
# Runs alongside the frozen :8080 stack — separate compose project
# (calico-reviewer), separate data volume, separate checkout.
#
# Run manually: cd ~/calico-demo && bash scripts/deploy_reviewer.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/annotagent"

echo "[reviewer-deploy] $(date -Is) · commit $(git -C "$ROOT" rev-parse --short HEAD)"

# Bootstrap .env on first run so docker compose doesn't fail on missing vars.
if [ ! -f .env ]; then
  echo "[reviewer-deploy] no .env found — copying .env.example. Set API keys before next deploy."
  cp .env.example .env
fi

docker compose -p calico-reviewer -f docker-compose.reviewer.yml up -d --build --remove-orphans
docker image prune -f >/dev/null

echo -n "[reviewer-deploy] waiting for backend …"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8002/api/health >/dev/null 2>&1; then
    echo " ok"
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo " TIMED OUT"
    docker compose -p calico-reviewer -f docker-compose.reviewer.yml logs --tail 50 backend
    exit 1
  fi
done

echo "[reviewer-deploy] done · reviewer frontend http://$(hostname -I | awk '{print $1}'):8000"
