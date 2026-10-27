#!/usr/bin/env bash
# One-time setup before `docker compose up -d --build`:
#   - creates .env from .env.example and fills in RENDER_GID
#   - warns if the default MediaMTX host port is already taken
#   - exports models into models/va/ (host venv, skipped if already populated)
#
# NPU-compile verification (utils/model_verification.py) only has real teeth
# inside a dlstreamer-based container -- a bare host venv has no NPU driver
# stack, so ov.Core().available_devices won't include NPU and that check is
# skipped (not failed). The real verification happens when the service
# container actually launches a pipeline on NPU.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

log()  { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[setup]\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker not found on PATH"
docker compose version >/dev/null 2>&1 || die "docker compose plugin not found"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"

# ---- .env ----
if [[ ! -f .env ]]; then
  log "Creating .env from .env.example"
  cp .env.example .env
fi

RENDER_GID="$(getent group render | cut -d: -f3 || true)"
if [[ -n "$RENDER_GID" ]]; then
  if grep -q '^RENDER_GID=' .env; then
    sed -i "s/^RENDER_GID=.*/RENDER_GID=${RENDER_GID}/" .env
  else
    echo "RENDER_GID=${RENDER_GID}" >> .env
  fi
  log "RENDER_GID=${RENDER_GID}"
else
  log "WARNING: no 'render' group on this host; GPU/NPU passthrough may not work"
fi

if (ss -tln 2>/dev/null || true) | grep -q ':8554 '; then
  log "WARNING: host port 8554 is already in use by another process/container."
  log "         Set VA_MEDIAMTX_RTSP_PORT in .env to a free port before continuing."
fi

# ---- model export (dev-time only) ----
# Both conversion scripts are internally idempotent -- convert_yolo_models
# checks each model's own .xml/.bin before (re)exporting it, and
# convert_classification_models checks all of its required files before
# redoing its group. So just always invoke both rather than gating on a
# top-level "is models/va/ non-empty" check -- that heuristic previously
# skipped the whole step as soon as ANY file existed (e.g. just the
# classification models), silently leaving the pose models missing.
log "Exporting models into models/va/ (host venv at .venv-models; skips any model whose output files already exist)"
python3 -m venv .venv-models
.venv-models/bin/pip install --upgrade pip -q
.venv-models/bin/pip install -r requirements-models.txt -q
# On a corporate-proxy network with TLS interception, certifi's public CA
# bundle doesn't trust the proxy's cert even though the OS trust store does
# -- point `requests` AND stdlib `urllib`/`ssl` (used by different download
# helpers in these two scripts) at the system bundle.
if [[ -f /etc/ssl/certs/ca-certificates.crt ]]; then
  export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
  export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
fi
# Run as modules (not `python utils/x.py`) so `from utils.model_verification
# import ...` resolves -- a direct script run puts utils/ itself on
# sys.path[0] instead of the repo root, and the import fails.
.venv-models/bin/python -m utils.convert_yolo_models
.venv-models/bin/python -m utils.convert_classification_models

log "Setup complete. Next: docker compose up -d --build"
