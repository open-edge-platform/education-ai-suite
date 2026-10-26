# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""convert_worker: exports survive an optional module that Windows refuses to load."""

import importlib.abc
import importlib.util
import sys

import pytest

from components.vlm.vlm_openvino_serving.utils import convert_worker


class _BlockedLoader(importlib.abc.Loader):
    """Fails like a DLL refused by Windows Application Control."""

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise ImportError("DLL load failed while importing lib: blocked by policy")


class _BlockedFinder(importlib.abc.MetaPathFinder):
    def __init__(self, name):
        self.name = name

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.name:
            return importlib.util.spec_from_loader(fullname, _BlockedLoader())
        return None


def test_an_unloadable_optional_module_is_treated_as_not_installed(monkeypatch):
    name = "_sc_blocked_optional"
    monkeypatch.setattr(convert_worker, "OPTIONAL_MODULES", (name,))
    monkeypatch.setattr(sys, "meta_path", [_BlockedFinder(name), *sys.meta_path])
    monkeypatch.delitem(sys.modules, name, raising=False)

    convert_worker.skip_unloadable_optional_modules()

    # How optimum-intel and transformers probe optional packages.
    assert importlib.util.find_spec(name) is None
    with pytest.raises(ImportError):
        importlib.import_module(name)
    monkeypatch.delitem(sys.modules, name)


def test_a_loadable_optional_module_is_left_alone(monkeypatch):
    monkeypatch.setattr(convert_worker, "OPTIONAL_MODULES", ("json",))
    convert_worker.skip_unloadable_optional_modules()
    assert sys.modules["json"] is not None


def test_optimum_cli_mode_dispatches_before_argument_parsing(monkeypatch):
    seen = []
    monkeypatch.setattr(convert_worker, "optimum_cli", lambda argv: seen.append(argv) or 0)
    assert convert_worker.main(["optimum-cli", "export", "openvino", "--help"]) == 0
    assert seen == [["export", "openvino", "--help"]]
