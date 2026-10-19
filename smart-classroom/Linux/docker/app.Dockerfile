# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#

FROM node:22-bookworm-slim AS ui-builder

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""

WORKDIR /ui

COPY ui/package.json ui/package-lock.json ./
RUN HTTP_PROXY="$HTTP_PROXY" HTTPS_PROXY="$HTTPS_PROXY" NO_PROXY="$NO_PROXY" npm ci

ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY ui/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1


ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""

COPY docker/system_requirements.txt ./system_requirements.txt
RUN HTTP_PROXY="$HTTP_PROXY" HTTPS_PROXY="$HTTPS_PROXY" NO_PROXY="$NO_PROXY" \
    apt-get update && apt-get install -y --no-install-recommends \
        $(grep -v '^#' system_requirements.txt | xargs) \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN HTTP_PROXY="$HTTP_PROXY" HTTPS_PROXY="$HTTPS_PROXY" NO_PROXY="$NO_PROXY" \
    pip install --no-cache-dir -r requirements.txt

# Non-root runtime user.
RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY main.py ./main.py
COPY pipeline.py ./pipeline.py
COPY monitoring/ ./monitoring/
COPY --from=ui-builder /ui/dist ./ui/dist

COPY utils/ ./utils/
COPY components/ ./components/
COPY api/ ./api/
COPY model_manager/ ./model_manager/
COPY services/ ./services/
COPY dto/ ./dto/
COPY constants/ ./constants/
COPY prompts/ ./prompts/
COPY config.yaml runtime_config.yaml ./

RUN chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=10 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
