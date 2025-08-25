import logging, os, subprocess
from typing import Tuple
import logging
from utils.config_loader import config
logger = logging.getLogger(__name__)

def _ir_exists(output_dir: str) -> bool:
    """Check if exported OpenVINO IR files exist."""
    xml_file = os.path.join(output_dir, "openvino_model.xml")
    bin_file = os.path.join(output_dir, "openvino_model.bin")
    return os.path.exists(xml_file) and os.path.exists(bin_file)

def _download_openvino_model(
    model_name: str,
    output_dir: str,
    weight_format: str = "fp16",
    quant_mode: str = "int8",
    force: bool = False
) -> Tuple[bool, str]:
    """Export a HuggingFace model to OpenVINO IR using optimum-cli."""
    os.makedirs(output_dir, exist_ok=True)

    if not force and _ir_exists(output_dir):
        logging.info(f"⚡ Using cached export at {output_dir}")
        return True, output_dir

    cmd = [
        "optimum-cli", "export", "openvino",
        "--model", model_name,
        "--weight-format", weight_format,
        "--quant-mode", quant_mode,
        output_dir,
    ]

    logging.info(f"🚀 Exporting {model_name} → {output_dir} ({weight_format}, {quant_mode})")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.debug(result.stdout.strip())
        if result.stderr.strip():
            logging.warning(result.stderr.strip())
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Export failed: {e.stderr or e}")
        return False, output_dir

    success = _ir_exists(output_dir)
    logging.info("✅ Export successful" if success else "❌ Export incomplete")
    return success, output_dir

def ensure_model() -> str:
    output_dir = get_model_path()
    if config.models.summarizer.provider == "openvino":
        _download_openvino_model(config.models.summarizer.name, output_dir, config.models.summarizer.weight_format, config.models.summarizer.quant_mode)
        return output_dir

    raise NotImplementedError(f"Provider '{config.models.summarizer.provider}' not supported yet!")

def get_model_path() -> str:
    return os.path.join(config.models.summarizer.models_base_path, config.models.summarizer.provider, f"{config.models.summarizer.name.replace("/", "_")}_{config.models.summarizer.weight_format}_Q{config.models.summarizer.quant_mode}")
