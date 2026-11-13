# One image for every component; Cloud Run services/jobs pick the command.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY ingest ingest
COPY processor processor
COPY notifier notifier
COPY data/replay data/replay
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
CMD exec uvicorn processor.app:app --host 0.0.0.0 --port ${PORT:-8080}
