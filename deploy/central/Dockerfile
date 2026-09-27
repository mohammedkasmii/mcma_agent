# syntax=docker/dockerfile:1
#
# MCMA central server image (Phase 2 deployment foundation).
# Build from the REPOSITORY ROOT:
#   docker build -f deploy/central/Dockerfile -t mcma-central:<tag> .
#
# Runs mcma.app.central_server only: API + built frontend + headless
# notification polling. No local runner, no mock portal, no Firefox/WebKit.

ARG PYTHON_IMAGE=python:3.14.7-slim-trixie
ARG NODE_IMAGE=node:22.23.3-slim

# --- 1. frontend build (Node >= 22.12; discarded after copying dist) ---------
FROM ${NODE_IMAGE} AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite build + scripts/audit-build.mjs (CSP policy audit) -- fails the image on drift
RUN npm run build

# --- 2. locked Python dependencies (uv.lock, no dev group) -------------------
FROM ${PYTHON_IMAGE} AS pydeps
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.12.9
WORKDIR /build
COPY pyproject.toml uv.lock ./
# pymupdf (65 MB) is used only by the legacy baseline; nothing under mcma/ imports it.
RUN uv sync --frozen --no-dev --no-install-project --no-install-package pymupdf

# --- 3. runtime ---------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
ARG MCMA_UID=10001
ARG MCMA_GID=10001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    HOME=/tmp

COPY --from=pydeps /opt/venv /opt/venv

# Chromium headless shell ONLY (the central server is always headless), plus
# its OS libraries, installed and left exactly as apt/Playwright installs them.
# No dpkg --force-depends surgery: the package database must stay consistent,
# so the assertion below (dpkg --audit prints nothing) can hold. The only trim
# is apt-managed: CJK/emoji/unifont fonts are purged with their dependents.
RUN playwright install --only-shell --with-deps chromium \
    && apt-get purge -y --auto-remove fonts-noto-color-emoji fonts-wqy-zenhei \
         fonts-ipafont-gothic fonts-unifont fonts-tlwg-loma-otf \
    && test -z "$(dpkg --audit)" \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /root/.cache /tmp/* \
    && groupadd --system --gid ${MCMA_GID} mcma \
    && useradd --system --uid ${MCMA_UID} --gid ${MCMA_GID} --no-create-home \
               --home-dir /nonexistent --shell /usr/sbin/nologin mcma

WORKDIR /app
COPY mcma /app/mcma
COPY --from=frontend /build/frontend/dist /app/frontend/dist
COPY deploy/central/healthcheck.py /opt/mcma/healthcheck.py
RUN python -m compileall -q /app/mcma /opt/mcma

USER mcma
EXPOSE 8443
ENTRYPOINT ["python", "-m", "mcma.app.central_server"]
