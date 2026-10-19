# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""

RUN HTTP_PROXY="$HTTP_PROXY" HTTPS_PROXY="$HTTPS_PROXY" NO_PROXY="$NO_PROXY" \
    pip install --no-cache-dir PyYAML==6.0.2

WORKDIR /app

# Only what utils/ovms_provision.py + utils/config_loader.py need at import
# time — not the full app source tree.
COPY utils/ ./utils/
COPY config.yaml ./config.yaml

ENTRYPOINT ["python", "-m", "utils.ovms_provision"]
CMD ["--check"]
