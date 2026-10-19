#!/usr/bin/env bash
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Node.js provisioning for the Smart Classroom UI (task 0.B.2).
# Replaces the Windows `winget install OpenJS.NodeJS.LTS` step: checks whether a
# Node.js that satisfies ui/package.json "engines" (^20.19.0 || >=22.12.0) is
# already present and, if not, installs one via NodeSource (apt/dnf) or nvm.
#
# Idempotent: a satisfying Node is detected and left untouched; only a missing or
# too-old Node triggers an install. Verifies node + npm afterwards.
#
# Usage:
#   scripts/node-setup.sh                 # check, install if needed, verify
#   NODE_MAJOR=20 scripts/node-setup.sh   # target the 20.x line instead of 22.x
#   NODE_FORCE=1  scripts/node-setup.sh   # (re)install even if a satisfying Node exists
set -euo pipefail

# Default install target when we have to install. 22 is the current LTS and
# satisfies the ">=22.12.0" arm of the engines range.
NODE_MAJOR="${NODE_MAJOR:-22}"
NODE_FORCE="${NODE_FORCE:-0}"

log()  { printf '\033[1;34m[node-setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[node-setup]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[node-setup]\033[0m %s\n' "$*" >&2; exit 1; }

# --- privilege helper --------------------------------------------------------
# NodeSource installs system-wide, so it needs root. Resolve a sudo prefix (empty
# when already root) or fall back to nvm (per-user) when neither is available.
SUDO=""
have_root() {
  if [[ $EUID -eq 0 ]]; then
    SUDO=""
    return 0
  fi
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
    return 0
  fi
  return 1
}

# --- engines check -----------------------------------------------------------
# ui/package.json: "node": "^20.19.0 || >=22.12.0"
#   ^20.19.0  →  >=20.19.0 <21.0.0
#   >=22.12.0 →  22.12.0 and newer (22.12+, 23, 24, …); 21.x is NOT allowed.
version_satisfies() {
  local maj="$1" min="$2"
  if (( maj == 20 )) && (( min >= 19 )); then return 0; fi
  if (( maj == 22 )) && (( min >= 12 )); then return 0; fi
  if (( maj > 22 )); then return 0; fi
  return 1
}

current_node_ok() {
  command -v node >/dev/null 2>&1 || return 1
  local v maj min
  v="$(node -v 2>/dev/null)"      # e.g. v22.12.0
  v="${v#v}"                      # 22.12.0
  maj="${v%%.*}"                  # 22
  min="${v#*.}"; min="${min%%.*}" # 12
  [[ "$maj" =~ ^[0-9]+$ && "$min" =~ ^[0-9]+$ ]] || return 1
  version_satisfies "$maj" "$min"
}

# --- install strategies ------------------------------------------------------
install_via_nodesource_apt() {
  log "Installing Node ${NODE_MAJOR}.x via NodeSource (apt)…"
  export DEBIAN_FRONTEND=noninteractive
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | $SUDO -E bash -
  $SUDO apt-get install -y nodejs
}

install_via_nodesource_dnf() {
  log "Installing Node ${NODE_MAJOR}.x via NodeSource (dnf)…"
  curl -fsSL "https://rpm.nodesource.com/setup_${NODE_MAJOR}.x" | $SUDO bash -
  $SUDO dnf install -y nodejs
}

install_via_nvm() {
  log "Installing Node ${NODE_MAJOR}.x via nvm (per-user, no root)…"
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
    log "Bootstrapping nvm into ${NVM_DIR}"
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  fi
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
  nvm install "$NODE_MAJOR"
  nvm alias default "$NODE_MAJOR"
  nvm use default
}

install_node() {
  command -v curl >/dev/null 2>&1 || die "curl is required to install Node.js."
  if command -v apt-get >/dev/null 2>&1 && have_root; then
    install_via_nodesource_apt
  elif command -v dnf >/dev/null 2>&1 && have_root; then
    install_via_nodesource_dnf
  else
    warn "No apt/dnf with root available — falling back to nvm (per-user)."
    install_via_nvm
  fi
}

# --- main --------------------------------------------------------------------
main() {
  if [[ "$NODE_FORCE" != "1" ]] && current_node_ok; then
    log "✅ Found Node $(node -v) (satisfies ^20.19.0 || >=22.12.0) — skipping install."
  else
    if command -v node >/dev/null 2>&1; then
      warn "Node $(node -v) does not satisfy ^20.19.0 || >=22.12.0 — installing ${NODE_MAJOR}.x."
    else
      log "Node.js not found — installing ${NODE_MAJOR}.x."
    fi
    install_node
  fi

  # --- verify ----------------------------------------------------------------
  command -v node >/dev/null 2>&1 || die "Node install failed: 'node' not on PATH (open a new shell if nvm was used)."
  command -v npm  >/dev/null 2>&1 || die "Node install failed: 'npm' not on PATH."
  if ! current_node_ok; then
    die "Installed Node $(node -v) still does not satisfy ^20.19.0 || >=22.12.0."
  fi
  log "✅ Node $(node -v) / npm $(npm -v) installed and verified."
}

main "$@"
