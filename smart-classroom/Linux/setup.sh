#!/usr/bin/env bash
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Smart Classroom Linux setup entry point (task 0.A.3 / 0.B.2).
# Replaces setup-smart-classroom.ps1. For now it provisions the Node.js toolchain
# the UI build needs; venv bootstrap / pip install / config prompts are layered on
# in 0.A.3.
#
# Usage:
#   ./setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\033[1;32m[setup]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[setup]\033[0m %s\n' "$*" >&2; exit 1; }


if git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "Initializing git submodules (edge-ai-libraries, performance-tools)…"
  git -C "$SCRIPT_DIR" submodule update --init --recursive edge-ai-libraries
  git -C "$SCRIPT_DIR" submodule update --init performance-tools
else
  log "Not a git checkout — skipping submodule init."
fi

log "Checking Node.js toolchain for the UI build…"
NODE_SETUP="${SCRIPT_DIR}/scripts/node-setup.sh"
[[ -f "$NODE_SETUP" ]] || die "Missing ${NODE_SETUP}"
bash "$NODE_SETUP"

ENV_FILE="${SCRIPT_DIR}/.env"
ENV_EXAMPLE="${SCRIPT_DIR}/.env.example"
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$ENV_EXAMPLE" ]]; then
    log "Creating .env from .env.example…"
    cp -n "$ENV_EXAMPLE" "$ENV_FILE"
  else
    log "⚠️  Missing ${ENV_EXAMPLE} — skipping .env bootstrap; create .env manually."
  fi
else
  log ".env already exists — leaving it untouched."
fi


CONFIG_YAML="${SCRIPT_DIR}/config.yaml"
if [[ -f "$CONFIG_YAML" ]] && command -v python3 >/dev/null 2>&1; then
  DIARIZATION_ENABLED="$(python3 - "$CONFIG_YAML" <<'PY'
import sys, yaml
try:
    with open(sys.argv[1]) as f:
        cfg = yaml.safe_load(f) or {}
    print(bool(((cfg.get("models") or {}).get("asr") or {}).get("diarization")))
except Exception:
    print("False")
PY
)"
  HF_TOKEN_SET="false"
  if [[ -f "$ENV_FILE" ]] && grep -qE '^HF_TOKEN=.+' "$ENV_FILE"; then
    HF_TOKEN_SET="true"
  fi
  if [[ "$DIARIZATION_ENABLED" == "True" && "$HF_TOKEN_SET" == "false" ]]; then
    log "⚠️  models.asr.diarization is enabled in config.yaml but HF_TOKEN is not set in .env."
    log "    Diarization (pyannote) and some gated text-gen models require a Hugging Face"
    log "    token with access granted to the relevant model repo(s). Set HF_TOKEN=<token>"
    log "    in ${ENV_FILE} before running 'docker compose up', or diarization/model"
    log "    downloads will fail with a 401 at startup."
  fi
else
  log "⚠️  Could not check config.yaml for diarization — if you use speaker diarization or"
  log "    gated text-gen models, set HF_TOKEN in .env manually."
fi

# --- Keep startup-models.yaml/.gpu.yaml in sync with config.yaml ------------
# model-downloader exports whatever model names are in
# components/vlm/config/startup-models(.gpu).yaml — these are hand-authored
# and NOT auto-generated, so changing models.text_gen.vlm_name / embedding /
# content_search reranker in config.yaml does not automatically update them.
# Auto-apply the sync (not just warn) so a bare `./setup.sh` always launches
# the models config.yaml actually asks for.
if command -v python3 >/dev/null 2>&1; then
  log "Syncing startup-models.yaml/.gpu.yaml model names from config.yaml…"
  (cd "$SCRIPT_DIR" && python3 -m utils.sync_startup_models --write) \
    || log "⚠️  Could not sync startup-models.yaml — check it manually against config.yaml."
else
  log "⚠️  python3 not found — skipping startup-models.yaml sync; check it manually against config.yaml."
fi

if command -v python3 >/dev/null 2>&1; then
  log "Deriving COMPOSE_PROFILES from config.yaml features:…"
  (cd "$SCRIPT_DIR" && python3 -m utils.compose_profiles --write-env) \
    || log "⚠️  Could not derive COMPOSE_PROFILES automatically — set it manually in .env before 'docker compose up'."
else
  log "⚠️  python3 not found — skipping COMPOSE_PROFILES derivation; set it manually in .env before 'docker compose up'."
fi

# --- GPU detection (optional docker-compose.gpu.yml overlay) ----------------
COMPOSE_FILES=(-f docker/docker-compose.yml)
if [[ -d /dev/dri ]]; then
  log "Intel GPU render node (/dev/dri) detected — enabling docker/docker-compose.gpu.yml overlay."
  COMPOSE_FILES+=(-f docker/docker-compose.gpu.yml)
  if ! grep -qE '^RENDER_GID=.+' "$ENV_FILE" 2>/dev/null; then
    RENDER_GID="$(getent group render | cut -d: -f3 || true)"
    if [[ -n "$RENDER_GID" ]]; then
      if grep -qE '^RENDER_GID=' "$ENV_FILE" 2>/dev/null; then
        sed -i "s/^RENDER_GID=.*/RENDER_GID=${RENDER_GID}/" "$ENV_FILE"
      else
        printf 'RENDER_GID=%s\n' "$RENDER_GID" >> "$ENV_FILE"
      fi
      log "Set RENDER_GID=${RENDER_GID} in .env."
    else
      log "⚠️  No 'render' group found — set RENDER_GID in .env manually before 'docker compose up'."
    fi
  fi
else
  log "No /dev/dri found — running CPU-only (docker/docker-compose.gpu.yml not applied)."
fi

# --- Sanity-check the compose config before building anything --------------
log "Validating docker compose config (docker compose config --services)…"
(cd "$SCRIPT_DIR" && docker compose --project-directory "$SCRIPT_DIR" --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" config --services >/dev/null) \
  || die "docker compose config failed — check COMPOSE_PROFILES/.env and the compose files above before retrying."

# --- Build + start the stack -------------------------------------------------
log "Building and starting the stack (docker compose up -d --build)…"
(cd "$SCRIPT_DIR" && docker compose --project-directory "$SCRIPT_DIR" --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" up -d --build) \
  || die "docker compose up failed — check the build/service logs above."

# --- Wait for the app to become healthy -------------------------------------
# First run can be slow: model-downloader pulls + exports VLM/embedding/rerank
# models before `ovms` (and in turn `app`'s SERVING_BASE_URL) is usable, and
# its own healthcheck start_period is 1800s (30 min). Give the overall wait
# here enough headroom to cover that, polling `app`'s container health status
# (cheaper/more reliable than curling the endpoint ourselves pre-healthy).
HEALTH_TIMEOUT_S="${HEALTH_TIMEOUT_S:-1900}"
HEALTH_POLL_INTERVAL_S=10
log "Waiting for the app container to become healthy (timeout ${HEALTH_TIMEOUT_S}s — first run can be slow while models download)…"
elapsed=0
app_status=""
while (( elapsed < HEALTH_TIMEOUT_S )); do
  app_status="$(docker inspect -f '{{.State.Health.Status}}' smart-classroom-app 2>/dev/null || echo "unknown")"
  if [[ "$app_status" == "healthy" ]]; then
    break
  fi
  sleep "$HEALTH_POLL_INTERVAL_S"
  elapsed=$(( elapsed + HEALTH_POLL_INTERVAL_S ))
done

if [[ "$app_status" == "healthy" ]]; then
  ACTIVE_PROFILES="$(grep -E '^COMPOSE_PROFILES=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)"
  log "✅ App is healthy: http://localhost:8000/"
  log "   Active profiles: ${ACTIVE_PROFILES:-none}"
else
  log "⚠️  App did not become healthy within ${HEALTH_TIMEOUT_S}s (last status: ${app_status})."
  log "    First-run model downloads can take a long time — it may still finish; re-check with:"
  log "      docker compose -f docker/docker-compose.yml ps"
  log "    Inspect logs with:"
  log "      docker compose -f docker/docker-compose.yml logs -f app"
  log "      docker compose -f docker/docker-compose.yml logs -f model-downloader ovms"
fi

log "Optional local UI startup (Vite dev server):"
log "  cd \"$SCRIPT_DIR/ui\""
log "  npm install"
log "  npm run dev -- --host 0.0.0.0 --port 5173"
log "Expected Vite banner:"
printf '  \033[1;36mVITE v8.1.4\033[0m  ready in 95 ms\n'
printf '  \033[1;36m➜  Local:\033[0m   http://localhost:5173/\n'
printf '  \033[1;36m➜  Network:\033[0m http://10.223.23.54:5173/\n'
printf '  \033[1;36m➜  Network:\033[0m http://172.18.0.1:5173/\n'

log "✅ setup complete."
