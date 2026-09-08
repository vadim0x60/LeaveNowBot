FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY leavenowbot ./leavenowbot
RUN uv sync --locked --no-dev

RUN useradd --system --uid 10001 app
USER app

CMD ["uvicorn", "leavenowbot.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]
