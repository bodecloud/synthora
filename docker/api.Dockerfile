FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock alembic.ini langgraph.json ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "synthora.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
