FROM ghcr.io/astral-sh/uv:0.9.5-python3.12-bookworm-slim
WORKDIR /app
ENV UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
COPY ingestion ./ingestion
COPY db ./db
EXPOSE 8100
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8100"]
