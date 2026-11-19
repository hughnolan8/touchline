FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY touchline ./touchline
RUN uv sync --frozen --no-dev && useradd --create-home --uid 10001 touchline \
    && mkdir -p /data && chown touchline /data
USER touchline
ENV PATH="/app/.venv/bin:$PATH" TOUCHLINE_DB=/data/touchline.sqlite3
EXPOSE 8080
CMD ["uvicorn", "touchline.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
