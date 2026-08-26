FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend ./
RUN npm run build


FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app \
    UV_CACHE_DIR=/tmp/uv-cache \
    HOST=0.0.0.0 \
    PORT=5050

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY . .
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /home/app --create-home app \
    && chown -R app:app /app /home/app

USER app

EXPOSE 5050

CMD ["sh", "-c", "exec uv run --frozen --no-dev uvicorn heritage_explorer.api:app --host ${HOST:-0.0.0.0} --port ${PORT:-5050}"]
