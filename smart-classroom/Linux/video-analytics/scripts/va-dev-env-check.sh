#!/usr/bin/env bash
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
#
# Pulls the pinned intel/dlstreamer base image,
# then verifies inside a container that:
#   - the GStreamer/DL Streamer elements the VA pipelines depend on are present
#   - VA-API (vah264enc/dec, vapostproc, ...) elements actually register
#     (requires /dev/dri + the host's "render" group GID passed in, or they
#     silently register 0 features)
#   - OpenVINO can compile+run a model on NPU and on GPU
#   - the gstgva Python bindings (gvapython's runtime surface) import cleanly
#   - gst-launch-1.0/gst-discoverer-1.0/gst-inspect-1.0 exist with no .exe
#     suffix (they're already on PATH inside the image; nothing to discover)
#
# No application code runs here — this only proves the sandbox every later

set -euo pipefail

VA_DLSTREAMER_IMAGE="${VA_DLSTREAMER_IMAGE:-intel/dlstreamer:2026.2.0-ubuntu24}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKS_DIR="${SCRIPT_DIR}/va-dev-env"
CONTAINER_CHECKS_DIR="/opt/va-dev-env"

log()  { printf '\033[1;34m[va-dev-env]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[va-dev-env]\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker not found on PATH"
[[ -d "$CHECKS_DIR" ]] || die "missing check scripts directory: $CHECKS_DIR"

RENDER_GID="$(getent group render | cut -d: -f3 || true)"
[[ -n "$RENDER_GID" ]] || die "no 'render' group on this host; GPU passthrough needs one"

DEVICE_ARGS=(--device /dev/dri --group-add "$RENDER_GID")
if [[ -e /dev/accel ]]; then
  DEVICE_ARGS+=(--device /dev/accel)
else
  log "WARNING: /dev/accel not present on this host — NPU checks will be skipped"
fi

MOUNT_ARGS=(-v "${CHECKS_DIR}:${CONTAINER_CHECKS_DIR}:ro")

log "Pulling ${VA_DLSTREAMER_IMAGE} ..."
docker pull "$VA_DLSTREAMER_IMAGE"

log "Checking required GStreamer/DL Streamer elements ..."
docker run --rm "${DEVICE_ARGS[@]}" "${MOUNT_ARGS[@]}" "$VA_DLSTREAMER_IMAGE" \
  bash "${CONTAINER_CHECKS_DIR}/check-gst-elements.sh" \
  || die "GStreamer element check failed (see MISS/FAIL lines above)"

log "Checking OpenVINO device enumeration + gstgva Python bindings ..."
docker run --rm "${DEVICE_ARGS[@]}" "${MOUNT_ARGS[@]}" "$VA_DLSTREAMER_IMAGE" \
  python3 "${CONTAINER_CHECKS_DIR}/check-openvino-gva.py" \
  || die "OpenVINO/gstgva check failed (see FAIL lines above)"

log "Checking gst-*-1.0 CLI tools resolve without a .exe suffix ..."
docker run --rm "$VA_DLSTREAMER_IMAGE" which gst-launch-1.0 gst-discoverer-1.0 gst-inspect-1.0 \
  || die "one or more gst-*-1.0 CLI tools not found on PATH"

log "All VA-1 checks passed against ${VA_DLSTREAMER_IMAGE}."
log "Reference docker run invocation for interactive dev work:"
cat <<EOF
  docker run -it --rm \\
    --device /dev/dri --device /dev/accel \\
    --group-add "\$(getent group render | cut -d: -f3)" \\
    ${VA_DLSTREAMER_IMAGE} bash
EOF
