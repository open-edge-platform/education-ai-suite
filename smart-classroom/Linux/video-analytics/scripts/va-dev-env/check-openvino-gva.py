#!/usr/bin/env python3
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Verify OpenVINO NPU/GPU compile+inference and the gstgva Python bindings.

Run this *inside* the intel/dlstreamer container, not on the host. Exits
non-zero if a device that OpenVINO enumerates fails to compile/run, or if the
gstgva import (the runtime surface gvapython scripts use) fails.
"""
import sys

import numpy as np
import openvino as ov
from openvino import opset13 as opset

INPUT_SHAPE = (1, 3, 224, 224)


def build_smoke_test_model() -> ov.Model:
    param = ov.op.Parameter(ov.Type.f32, ov.Shape(list(INPUT_SHAPE)))
    return ov.Model([opset.relu(param)], [param], name="va_dev_env_smoke_test")


def check_openvino_devices() -> bool:
    core = ov.Core()
    available = core.available_devices
    print("Available OpenVINO devices:", available)

    model = build_smoke_test_model()
    ok = True
    for device in ("GPU", "NPU"):
        if device not in available:
            print(f"SKIP {device}: not enumerated by OpenVINO Core on this host")
            continue
        try:
            compiled = core.compile_model(model, device_name=device)
            request = compiled.create_infer_request()
            inputs = {0: np.random.rand(*INPUT_SHAPE).astype(np.float32)}
            outputs = request.infer(inputs)
            assert list(outputs.values())[0].shape == INPUT_SHAPE
            print(f"OK   {device} compile+infer")
        except Exception as exc:  # noqa: BLE001 - report and continue to other devices
            print(f"FAIL {device} compile+infer: {exc}", file=sys.stderr)
            ok = False
    return ok


def check_gstgva_bindings() -> bool:
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        from gstgva import VideoFrame  # noqa: F401 - import surface used by gvapython scripts
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL gstgva Python bindings import: {exc}", file=sys.stderr)
        return False
    print("OK   gstgva Python bindings import")
    return True


def main() -> int:
    ok = check_openvino_devices()
    ok = check_gstgva_bindings() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
