import logging, os, subprocess
from typing import Tuple
import sys
from utils.config_loader import config
from utils.cli_utils import run_cli
logger = logging.getLogger(__name__)

def _ir_exists(output_dir: str) -> bool:
    """Check if exported OpenVINO IR files exist."""
    xml_file = os.path.join(output_dir, "openvino_model.xml")
    bin_file = os.path.join(output_dir, "openvino_model.bin")
    return os.path.exists(xml_file) and os.path.exists(bin_file)

def _download_openvino_model(
    model_name: str,
    output_dir: str,
    weight_format: str,
    force: bool = False
) -> Tuple[bool, str]:
    """Export a HuggingFace model to OpenVINO IR using optimum-cli."""
    os.makedirs(output_dir, exist_ok=True)

    if not force and _ir_exists(output_dir):
        logger.info(f"⚡ Using cached export at {output_dir}")
        return True, output_dir

    cmd = [
        "optimum-cli", "export", "openvino",
        "--model", model_name,
        "--weight-format", weight_format,
        "--trust-remote-code",
        output_dir,
    ]

    logger.info(f"🚀  Exporting {model_name} → {output_dir} ({weight_format})\n"
                "⏳  Exporting model... This process may take some time depending on the model size. \n"
                "⚠️  Please do not terminate the process.")

    return_code = run_cli(cmd=cmd, log_fn=logger.info)
    if return_code != 0:
        logger.error(f"❌ Export failed: {return_code}")
        return False, output_dir

    success = _ir_exists(output_dir)
    logger.info("✅ Export successful" if success else "❌ Export incomplete")
    return success, output_dir

def ensure_model() -> str:
    output_dir = get_model_path()
    if config.models.summarizer.provider == "openvino":
        _download_openvino_model(config.models.summarizer.name, output_dir, config.models.summarizer.weight_format)
        return output_dir

def get_model_path() -> str:
    return os.path.join(config.models.summarizer.models_base_path, config.models.summarizer.provider, f"{config.models.summarizer.name.replace("/", "_")}_{config.models.summarizer.weight_format}")
