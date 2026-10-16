# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Explicit preparation of derived DFlash artifacts; never run inside a benchmark.

Two subcommands, both writing only to a *new* output directory (an existing one is refused),
leaving every input byte-identical, and recording source/output SHA-256 hashes in
``context_bench_derivation.json``:

``prepare-target``
    Derive a DFlash-ready target from an export that lacks the model-level
    ``hidden_states_decoder_layers`` rt_info GenAI uses to locate the hidden states the draft
    reads. The language-model XML is annotated through ElementTree (each draft
    ``target_layer_ids`` entry maps to its layer's final residual ``Add``); weights and
    every other file are hard-linked, or copied with ``--copy-weights`` or across volumes.
    The serving workflow derives the same layout as ``<weight_format>-dflash``.

``build-head``
    Give a DFlash draft its own quantized ``lm_head`` so GenAI stops grafting the target's
    (on Qwen3.6-35B-A3B int4 a 248320 x 2048 int8 matrix, streamed on every draft pass). The
    target's head is located in its XML -- only the int8-per-row-symmetric decompression chain
    optimum-intel writes is accepted -- read from its .bin by offset, requantized to int4
    symmetric (group 128) or copied as int8 (``--bits 8``, the control), checked against a
    NumPy reference on CPU, and appended to the draft graph with the OpenVINO IR API.
    Rebuild it whenever the target is re-exported.

    python -m components.context_bench.dflash_draft_head prepare-target \\
        --target models/openvino/Qwen3.6-35B-A3B/int4 \\
        --draft models/openvino/Qwen3.6-35B-A3B-DFlash/int4 \\
        --output models/openvino/Qwen3.6-35B-A3B/int4-dflash

    python -m components.context_bench.dflash_draft_head build-head \\
        --target models/openvino/Qwen3.6-35B-A3B/int4 \\
        --draft models/openvino/Qwen3.6-35B-A3B-DFlash/int4 \\
        --output models/openvino/Qwen3.6-35B-A3B-DFlash/int4-int4head

Requires OpenVINO and NumPy for ``build-head`` only; ``prepare-target`` uses the standard
library.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from components.context_bench import evidence, trial_runner

MANIFEST_NAME = "context_bench_derivation.json"

# Rows quantized per chunk: an f32 copy of the whole head would be 2 GB.
_CHUNK_ROWS = 16384


class PreparationError(ValueError):
    """The inputs are not the layout this utility qualifies; nothing was written."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _same_path(a, b) -> bool:
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def _check_output(output_dir, *inputs) -> Path:
    output = Path(output_dir)
    if any(_same_path(output, path) for path in inputs):
        raise PreparationError("--output must be a new directory, not one of the inputs")
    if output.exists():
        raise PreparationError(f"refusing to write into existing {output.name!r}; choose a new --output")
    if not output.parent.is_dir():
        raise PreparationError(f"the parent of --output does not exist: {output.parent.name!r}")
    return output


def _hashes(directory: Path) -> dict:
    return {
        path.relative_to(directory).as_posix(): evidence.file_sha256(str(path))
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


def _write_manifest(output: Path, payload: dict) -> None:
    redactor = evidence.PathRedactor(Path(__file__).resolve().parents[2])
    payload = {**payload, "created_utc": evidence.utc_now(), "tool": "context_bench.dflash_draft_head"}
    for key in ("source_target", "source_draft"):
        if payload.get(key):
            payload[key] = redactor.redact(payload[key])
    evidence.atomic_write_json(str(output / MANIFEST_NAME), payload)


def _parse_ir(xml_path) -> tuple:
    """``(tree, layers_by_id, producers_by_id)`` from an IR XML via ElementTree."""
    try:
        tree = ET.parse(str(xml_path))
    except (ET.ParseError, OSError) as exc:
        raise PreparationError(f"cannot parse {Path(xml_path).name}: {exc}") from exc
    root = tree.getroot()
    layers = {layer.get("id"): layer for layer in root.iter("layer") if layer.get("id")}
    producers: dict = {}
    edges = root.find("edges")
    for edge in (edges if edges is not None else []):
        producers.setdefault(edge.get("to-layer"), []).append(edge.get("from-layer"))
    return tree, layers, producers


def _data(layer) -> dict:
    data = layer.find("data")
    return dict(data.attrib) if data is not None else {}


# ---------------------------------------------------------------------------
# prepare-target
# ---------------------------------------------------------------------------
def dflash_layer_annotation(root, layer_ids: list) -> str:
    """GenAI's hidden-state locator JSON: each target layer's final residual Add."""
    layers = [layer for layer in root.iter("layer")]
    located = {}
    for layer_id in layer_ids:
        suffix = f"layers.{layer_id}/aten::add/Add_1"
        matches = [layer for layer in layers if (layer.get("name") or "").endswith(suffix)]
        if len(matches) != 1:
            raise PreparationError(
                f"target layer {layer_id}: expected one residual node ending in {suffix!r}, "
                f"found {len(matches)}"
            )
        port = matches[0].find("output/port")
        rank = len(port.findall("dim")) if port is not None else 0
        if rank != 3:
            raise PreparationError(f"target layer {layer_id} residual has rank {rank}, not 3")
        located[str(layer_id)] = {"producer": matches[0].get("name"), "output_index": 0}
    return json.dumps({"layers": located}, separators=(",", ":"))


def prepare_target(target_dir, draft_dir, output_dir, copy_weights: bool = False) -> Path:
    """Write an annotated copy of `target_dir` to the new `output_dir`; returns its XML path."""
    target_dir, draft_dir = Path(target_dir), Path(draft_dir)
    output = _check_output(output_dir, target_dir, draft_dir)
    xml_name = trial_runner.language_model_ir(str(target_dir))
    if xml_name is None:
        raise PreparationError("the target has no openvino_language_model.xml or openvino_model.xml")
    xml_path = Path(xml_name)
    key = trial_runner.DFLASH_TARGET_RT_INFO_KEY
    if trial_runner.has_model_rt_info(str(xml_path), key):
        raise PreparationError(f"the target already carries {key!r}; use it directly")
    try:
        layer_ids = trial_runner.dflash_target_layer_ids(str(draft_dir))
    except ValueError as exc:
        raise PreparationError(str(exc)) from exc
    try:
        config = json.loads((target_dir / "config.json").read_text(encoding="utf-8"))
        depth = (config.get("text_config") or config).get("num_hidden_layers")
    except (OSError, ValueError, AttributeError):
        depth = None
    if isinstance(depth, int) and max(layer_ids) >= depth:
        raise PreparationError(f"the draft reads target layer {max(layer_ids)}; the target has {depth}")

    source_hashes = _hashes(target_dir)
    tree, _layers, _producers = _parse_ir(xml_path)
    root = tree.getroot()
    annotation = dflash_layer_annotation(root, layer_ids)

    output.mkdir()
    try:
        for source in sorted(target_dir.rglob("*")):
            if not source.is_file() or source == xml_path:
                continue
            destination = output / source.relative_to(target_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if copy_weights:
                shutil.copy2(source, destination)
            else:
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copy2(source, destination)
        rt_info = root.find("rt_info")
        if rt_info is None:
            rt_info = ET.SubElement(root, "rt_info")
        ET.SubElement(rt_info, key, {"value": annotation})
        out_xml = output / xml_path.name
        tree.write(str(out_xml), encoding="utf-8", xml_declaration=True)
        if _hashes(target_dir) != source_hashes:
            raise PreparationError("a source file changed while preparing; output discarded")
        _write_manifest(output, {
            "kind": "dflash-target-metadata",
            "source_target": str(target_dir),
            "source_draft": str(draft_dir),
            "rt_info_key": key,
            "target_layer_ids": layer_ids,
            "weights": "copied" if copy_weights else "hard-linked where possible",
            "source_sha256": source_hashes,
            "output_sha256": _hashes(output),
        })
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return out_xml


# ---------------------------------------------------------------------------
# build-head
# ---------------------------------------------------------------------------
def locate_lm_head(target_dir: str) -> dict:
    """Byte offsets and shapes of the target's int8 lm_head weight and per-row scale.

    Walks back from the single MatMul named ``lm_head`` through
    ``MatMul <- Convert <- Multiply(Convert(Const i8 [V, H]), Const f16 [V, 1])``. Anything
    else raises PreparationError rather than quantizing the wrong tensor.
    """
    xml_name = trial_runner.language_model_ir(str(target_dir))
    if xml_name is None:
        raise PreparationError(f"{Path(target_dir).name} has no "
                               f"{' or '.join(trial_runner.LANGUAGE_MODEL_IRS)}")
    _tree, layers, producers = _parse_ir(xml_name)
    matmuls = [layer_id for layer_id, layer in layers.items()
               if layer.get("type") == "MatMul" and "lm_head" in (layer.get("name") or "")]
    if len(matmuls) != 1:
        raise PreparationError(f"expected one lm_head MatMul, found {len(matmuls)}")
    if _data(layers[matmuls[0]]).get("transpose_b") != "true":
        raise PreparationError("lm_head MatMul is not transpose_b; unsupported layout")

    def inputs(layer_id, kind):
        return [p for p in producers.get(layer_id, []) if layers.get(p) is not None
                and layers[p].get("type") == kind]

    multiply = [m for c in inputs(matmuls[0], "Convert") for m in inputs(c, "Multiply")]
    if len(multiply) != 1:
        raise PreparationError("lm_head is not a Convert(Multiply(...)) decompression chain")
    weight = scale = None
    for source in producers.get(multiply[0], []):
        layer = layers.get(source)
        if layer is None:
            continue
        if layer.get("type") == "Const" and _data(layer).get("element_type") == "f16":
            scale = _data(layer)
        elif layer.get("type") == "Convert":
            consts = inputs(source, "Const")
            if consts and _data(layers[consts[0]]).get("element_type") == "i8":
                weight = _data(layers[consts[0]])
    if weight is None or scale is None:
        raise PreparationError("lm_head is not int8 weights with a per-row f16 scale")
    try:
        vocab, hidden = (int(x) for x in weight["shape"].split(","))
        scale_shape = [int(x) for x in scale["shape"].split(",")]
    except (KeyError, ValueError) as exc:
        raise PreparationError("lm_head constants have unreadable shapes") from exc
    if scale_shape != [vocab, 1]:
        raise PreparationError(f"lm_head scale shape {scale['shape']} is not per-row")
    return {
        "bin": os.path.splitext(xml_name)[0] + ".bin",
        "weight_offset": int(weight["offset"]),
        "scale_offset": int(scale["offset"]),
        "vocab": vocab,
        "hidden": hidden,
    }


def _quantize_int4(weight, scale, group: int):
    """Requantize the int8 head to int4 symmetric per `group` columns: (packed u8, f16 scales)."""
    import numpy as np

    vocab, hidden = weight.shape
    groups = hidden // group
    packed = np.empty((vocab, groups, group // 2), np.uint8)
    scales = np.empty((vocab, groups, 1), np.float16)
    for start in range(0, vocab, _CHUNK_ROWS):
        stop = min(vocab, start + _CHUNK_ROWS)
        rows = weight[start:stop].astype(np.float32) * scale[start:stop].astype(np.float32)
        rows = rows.reshape(stop - start, groups, group)
        step = np.abs(rows).max(axis=2, keepdims=True) / 7.0
        step[step == 0] = 1.0
        # Codes are chosen against the f16 scale actually stored, so dequantization agrees.
        step = step.astype(np.float16)
        codes = np.clip(np.rint(rows / step.astype(np.float32)), -8, 7).astype(np.int8)
        nibbles = (codes & 0x0F).astype(np.uint8)
        packed[start:stop] = nibbles[..., 0::2] | (nibbles[..., 1::2] << 4)  # low nibble first
        scales[start:stop] = step
    return packed, scales


def build_head(hidden_state, weight, scale, bits: int, group: int):
    """Append ``logits = hidden_state @ dequant(head).T`` to a graph; returns the MatMul node."""
    import numpy as np
    import openvino as ov
    import openvino.opset13 as ops

    vocab, hidden = weight.shape
    if bits == 8:
        decompressed = ops.multiply(
            ops.convert(ops.constant(np.ascontiguousarray(weight), dtype=ov.Type.i8), ov.Type.f16),
            ops.constant(np.ascontiguousarray(scale)),
        )
    else:
        if hidden % group:
            raise PreparationError(f"hidden size {hidden} is not a multiple of group {group}")
        packed, scales = _quantize_int4(weight, scale, group)
        tensor = ov.Tensor(ov.Type.i4, ov.Shape([vocab, hidden // group, group]))
        np.copyto(tensor.data.view(np.uint8).reshape(-1), packed.reshape(-1))
        decompressed = ops.reshape(
            ops.multiply(ops.convert(ops.constant(tensor), ov.Type.f16), ops.constant(scales)),
            ops.constant(np.array([vocab, hidden], np.int64)),
            special_zero=False,
        )
    return ops.matmul(hidden_state, ops.convert(decompressed, ov.Type.f32),
                      transpose_a=False, transpose_b=True)


def _self_check(weight, scale, bits: int, group: int) -> float:
    """Relative error of the compiled head against the same quantization done in NumPy."""
    import numpy as np
    import openvino as ov
    import openvino.opset13 as ops

    rows = min(4096, weight.shape[0])
    weight, scale = np.asarray(weight[:rows]), np.asarray(scale[:rows])
    hidden = ops.parameter([4, weight.shape[1]], ov.Type.f32)
    model = ov.Model([ops.result(build_head(hidden, weight, scale, bits, group))], [hidden])
    probe = np.random.default_rng(0).standard_normal((4, weight.shape[1])).astype(np.float32)
    got = ov.Core().compile_model(model, "CPU")(probe)[0]
    reference = weight.astype(np.float32) * scale.astype(np.float32)
    if bits == 4:
        packed, scales = _quantize_int4(weight, scale, group)
        nibbles = np.stack([packed & 0x0F, packed >> 4], axis=-1).reshape(rows, -1, group)
        values = np.where(nibbles > 7, nibbles.astype(np.int16) - 16, nibbles).astype(np.float32)
        reference = (values * scales.astype(np.float32)).reshape(rows, -1)
    expected = probe @ reference.T
    return float(np.abs(got - expected).max() / np.abs(expected).max())


def build_draft(target_dir: str, draft_dir: str, output_dir: str, bits: int = 4,
                group: int = 128) -> str:
    """Write `draft_dir` plus its own lm_head to the new `output_dir`; returns the IR path."""
    import numpy as np
    import openvino as ov
    import openvino.opset13 as ops

    output = _check_output(output_dir, target_dir, draft_dir)
    head = locate_lm_head(target_dir)
    draft_xml = os.path.join(draft_dir, "openvino_model.xml")
    if not os.path.isfile(draft_xml):
        raise PreparationError("the draft directory has no openvino_model.xml")
    source_hashes = {"target_head_bin": evidence.file_sha256(head["bin"]),
                     "draft": _hashes(Path(draft_dir))}
    weight = np.memmap(head["bin"], np.int8, "r", offset=head["weight_offset"],
                       shape=(head["vocab"], head["hidden"]))
    scale = np.memmap(head["bin"], np.float16, "r", offset=head["scale_offset"],
                      shape=(head["vocab"], 1))
    error = _self_check(weight, scale, bits, group)
    if error > 0.01:
        raise PreparationError(f"rebuilt head disagrees with its NumPy reference (rel. error {error:.4f})")

    model = ov.Core().read_model(draft_xml)
    if [port.get_names() & {"logits"} for port in model.outputs] != [set()]:
        raise PreparationError("draft must have exactly one output and no `logits` yet")
    old_result = model.get_results()[0]
    hidden_state = old_result.input_value(0)
    if hidden_state.get_partial_shape()[-1].get_length() != head["hidden"]:
        raise PreparationError("draft hidden size does not match the target lm_head")
    if hidden_state.get_element_type() != ov.Type.f32:
        hidden_state = ops.convert(hidden_state, ov.Type.f32)
    logits = ops.result(build_head(hidden_state, weight, scale, bits, group))
    logits.output(0).get_tensor().set_names({"logits"})
    model.add_results([logits])
    model.remove_result(old_result)
    model.validate_nodes_and_infer_types()

    output.mkdir()
    try:
        output_xml = output / "openvino_model.xml"
        ov.save_model(model, str(output_xml), compress_to_fp16=False)
        for name in os.listdir(draft_dir):
            source = os.path.join(draft_dir, name)
            if os.path.isfile(source) and not name.startswith("openvino_model."):
                shutil.copyfile(source, output / name)
        _write_manifest(output, {
            "kind": "dflash-draft-lm-head",
            "source_target": str(target_dir),
            "source_draft": str(draft_dir),
            "bits": bits,
            "group_size": group,
            "self_check_relative_error": error,
            "source_sha256": source_hashes,
            "output_sha256": _hashes(output),
        })
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return str(output_xml)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m components.context_bench.dflash_draft_head",
        description="Prepare derived DFlash artifacts in a new directory (inputs are never modified).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    target = commands.add_parser("prepare-target", help="annotate a target with hidden-state rt_info")
    head = commands.add_parser("build-head", help="give a draft its own quantized lm_head")
    for sub in (target, head):
        sub.add_argument("--target", required=True, help="target model IR directory")
        sub.add_argument("--draft", required=True, help="DFlash draft IR directory")
        sub.add_argument("--output", required=True, help="new directory for the derived artifact")
    target.add_argument("--copy-weights", action="store_true",
                        help="copy weights instead of hard-linking them")
    head.add_argument("--bits", type=int, choices=(4, 8), default=4,
                      help="4: int4 symmetric head; 8: exact copy of the graft (control)")
    head.add_argument("--group-size", type=int, default=128)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-target":
            path = prepare_target(args.target, args.draft, args.output, args.copy_weights)
        else:
            path = build_draft(args.target, args.draft, args.output, args.bits, args.group_size)
    except PreparationError as exc:
        print(f"dflash_draft_head: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {Path(path).parent.name}/{Path(path).name} and {MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
