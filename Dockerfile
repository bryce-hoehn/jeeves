FROM ghcr.io/astral-sh/uv:0.12.6-python3.14-bookworm-slim

WORKDIR /app

ENV UV_LINK_MODE=copy

# Dependencies first so code changes don't invalidate the cached layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY agent.py main.py mcp_servers.py ./
COPY tools/ tools/

CMD ["uv", "run", "--no-sync", "main.py"]
