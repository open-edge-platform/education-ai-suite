"""
Utilities for validating benchmark target device arguments.
"""

import argparse
import os
import re


_GPU_INDEX_PATTERN = re.compile(r"^GPU\.(\d+)$", re.IGNORECASE)


def validate_target_device(value: str) -> str:
    """Validate and normalize target device values.

    Accepted values:
    - CPU
    - GPU
    - GPU.<index> where index is a non-negative integer
    - NPU
    """
    normalized = value.strip()
    upper_value = normalized.upper()

    if upper_value in {"CPU", "GPU", "NPU"}:
        return upper_value

    gpu_match = _GPU_INDEX_PATTERN.fullmatch(normalized)
    if gpu_match:
        return f"GPU.{gpu_match.group(1)}"

    raise argparse.ArgumentTypeError(
        "invalid target device '%s'. Expected one of: CPU, GPU, NPU, GPU.<index>"
        % value
    )


def resolve_target_device_default(default_value: str,
                                  env_var_name: str = "TARGET_DEVICE") -> str:
    """Resolve default target device using env var and validate/normalize it.

    Precedence:
    1) explicit CLI value (handled by argparse separately)
    2) environment variable
    3) hard-coded default
    """
    env_value = os.getenv(env_var_name)
    candidate = env_value if env_value and env_value.strip() else default_value
    return validate_target_device(candidate)
