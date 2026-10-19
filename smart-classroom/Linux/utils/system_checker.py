from utils.platform_info import get_platform_and_model_info
from utils.gstreamer_env import GST_SUBPROCESS_TIMEOUT, ensure_gst_registry
import os
import sys
import re
import glob
import subprocess
import shutil
import logging

logger = logging.getLogger(__name__)

MIN_MEMORY_GB = 32
MIN_MODEL_CACHE_GB = 20
REQUIRED_OS = "Linux"
REQUIRED_PYTHON_MAJOR = 3
REQUIRED_PYTHON_MINOR = 12
REQUIRED_NODE_MAJOR = 18  # Minimum required Node.js version
MIN_DLSTREAMER_VERSION = (2026, 1, 0)
OS_RELEASE_PATH = "/etc/os-release"
INTEL_PCI_VENDOR_ID = "0x8086"


def _run_text(cmd) -> str:
    """Run a probe command and return stdout, or '' on any failure."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=GST_SUBPROCESS_TIMEOUT,
        )
        return result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def check_meteor_lake(processor_name: str) -> bool:
    try:
        if not processor_name:
            return False
        match = re.search(r"\b(\d{3})[A-Z]?\b", str(processor_name))
        return bool(match and match.group(1).startswith("1"))
    except Exception:
        return False


def parse_memory_gb(memory_str: str) -> float:
    try:
        if not memory_str:
            return 0
        match = re.search(r"(\d+)", str(memory_str))
        return float(match.group(1)) if match else 0
    except Exception:
        return 0


def check_python_version() -> bool:
    try:
        major = sys.version_info.major
        minor = sys.version_info.minor
        return major == REQUIRED_PYTHON_MAJOR and minor == REQUIRED_PYTHON_MINOR
    except Exception:
        return False


def check_os() -> bool:
    """Confirm the host is running Linux.

    Reads `/etc/os-release` for a human-friendly distro label (logging only);
    the pass/fail decision is based on the Python platform tag so it works on
    any distribution.
    """
    try:
        if not sys.platform.startswith("linux"):
            logger.error(f"❌ Unsupported OS '{sys.platform}'. This build targets {REQUIRED_OS}.")
            return False

        pretty = ""
        try:
            with open(OS_RELEASE_PATH, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if line.startswith("PRETTY_NAME="):
                        pretty = line.split("=", 1)[1].strip().strip('"')
                        break
        except OSError:
            pass

        logger.info(f"✅ Operating system: {pretty or 'Linux'}")
        return True
    except Exception as e:
        logger.error(f"⚠️ OS check failed: {e}")
        return False


def check_intel_gpu() -> bool:
    """Confirm an Intel GPU is available for summarization acceleration.

    Probes, in order of preference:
      1. `vainfo`  — confirms a working VA-API driver (iHD/i965) on an Intel GPU.
      2. `clinfo`  — confirms an Intel OpenCL GPU device.
      3. `/sys/class/drm/card*/device/vendor` — confirms an Intel DRM card exists
         even before the VA-API/OpenCL runtimes are installed.
    The sysfs fallback keeps this check meaningful on a fresh host where the
    userspace GPU runtimes have not been provisioned yet.
    """
    try:
        # 1. vainfo — a working VA-API stack is the strongest signal of usability.
        if shutil.which("vainfo"):
            out = _run_text(["vainfo"])
            if re.search(r"\b(iHD|i965)\b", out) or re.search(r"Intel", out):
                logger.info("✅ Intel GPU usable via VA-API (vainfo).")
                return True

        # 2. clinfo — an Intel OpenCL GPU device (used for summarization offload).
        if shutil.which("clinfo"):
            out = _run_text(["clinfo"])
            if "Intel" in out and re.search(r"(Graphics|Arc|UHD|Iris|GPU)", out):
                logger.info("✅ Intel GPU usable via OpenCL (clinfo).")
                return True

        # 3. sysfs — confirm an Intel DRM card is physically present.
        for card in glob.glob("/sys/class/drm/card[0-9]*"):
            vendor_path = os.path.join(card, "device", "vendor")
            try:
                with open(vendor_path, "r", encoding="utf-8", errors="ignore") as fh:
                    if fh.readline().strip().lower() == INTEL_PCI_VENDOR_ID:
                        logger.info("✅ Intel GPU detected via /sys/class/drm.")
                        return True
            except OSError:
                continue

        logger.error("❌ No Intel GPU detected (checked vainfo, clinfo, /sys/class/drm).")
        return False
    except Exception as e:
        logger.error(f"⚠️ Intel GPU check failed: {e}")
        return False


def check_nodejs_version() -> bool:
    """
    Checks if Node.js is installed and meets the minimum version requirement.
    Returns True if Node.js exists and version >= REQUIRED_NODE_MAJOR.
    """
    try:
        node_path = shutil.which("node")
        if node_path is None:
            logger.error("❌ Node.js is not installed or not found in PATH.")
            return False

        version_output = subprocess.check_output(["node", "--version"], text=True).strip()
        logger.info(f"✅ Node.js found: {version_output}")

        # Parse version (e.g., v18.16.0 → 18)
        match = re.match(r"v(\d+)", version_output)
        if not match:
            logger.error("⚠️ Unable to parse Node.js version output.")
            return False

        major_version = int(match.group(1))
        if major_version < REQUIRED_NODE_MAJOR:
            logger.error(f"⚠️ Node.js version {major_version} is too old. Please install Node.js v{REQUIRED_NODE_MAJOR}+.")
            return False

        return True

    except Exception as e:
        logger.error(f"⚠️ Node.js check failed: {e}")
        return False


def check_docker_and_compose() -> bool:
    """Confirm Docker and Compose are available for containerized startup."""
    try:
        docker_path = shutil.which("docker")
        if docker_path is None:
            logger.error("❌ Docker is not installed or not found in PATH.")
            return False

        docker_version = subprocess.run(
            [docker_path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=GST_SUBPROCESS_TIMEOUT,
            check=False,
        )
        if docker_version.stdout:
            logger.info(f"✅ Docker found: {docker_version.stdout.strip()}")

        compose_cmd = None
        docker_compose_version = subprocess.run(
            [docker_path, "compose", "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=GST_SUBPROCESS_TIMEOUT,
            check=False,
        )
        if docker_compose_version.returncode == 0:
            compose_cmd = [docker_path, "compose"]
        elif shutil.which("docker-compose"):
            compose_cmd = ["docker-compose"]

        if compose_cmd is None:
            logger.error("❌ Docker Compose is not installed or not found in PATH.")
            return False

        compose_version = subprocess.run(
            compose_cmd + ["version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=GST_SUBPROCESS_TIMEOUT,
            check=False,
        )
        if compose_version.returncode == 0 and compose_version.stdout:
            logger.info(f"✅ Docker Compose found: {compose_version.stdout.strip()}")
            return True

        logger.error("❌ Docker Compose is not working properly.")
        return False
    except Exception as e:
        logger.error(f"⚠️ Docker/Compose check failed: {e}")
        return False


def _docker_root_dir() -> str | None:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.DockerRootDir}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=GST_SUBPROCESS_TIMEOUT,
            check=False,
        )
        root_dir = (result.stdout or "").strip()
        return root_dir or None
    except (OSError, subprocess.SubprocessError):
        return None


def _model_cache_path() -> str | None:
    try:
        result = subprocess.run(
            ["docker", "volume", "inspect", "--format", "{{.Mountpoint}}", "model-cache"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=GST_SUBPROCESS_TIMEOUT,
            check=False,
        )
        mountpoint = (result.stdout or "").strip()
        if mountpoint and os.path.isdir(mountpoint):
            return mountpoint

        root_dir = _docker_root_dir()
        if root_dir:
            fallback = os.path.join(root_dir, "volumes", "model-cache", "_data")
            if os.path.isdir(fallback):
                return fallback
            return root_dir
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def check_model_cache_disk_space(min_free_gb: int = MIN_MODEL_CACHE_GB) -> bool:
    """Confirm the backing path for the model-cache volume has enough space."""
    try:
        model_cache_path = _model_cache_path()
        if not model_cache_path:
            logger.error("❌ Unable to determine the Docker model-cache volume path.")
            return False

        usage = shutil.disk_usage(model_cache_path)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < min_free_gb:
            logger.error(
                f"❌ Not enough free space for model-cache: {free_gb:.1f} GiB available "
                f"at {model_cache_path}, need at least {min_free_gb} GiB."
            )
            return False

        logger.info(
            f"✅ model-cache backing path {model_cache_path} has {free_gb:.1f} GiB free."
        )
        return True
    except Exception as e:
        logger.error(f"⚠️ model-cache space check failed: {e}")
        return False


def check_dlstreamer_installation() -> bool:
    """
    Checks if DL Streamer is installed by inspecting the gvadetect plugin.
    Returns True if DL Streamer is properly installed.
    """
    try:
        gst_inspect_path = shutil.which("gst-inspect-1.0")
        if gst_inspect_path is None:
            logger.error("❌ gst-inspect-1.0 is not installed or not found in PATH.")
            return False

        # This is usually the first GStreamer process the app spawns, so it is
        # the one that pays for a plugin registry rebuild if the cache is stale.
        ensure_gst_registry()

        result = subprocess.run(
            ["gst-inspect-1.0", "gvadetect"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GST_SUBPROCESS_TIMEOUT
        )

        if result.returncode == 0 and "gvadetect" in result.stdout.lower():
            version_match = re.search(r"Version\s+(\S+)", result.stdout)
            if version_match:
                version = version_match.group(1)
                parts = tuple(int(x) for x in re.findall(r"\d+", version))[:3]
                if parts < MIN_DLSTREAMER_VERSION:
                    min_ver_str = ".".join(str(v) for v in MIN_DLSTREAMER_VERSION)
                    logger.error(f"❌ DL Streamer version {version} is too old. Minimum required: {min_ver_str}.")
                    return False
                logger.info(f"✅ DL Streamer found and working (version {version}).")
                return True
        else:
            logger.error("❌ DL Streamer not found or not working properly.")
            return False
    except Exception as e:
        logger.error(f"⚠️ DL Streamer check failed: {e}")
        return False


def check_system_requirements() -> bool:
    """
    Checks the overall system environment for compatibility.
    Returns True only if all major requirements are satisfied.
    """
    try:
        info = get_platform_and_model_info()
    except Exception:
        return False

    try:
        if not check_os():
            return False
        if not check_meteor_lake(info.get("Processor", "")):
            return False
        if parse_memory_gb(info.get("Memory", "")) < MIN_MEMORY_GB:
            return False
        if not check_intel_gpu():
            return False
        if not check_python_version():
            return False
        if not check_nodejs_version():
            return False
        if not check_docker_and_compose():
            return False
        if not check_model_cache_disk_space():
            return False
        if not check_dlstreamer_installation():
            return False
        return True
    except Exception:
        return False


def show_warning_and_prompt_user_to_continue():
    """
    Ask the user to press ENTER to continue or type 'exit' to quit.
    Returns True if the user wants to continue, False otherwise.
    """

    logger.warning("\n\033[1;31m⚠️  Warning: Your system doesn’t meet the minimum or recommended requirements to run this application. Please check the README for setup instructions to ensure proper execution.\033[0m")
    logger.info("""\n
\033[90m------------------------------------------------------------\033[0m             
\033[1;34m💻 System Requirements\033[0m

- \033[1mOS:\033[0m Linux (Ubuntu 24.04 LTS recommended)
- \033[1mProcessor:\033[0m Intel® Core Ultra Series 1 (with integrated GPU support)
- \033[1mMemory:\033[0m 32 GB RAM (minimum recommended)
- \033[1mStorage:\033[0m At least 50 GB free (for models and logs)
- \033[1mGPU/Accelerator:\033[0m Intel® iGPU (Intel® Core Ultra Series 1, Arc GPU, or higher) for summarization acceleration
- \033[1mPython:\033[0m 3.12
- \033[1mNode.js:\033[0m v18+ (for frontend)
- \033[1mDL Streamer:\033[0m 2026.1.0+ (for video analytics pipelines)

\033[90m------------------------------------------------------------\033[0m
""")

    try:
        user_input = input("⚠️  Press ENTER to continue anyway or type 'exit' to quit: ").strip().lower()
        if user_input == "exit":
            return False
        return True
    except KeyboardInterrupt:
        return False
