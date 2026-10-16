# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Offline, text-only OpenVINO LLM benchmark (``python -m components.context_bench.benchmark``).

Deliberately empty: importing the package must not pull in OpenVINO, transformers or numpy,
so planning (``--list-profiles``) and the hardware-independent tests run without them.
Inference imports live inside the child-process functions in ``trial_runner``.
"""
