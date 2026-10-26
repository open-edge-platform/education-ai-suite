from components.base_component import PipelineComponent
from utils.runtime_config_loader import RuntimeConfig
from utils.config_loader import config
from utils.prompt_loader import load_prompt
from utils.storage_manager import StorageManager
from utils.session_paths import SessionPaths
import json
import json_repair
import logging, os

logger = logging.getLogger(__name__)

# Levels below the root the grammar allows. The prompt asks for 2-4; the grammar
# is unrolled to this depth rather than recursive, so the bound is exact.
MAX_DEPTH = 4


def _node_schema(depth: int) -> dict:
    """One jsMind node: id and topic, children only above the depth bound."""
    properties = {
        "id": {"type": "string", "minLength": 1},
        "topic": {"type": "string", "minLength": 1},
    }
    if depth < MAX_DEPTH:
        properties["children"] = {"type": "array", "items": _node_schema(depth + 1)}
    return {
        "type": "object",
        "properties": properties,
        "required": ["id", "topic"],
        "additionalProperties": False,
    }


def mindmap_json_schema() -> str:
    """Schema for the jsMind node_tree, passed to the decoder as a grammar.

    The model's free-form JSON is valid almost always, not always: a session
    once lost the opening quote of a topic value and the UI could not render
    the map at all. Constraining decoding rules that out.
    """
    root = _node_schema(0)
    root["properties"]["id"] = {"const": "root"}
    meta = {
        "type": "object",
        "properties": {key: {"type": "string"} for key in ("name", "author", "version")},
        "required": ["name", "author", "version"],
        "additionalProperties": False,
    }
    return json.dumps({
        "type": "object",
        "properties": {
            "meta": meta,
            "format": {"const": "node_tree"},
            "data": root,
        },
        "required": ["meta", "format", "data"],
        "additionalProperties": False,
    })


def _is_node(node) -> bool:
    if not isinstance(node, dict):
        return False
    if not isinstance(node.get("id"), str) or not isinstance(node.get("topic"), str):
        return False
    children = node.get("children", [])
    return isinstance(children, list) and all(_is_node(child) for child in children)


def _is_mindmap(obj) -> bool:
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("meta"), dict)
        and obj.get("format") == "node_tree"
        and _is_node(obj.get("data"))
    )


def parse_mindmap(raw: str) -> dict:
    """The jsMind node_tree in ``raw``, repaired if the JSON is broken.

    Raises ``ValueError`` when no node_tree can be recovered, so a mind map the
    UI cannot render fails the stage instead of being saved as done.
    """
    text = (raw or "").strip()
    try:
        obj = json.loads(text)
    except ValueError:
        obj = None
    if not _is_mindmap(obj):
        repaired = json_repair.loads(text)
        if not _is_mindmap(repaired):
            raise ValueError(f"INVALID_MINDMAP_FORMAT: {text[:200]!r}")
        logger.warning("Mindmap output was not a valid node_tree; saved the repaired JSON.")
        obj = repaired
    return obj


class MindmapComponent(PipelineComponent):
    def __init__(self, session_id, provider, model_name, device, temperature=0.7):
        self.session_id = session_id
        self.provider = provider.lower()
        self.model_name = model_name
        self.device = device
        self.temperature = temperature

    def _get_mindmap_message(self, input_text):
        system_prompt = load_prompt("mindmap", config.app.language, "system_prompt")
        logger.debug("Mindmap system prompt loaded for lang=%s", config.app.language)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{input_text}"}
        ]

    def _generate(self, messages: list) -> str:
        try:
            return self.model.generate(
                messages=messages,
                stream=False,
                enable_thinking=False,
                json_schema=mindmap_json_schema(),
            )
        except TypeError:
            logger.info("Backend does not accept json_schema; generating unconstrained.")
        except Exception as exc:
            logger.warning(
                "Constrained generation failed (%s); retrying unconstrained.", exc
            )
        return self.model.generate(messages=messages, stream=False, enable_thinking=False)

    def generate_mindmap(self, summary_text):
        mindmap_path = str(SessionPaths.mindmap_path(self.session_id))

        try:
            logger.info("Generating mindmap from summary...")
            raw = self._generate(self._get_mindmap_message(summary_text))
            full_mindmap = json.dumps(parse_mindmap(raw), ensure_ascii=False, indent=2)
            StorageManager.save(mindmap_path, full_mindmap, append=False)
            logger.info("Mindmap generation completed successfully.")
            return full_mindmap

        except Exception as e:
            logger.error(f"Mindmap generation failed: {e}")
            raise e
