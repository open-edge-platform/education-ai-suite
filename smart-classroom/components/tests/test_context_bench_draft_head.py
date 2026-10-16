# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Derived DFlash artifacts: structured XML reads, new-directory-only writes, unchanged
inputs and recorded hashes. NumPy-dependent packing checks skip when NumPy is absent."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from components.context_bench import dflash_draft_head, trial_runner

HAS_NUMPY = importlib.util.find_spec("numpy") is not None


def _layer(layer_id, name, kind, outputs="", **data):
    attrs = " ".join(f'{key}="{value}"' for key, value in data.items())
    return (f'\t\t<layer id="{layer_id}" name="{name}" type="{kind}" version="opset1">\n'
            f'\t\t\t<data {attrs} />\n{outputs}\t\t</layer>\n')


def _head_ir(scale_type="f16", scale_shape="8, 1", transpose_b="true", weight_type="i8"):
    layers = (
        _layer(1, "self.model.lm_head.weight", "Const", element_type=weight_type, shape="8, 4",
               offset=100, size=32)
        + _layer(2, "lm_head/Convert", "Convert", destination_type="f16")
        + _layer(3, "self.model.lm_head.weight/scale", "Const", element_type=scale_type,
                 shape=scale_shape, offset=132, size=16)
        + _layer(4, "self.model.lm_head.weight/fq_weights_1", "Multiply", auto_broadcast="numpy")
        + _layer(5, "__module.model.lm_head/ov_ext::linear/Convert", "Convert", destination_type="f32")
        + _layer(6, "__module.model.lm_head/ov_ext::linear/MatMul", "MatMul", transpose_a="false",
                 transpose_b=transpose_b)
    )
    edges = "".join(f'\t\t<edge from-layer="{a}" from-port="0" to-layer="{b}" to-port="{p}" />\n'
                    for a, b, p in ((1, 2, 0), (2, 4, 0), (3, 4, 1), (4, 5, 0), (5, 6, 1)))
    return f'<?xml version="1.0"?>\n<net name="m" version="11">\n\t<layers>\n{layers}\t</layers>\n\t<edges>\n{edges}\t</edges>\n</net>\n'


def _residual(layer_id, index, rank=3):
    dims = "".join("<dim>-1</dim>" for _ in range(rank))
    port = f'\t\t\t<output><port id="2" precision="FP32">{dims}</port></output>\n'
    return _layer(layer_id, f"__module.model.language_model.layers.{index}/aten::add/Add_1", "Add",
                  outputs=port, auto_broadcast="numpy")


def _target_ir(rank=3, rt_info=""):
    layers = _residual(10, 1, rank) + _residual(11, 6, rank)
    return (f'<?xml version="1.0"?>\n<net name="t" version="11">\n\t<layers>\n{layers}\t</layers>\n'
            f'\t<edges />\n\t<rt_info>{rt_info}</rt_info>\n</net>\n')


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestLocateLmHead(unittest.TestCase):
    def _locate(self, **kwargs):
        with tempfile.TemporaryDirectory() as target:
            Path(target, "openvino_language_model.xml").write_text(_head_ir(**kwargs), encoding="utf-8")
            return dflash_draft_head.locate_lm_head(target)

    def test_finds_the_int8_weight_and_per_row_scale_offsets(self):
        head = self._locate()
        self.assertEqual((head["weight_offset"], head["scale_offset"]), (100, 132))
        self.assertEqual((head["vocab"], head["hidden"]), (8, 4))
        self.assertTrue(head["bin"].endswith("openvino_language_model.bin"))

    def test_refuses_heads_it_does_not_understand(self):
        for kwargs, message in (({"weight_type": "u8"}, "not int8 weights"),
                                ({"scale_shape": "8, 2"}, "not per-row"),
                                ({"transpose_b": "false"}, "transpose_b")):
            with self.subTest(**kwargs), self.assertRaisesRegex(dflash_draft_head.PreparationError, message):
                self._locate(**kwargs)

    def test_a_directory_without_an_ir_is_refused(self):
        with tempfile.TemporaryDirectory() as target, \
                self.assertRaisesRegex(dflash_draft_head.PreparationError, "has no"):
            dflash_draft_head.locate_lm_head(target)


@unittest.skipUnless(HAS_NUMPY, "NumPy is not installed in this environment")
class TestInt4Packing(unittest.TestCase):
    def test_round_trip_is_within_half_a_quantization_step(self):
        import numpy as np

        rng = np.random.default_rng(0)
        weight = rng.integers(-127, 128, size=(6, 256), dtype=np.int8)
        scale = rng.uniform(0.001, 0.01, size=(6, 1)).astype(np.float16)
        packed, scales = dflash_draft_head._quantize_int4(weight, scale, 128)
        nibbles = np.stack([packed & 0x0F, packed >> 4], axis=-1).reshape(6, 2, 128)
        values = np.where(nibbles > 7, nibbles.astype(np.int16) - 16, nibbles)
        rebuilt = (values * scales.astype(np.float32)).reshape(6, 256)
        original = weight.astype(np.float32) * scale.astype(np.float32)
        step = np.repeat(scales.astype(np.float32).reshape(6, 2), 128, axis=1)
        self.assertTrue(np.all(np.abs(rebuilt - original) <= step / 2 + 1e-6))
        self.assertEqual(packed.shape, (6, 2, 64))


class TestPrepareTarget(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.target, self.draft, self.output = root / "int4", root / "draft", root / "int4-dflash"
        self.target.mkdir()
        self.draft.mkdir()
        (self.target / "openvino_language_model.xml").write_text(_target_ir(), encoding="utf-8")
        (self.target / "openvino_language_model.bin").write_bytes(b"weights" * 100)
        (self.target / "config.json").write_text(json.dumps({"text_config": {"num_hidden_layers": 8}}),
                                                 encoding="utf-8")
        (self.draft / "config.json").write_text(json.dumps({"dflash_config": {"target_layer_ids": [1, 6]}}),
                                                encoding="utf-8")
        self.before = {p.name: _digest(p) for p in self.target.iterdir()}

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_an_annotated_copy_and_leaves_the_source_unchanged(self):
        out_xml = dflash_draft_head.prepare_target(self.target, self.draft, self.output)
        self.assertEqual({p.name: _digest(p) for p in self.target.iterdir()}, self.before)
        self.assertTrue(trial_runner.has_model_rt_info(str(out_xml), trial_runner.DFLASH_TARGET_RT_INFO_KEY))
        entry = ET.parse(out_xml).getroot().find(f"rt_info/{trial_runner.DFLASH_TARGET_RT_INFO_KEY}")
        annotation = json.loads(entry.attrib["value"])
        self.assertEqual(sorted(annotation["layers"]), ["1", "6"])
        self.assertTrue(annotation["layers"]["6"]["producer"].endswith("layers.6/aten::add/Add_1"))
        self.assertEqual(_digest(self.output / "openvino_language_model.bin"),
                         self.before["openvino_language_model.bin"])
        manifest = json.loads((self.output / dflash_draft_head.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_sha256"]["openvino_language_model.xml"],
                         self.before["openvino_language_model.xml"])
        self.assertEqual(manifest["output_sha256"]["openvino_language_model.xml"], _digest(out_xml))
        self.assertEqual(manifest["target_layer_ids"], [1, 6])

    def test_refuses_an_existing_output_or_an_input_as_output(self):
        self.output.mkdir()
        with self.assertRaisesRegex(dflash_draft_head.PreparationError, "existing"):
            dflash_draft_head.prepare_target(self.target, self.draft, self.output)
        with self.assertRaisesRegex(dflash_draft_head.PreparationError, "new directory"):
            dflash_draft_head.prepare_target(self.target, self.draft, self.target)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_refuses_an_already_annotated_target_and_bad_geometry_without_writing(self):
        (self.target / "openvino_language_model.xml").write_text(
            _target_ir(rank=2), encoding="utf-8")
        with self.assertRaisesRegex(dflash_draft_head.PreparationError, "rank 2"):
            dflash_draft_head.prepare_target(self.target, self.draft, self.output)
        self.assertFalse(self.output.exists())
        (self.target / "openvino_language_model.xml").write_text(
            _target_ir(rt_info='<hidden_states_decoder_layers value="{}" />'), encoding="utf-8")
        with self.assertRaisesRegex(dflash_draft_head.PreparationError, "already carries"):
            dflash_draft_head.prepare_target(self.target, self.draft, self.output)
        (self.draft / "config.json").write_text(json.dumps({"dflash_config": {"target_layer_ids": [9]}}),
                                                encoding="utf-8")
        (self.target / "openvino_language_model.xml").write_text(_target_ir(), encoding="utf-8")
        with self.assertRaisesRegex(dflash_draft_head.PreparationError, "target has 8"):
            dflash_draft_head.prepare_target(self.target, self.draft, self.output)

    def test_cli_returns_nonzero_without_writing_on_refusal(self):
        self.output.mkdir()
        code = dflash_draft_head.main(["prepare-target", "--target", str(self.target),
                                       "--draft", str(self.draft), "--output", str(self.output)])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
