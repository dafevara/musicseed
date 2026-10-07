# syntax=docker/dockerfile:1

# Build tools are discarded; only the final Python/Alpine stage ships.
ARG PYTHON_IMAGE=python:3.12-alpine3.23
ARG NODE_IMAGE=node:22-alpine3.23
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.23

FROM ${UV_IMAGE} AS uv-build

FROM ${NODE_IMAGE} AS web-deps
WORKDIR /build/web
ENV NEXT_TELEMETRY_DISABLED=1
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

FROM web-deps AS web-build
COPY web/ ./
RUN --mount=type=cache,target=/build/web/.next/cache npm run build

FROM ${PYTHON_IMAGE} AS python-base
ARG ALPINE_MIRROR=https://dl-4.alpinelinux.org/alpine
# Native musllinux wheels need these shared libraries, not a compiler toolchain.
RUN sed -i "s|https://dl-cdn.alpinelinux.org/alpine|${ALPINE_MIRROR}|g" /etc/apk/repositories \
    && apk add --no-cache libgcc libstdc++
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

FROM python-base AS python-deps
COPY --from=uv-build /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy
WORKDIR /build
COPY docker/requirements.txt ./requirements.txt
# Fail clearly if a pinned dependency has no Alpine wheel for this architecture.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /usr/local/bin/python --only-binary=:all: \
    --target=/opt/dependencies -r requirements.txt

FROM python-deps AS python-build
COPY core/pyproject.toml core/README.md ./core/
COPY api/pyproject.toml ./api/
COPY cli/pyproject.toml cli/README.md ./cli/
COPY mcp/pyproject.toml mcp/README.md ./mcp/
COPY core/src/ ./core/src/
COPY api/src/ ./api/src/
COPY cli/src/ ./cli/src/
COPY mcp/src/ ./mcp/src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /usr/local/bin/python --no-deps --target=/opt/musicseed \
    ./core ./api ./cli ./mcp
# Check the combined environment, including all four package requirements.
RUN PYTHONPATH=/opt/musicseed:/opt/dependencies python -m pip check

FROM python-base AS runtime
ARG MUSICSEED_UID=1000
ARG MUSICSEED_GID=1000
RUN addgroup -S -g "${MUSICSEED_GID}" musicseed \
    && adduser -S -D -H -h /data -u "${MUSICSEED_UID}" -G musicseed musicseed \
    && mkdir -p /data/.config/musicseed /data/.local/share/musicseed \
       /data/.cache/musicseed /data/.ssh \
    && chown -R musicseed:musicseed /data \
    && chmod 700 /data /data/.config /data/.config/musicseed \
       /data/.local /data/.local/share /data/.local/share/musicseed \
       /data/.cache /data/.cache/musicseed /data/.ssh
ENV HOME=/data \
    PYTHONPATH=/opt/musicseed:/opt/dependencies \
    PATH=/opt/musicseed/bin:/opt/dependencies/bin:$PATH \
    MUSICSEED_STATIC_DIR=/opt/web
WORKDIR /opt/musicseed
# Dependencies, Python source packages, and static UI remain separate layers.
COPY --from=python-deps /opt/dependencies /opt/dependencies
COPY --from=python-build /opt/musicseed /opt/musicseed
COPY --from=web-build /build/web/out /opt/web
USER musicseed
VOLUME ["/data"]
EXPOSE 8789
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8789/api/openapi.json', timeout=3).close()"
CMD ["musicseed", "--host", "0.0.0.0"]
