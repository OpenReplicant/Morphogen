FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
# git: the promoter commits when intent/ is its own repository.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY schemas ./schemas
RUN uv sync --no-dev --frozen
