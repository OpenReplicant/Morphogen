FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY schemas ./schemas
RUN uv sync --no-dev
