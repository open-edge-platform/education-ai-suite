#!/usr/bin/env bash
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Verifies that the GStreamer/DL Streamer elements the VA pipelines depend on
# are registered inside the current environment (run this *inside* the
# intel/dlstreamer container, not on the host).

set -euo pipefail

REQUIRED_ELEMENTS=(
  gvadetect
  gvaclassify
  gvapython
  gvawatermark
  gvametaconvert
  gvametapublish
  gvafpscounter
  decodebin3
  vah264enc
  vah264dec
  vah265enc
  vah265dec
  vapostproc
)

missing=0
for element in "${REQUIRED_ELEMENTS[@]}"; do
  if gst-inspect-1.0 "$element" >/dev/null 2>&1; then
    echo "OK   $element"
  else
    echo "MISS $element"
    missing=1
  fi
done

if (( missing )); then
  echo "One or more required GStreamer elements are missing (see MISS lines above)." >&2
  echo "vah264enc/dec, vah265enc/dec, vapostproc need --device /dev/dri AND --group-add <render GID>." >&2
fi

exit "$missing"
