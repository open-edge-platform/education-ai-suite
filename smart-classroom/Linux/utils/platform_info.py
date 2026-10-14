import os
import re
import glob
import math
import shutil
import subprocess

import psutil
import cpuinfo

from utils.config_loader import config


def _run(cmd):
    """Run a command and return stdout (str), or '' on any failure."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _read_first_line(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.readline().strip()
    except OSError:
        return ""


def _lspci_device_name(line):
    """Extract a clean device name from an `lspci -nnk` line.

    A line looks like:
      00:02.0 VGA compatible controller [0300]: Intel Corporation Arrow Lake-P \
      [Intel Graphics] [8086:7d51] (rev 03)
    We want the text after the class-id bracket (`]: `), with the trailing
    `[vendor:device]` id and `(rev ..)` suffix stripped.
    """
    match = re.search(r"\]:\s*(.*)", line)
    if not match:
        return ""
    name = match.group(1).strip()
    name = re.sub(r"\s*\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\]", "", name)  # drop [8086:7d51]
    name = re.sub(r"\s*\(rev [0-9a-fA-F]+\)", "", name)              # drop (rev 03)
    return name.strip()


def get_intel_igpu():
    """Detect an Intel integrated/discrete GPU on Linux.

    Order of preference:
      1. `clinfo` device name (most descriptive when the OpenCL runtime is present).
      2. `lspci -nnk` VGA/Display/3D controller line for Intel.
      3. `/sys/class/drm` sysfs presence check.
    Falls back to a generic label so the caller always gets a value.
    """
    # 1. clinfo — descriptive marketing name when the Intel OpenCL runtime is installed.
    clinfo_out = _run(["clinfo"])
    if clinfo_out:
        for line in clinfo_out.splitlines():
            if "Device Name" in line and "Intel" in line:
                name = line.split("Device Name", 1)[1].strip()
                # Skip CPU OpenCL devices; keep Graphics/Arc/UHD/Iris entries.
                if any(k in name for k in ("Graphics", "Arc", "UHD", "Iris", "GPU")):
                    return name

    # 2. lspci — parse the display controller line for an Intel entry.
    lspci_out = _run(["lspci", "-nnk"])
    if lspci_out:
        for line in lspci_out.splitlines():
            if re.search(r"(VGA compatible controller|Display controller|3D controller)", line) \
                    and "Intel" in line:
                name = _lspci_device_name(line)
                if name:
                    return name

    # 3. sysfs — confirm an Intel DRM card exists via the i915/xe driver.
    for card in glob.glob("/sys/class/drm/card[0-9]*"):
        vendor = _read_first_line(os.path.join(card, "device", "vendor"))
        if vendor.lower() == "0x8086":  # Intel PCI vendor id
            return "Intel Graphics"

    return "Intel Graphics"


def detect_intel_npu():
    """Detect an Intel NPU (AI Boost / VPU) on Linux.

    Order of preference:
      1. `/sys/class/accel` accelerator device backed by the `intel_vpu` driver.
      2. `lspci -nnk` "Processing accelerators" / neural-network controller line for Intel.
    Falls back to a generic label.
    """
    # 1. sysfs accel class — intel_vpu exposes /sys/class/accel/accel*.
    for accel in glob.glob("/sys/class/accel/accel*"):
        driver = os.path.realpath(os.path.join(accel, "device", "driver"))
        if "vpu" in driver.lower():
            return "Intel AI Boost"
        vendor = _read_first_line(os.path.join(accel, "device", "vendor"))
        if vendor.lower() == "0x8086":
            return "Intel AI Boost"

    # 2. lspci — the NPU appears as a processing-accelerator / neural-network controller.
    lspci_out = _run(["lspci", "-nnk"])
    if lspci_out:
        for line in lspci_out.splitlines():
            if "Intel" in line and re.search(
                r"(Processing accelerators|Neural network controller|AI Boost|NPU)",
                line,
                re.IGNORECASE,
            ):
                name = _lspci_device_name(line)
                if name:
                    return name

    return "Intel AI Boost"


def format_size_gb(size_bytes: int, is_storage: bool = False) -> str:
    gb = size_bytes / (1024 ** 3)
    if is_storage:
        tb = gb / 931 
        return f"{round(tb)} TB" if abs(tb - round(tb)) < 0.05 else f"{tb:.2f} TB"
    else:
        return f"{math.ceil(gb)} GB"


def get_platform_and_model_info():
    # Prefer the metrics-collector sidecar (performance-tools-based) for the
    # hardware summary, so this stays a single source of truth with the
    # /metrics dashboard. Fall back to local detection if the sidecar isn't
    # up (e.g. running main.py outside docker-compose).
    from monitoring.monitor import get_platform_info as get_pt_platform_info
    info = get_pt_platform_info()

    if not info:
        info = {}
        # Processor
        try:
            info['Processor'] = cpuinfo.get_cpu_info()['brand_raw']
        except Exception:
            info['Processor'] = f"Intel Processor"

        # Memory
        try:
            mem = psutil.virtual_memory()
            info['Memory'] = format_size_gb(mem.total)
        except Exception:
            info['Memory'] = "--"

        # storage
        try:
            disk = shutil.disk_usage("/")
            info['Storage'] = format_size_gb(disk.total, is_storage=True)
        except Exception:
            info['Storage'] = '--'

        # GPU/NPU Info
        info['iGPU'] = get_intel_igpu()
        info['NPU'] = detect_intel_npu()

    # Model Info 
    try:
        info['asr_model'] = f"{config.models.asr.provider}/{config.models.asr.name}"
    except Exception:
        info['asr_model'] = "--"

    try:
        text_gen = config.models.text_gen
        if getattr(text_gen, 'provider', None) == 'vlm':
            info['summarizer_model'] = getattr(text_gen, 'vlm_name', '--')
    except Exception:
        info['summarizer_model'] = "--"

    return info



