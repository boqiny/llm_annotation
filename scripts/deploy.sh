#!/usr/bin/env bash
# Deploy CALICO on this server. Idempotent — safe to re-run.
#
# Assumes:
#   - Repo is at $PWD (workflow `cd`s here before calling)
#   - Docker + docker compose plugin are installed and the runner user is
#     in the `docker` group (no `sudo` needed for compose)
#   - annotagent/.env exists on the server with API keys (not in git)
#
# Run manually: cd ~/llm_annotation && bash scripts/deploy.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/annotagent"

echo "[deploy] $(date -Is) · commit $(git -C "$ROOT" rev-parse --short HEAD)"

# Bootstrap .env on first run so docker compose doesn't fail on missing vars.
if [ ! -f .env ]; then
  echo "[deploy] no .env found — copying .env.example. Set API keys before next deploy."
  cp .env.example .env
fi

# Build + restart in detached mode. --build forces image rebuild on code changes.
# --remove-orphans cleans up any container that was renamed or dropped from compose.
docker compose up -d --build --remove-orphans

# Free up old image layers so the disk doesn't bloat over many deploys.
docker image prune -f >/dev/null

# Health check — wait up to 30s for backend to come up.
echo -n "[deploy] waiting for backend …"
for i in $(seq 1 30); do
  if curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
    echo " ok"
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo " TIMED OUT"
    docker compose logs --tail 50 backend
    exit 1
  fi
done

echo "[deploy] done · frontend http://$(hostname -I | awk '{print $1}'):8080 · backend :8000"
