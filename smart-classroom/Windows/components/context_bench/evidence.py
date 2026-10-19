# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Run directories, atomic checkpoints, path redaction and artifact identities.

Helpers for `benchmark.py`, which owns all run-level state. `results.json` is the
authoritative evidence record; `report.txt` is rendered from the same snapshot. Both are
written through a temporary file and an atomic replace, so a reader never sees a torn file,
and both carry the run ID and revision so a stale report is detectable.

Absolute paths stay in process memory. Exported settings and diagnostics use paths relative
to the Smart Classroom root for files inside it, and an opaque ``external:<id>`` for
anything outside; user names, host names and credentials are never written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
RESULTS_NAME = "results.json"
REPORT_NAME = "report.txt"

# Files hashed for an artifact identity. Weight binaries are identified by size: hashing tens
# of GiB per run would dominate a short benchmark. The derivation utility hashes them.
_IDENTITY_SUFFIXES = (".xml", ".json")
_HASH_CHUNK = 1 << 20

# Fields carrying generated or planted text; persisted only under `record_text: true`.
TEXT_FIELDS = ("output_text", "prediction_text", "prediction", "truth", "distractors")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def create_run_dir(output_base: str) -> tuple:
    """Create ``<output_base>/<UTC-timestamp>-<unique-suffix>/`` exclusively.

    Returns ``(run_id, path)``. Never reuses or overwrites an existing directory.
    """
    os.makedirs(output_base, exist_ok=True)
    for _ in range(8):
        run_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                  + "-" + secrets.token_hex(4))
        path = os.path.join(output_base, run_id)
        try:
            os.mkdir(path)
        except FileExistsError:
            continue
        return run_id, path
    raise OSError("could not create a unique run directory")


def atomic_write_text(path: str, text: str) -> None:
    """Write `text` to `path` via a temporary sibling and ``os.replace``."""
    directory = os.path.dirname(os.path.abspath(path))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", delete=False, dir=directory,
            prefix="." + os.path.basename(path) + ".", suffix=".tmp",
        ) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(path: str, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=False, allow_nan=False,
                                       default=_json_default) + "\n")


def _json_default(value):
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if hasattr(value, "items"):
        return dict(value.items())
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def to_plain(value):
    """Deep copy into JSON-shaped data: mappings to dicts, sequences to lists, NaN to None."""
    if isinstance(value, dict) or (hasattr(value, "items") and hasattr(value, "keys")):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_plain(item) for item in value]
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PathRedactor:
    """Maps absolute paths to exportable identifiers without changing what is loaded."""

    def __init__(self, root: str):
        self.root = os.path.normcase(os.path.abspath(root))
        self._root_display = os.path.abspath(root)
        self._home = os.path.normcase(os.path.expanduser("~"))

    def redact(self, path) -> str | None:
        if path is None:
            return None
        absolute = os.path.abspath(str(path))
        normalized = os.path.normcase(absolute)
        try:
            common = os.path.commonpath([self.root, normalized])
        except ValueError:  # different drives
            common = None
        if common == self.root:
            relative = os.path.relpath(absolute, self._root_display)
            return Path(relative).as_posix()
        return "external:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]

    def text(self, text) -> str:
        """Redact known roots and any absolute path left in a diagnostic string."""
        from components.context_bench.trial_runner import sanitize_message

        value = str(text or "")
        for prefix, replacement in ((self._root_display, "<smart-classroom>"),
                                    (os.path.expanduser("~"), "<home>")):
            if prefix and len(prefix) > 3:
                value = re.sub(re.escape(prefix), replacement, value, flags=re.IGNORECASE)
        return sanitize_message(value, limit=2000)


def artifact_identity(model_dir: str, redactor: PathRedactor) -> dict:
    """Location, small-file hashes and weight sizes of one artifact directory.

    The identity ID is a hash over the graph/config/tokenizer hashes and weight sizes, so
    two directories holding the same export compare equal regardless of their location.
    """
    files, weights = {}, {}
    if os.path.isdir(model_dir):
        for name in sorted(os.listdir(model_dir)):
            path = os.path.join(model_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                if name.endswith(_IDENTITY_SUFFIXES):
                    files[name] = file_sha256(path)
                elif name.endswith(".bin"):
                    weights[name] = os.path.getsize(path)
            except OSError:
                continue
    digest = hashlib.sha256(json.dumps({"files": files, "weights": weights},
                                       sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "location": redactor.redact(model_dir),
        "artifact_id": digest[:16] if files or weights else None,
        "file_sha256": files,
        "weight_bytes": weights,
        "weight_hash_method": "size only (binaries are not content-hashed per run)",
    }


def strip_text(value, record_text: bool):
    """Drop generated/planted text fields unless `record_text` is set; copy otherwise."""
    if isinstance(value, dict):
        return {
            key: strip_text(item, record_text) for key, item in value.items()
            if record_text or key not in TEXT_FIELDS
        }
    if isinstance(value, list):
        return [strip_text(item, record_text) for item in value]
    return value


def package_versions(names) -> dict:
    """Installed distribution versions read from metadata, without importing packages."""
    from importlib import metadata

    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except Exception:  # noqa: BLE001
            versions[name] = None
    return versions
