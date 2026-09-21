FROM node:22-slim AS web-builder

ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org

WORKDIR /app/web

COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY web ./
RUN npm run build


FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /bin/

ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ARG UV_FILES_BASE_URL=https://files.pythonhosted.org/packages

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app \
    UV_CACHE_DIR=/tmp/uv-cache

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY server/src ./server/src
RUN sed -i "s#https://files.pythonhosted.org/packages#${UV_FILES_BASE_URL%/}#g" uv.lock \
    && UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX" uv sync --frozen --no-dev

COPY . .
COPY --from=web-builder /app/web/dist ./web/dist

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /home/app --create-home app \
    && chown -R app:app /app /home/app

USER app

EXPOSE 5050

CMD ["/app/.venv/bin/xuhua"]
