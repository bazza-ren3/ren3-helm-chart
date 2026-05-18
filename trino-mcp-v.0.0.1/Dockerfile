# MCP stdio server — mount overlay at runtime to override bundled semantic/.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY server.py config.py trino_client.py sample_queries.py semantic_layer.py sql_knowledge.py ./
COPY tools/ ./tools/
COPY prompts/ ./prompts/
COPY semantic/ ./semantic/
COPY samples/sample_queries.yaml ./samples/
COPY skills/ ./skills/

ENV SEMANTIC_OVERLAY_PATH=/app/overlay.yaml

ENTRYPOINT ["uv", "run", "python", "server.py"]
