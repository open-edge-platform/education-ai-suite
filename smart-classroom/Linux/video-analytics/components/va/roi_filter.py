"""ROI filtering logic"""
from typing import Callable, Iterable, List, Optional


def default_label(obj: dict) -> str:
    """Posture label if present (added by PostureDetect), else the raw detection label."""
    for tensor in obj.get("tensors", []):
        if tensor.get("name") == "posture":
            return tensor.get("label", "")
    return obj.get("detection", {}).get("label", "")


def _confidence(obj: dict) -> float:
    return obj.get("detection", {}).get("confidence", 0.0)


def filter_objects(
    objects: Iterable[dict],
    label: Optional[str] = None,
    confidence_threshold: float = 0.0,
    max_rois_num: int = 0,
    label_fn: Callable[[dict], str] = default_label,
) -> List[dict]:
    """Keep objects matching ``label`` (comma-separated whitelist, None = any)
    and ``confidence_threshold``, capped to the ``max_rois_num`` highest-
    confidence survivors (0 = no cap). Mirrors gvaroifilter.cpp's
    should_keep_roi() + count-cap logic exactly.
    """
    labels = [part.strip() for part in label.split(",") if part.strip()] if label else None

    kept = [
        obj for obj in objects
        if _confidence(obj) >= confidence_threshold
        and (not labels or label_fn(obj) in labels)
    ]

    if max_rois_num and len(kept) > max_rois_num:
        kept = sorted(kept, key=_confidence, reverse=True)[:max_rois_num]

    return kept
