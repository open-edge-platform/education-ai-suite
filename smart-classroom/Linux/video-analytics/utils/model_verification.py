"""Compile-time verification for VA's OpenVINO model exports

Confirms an exported/quantized model actually compiles and runs one inference
on each requested device *before* the conversion scripts consider it done —
catching an NPU-unsupported op or a leftover dynamic shape at export time
instead of at pipeline launch time.
"""
from pathlib import Path
from typing import Sequence
import logging

import numpy as np
import openvino as ov

logger = logging.getLogger(__name__)

DEFAULT_VERIFY_DEVICES = ("NPU",)


def verify_openvino_ir(xml_path: Path, devices: Sequence[str] = DEFAULT_VERIFY_DEVICES) -> None:
    """Compile ``xml_path`` on each of ``devices`` and run one dummy inference.

    Devices not enumerated by this host's ``ov.Core`` (e.g. no NPU present)
    are skipped with a warning rather than failing the build. Raises
    RuntimeError if the model has a dynamic input shape, or if compilation/
    inference fails on a device that *is* enumerated (a real NPU-compatibility
    problem, not a missing-hardware one).
    """
    xml_path = Path(xml_path)
    core = ov.Core()
    available = core.available_devices
    model = core.read_model(str(xml_path))

    input_shapes = {}
    for inp in model.inputs:
        shape = inp.get_partial_shape()
        if not shape.is_static:
            raise RuntimeError(
                f"{xml_path.name}: input '{inp.any_name}' has a dynamic shape "
                f"({shape}); NPU requires a static shape before verification"
            )
        input_shapes[inp.any_name] = tuple(int(d) for d in shape.to_shape())

    for device in devices:
        if device not in available:
            logger.warning(
                "SKIP %s verification on %s: device not enumerated on this host",
                xml_path.name, device,
            )
            continue
        try:
            compiled = core.compile_model(model, device_name=device)
            request = compiled.create_infer_request()
            feeds = {
                inp.any_name: np.random.rand(*input_shapes[inp.any_name]).astype(np.float32)
                for inp in model.inputs
            }
            request.infer(feeds)
        except Exception as exc:
            raise RuntimeError(
                f"{xml_path.name} failed to compile/run on {device}: {exc}"
            ) from exc
        logger.info("%s compiles and runs on %s", xml_path.name, device)
