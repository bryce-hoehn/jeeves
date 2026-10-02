# --- Stage 1: build the SimulationCraft CLI from source --------------------
# simc is not packaged for Debian, so we compile it (see the repo's
# HowToBuild wiki). libcurl is kept so armory imports work.
FROM debian:trixie-slim AS simc-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        g++ \
        git \
        libcurl4-openssl-dev \
        make \
    && rm -rf /var/lib/apt/lists/*

# Branch or tag to build — override with --build-arg SIMC_REF=11.2.0
# to pin a release instead of tracking the development branch.
ARG SIMC_REF=midnight
RUN git clone --depth 1 --branch ${SIMC_REF} \
        https://github.com/simulationcraft/simc /tmp/simc \
    && make -C /tmp/simc/engine -j"$(nproc)" \
    && cp /tmp/simc/engine/simc /usr/local/bin/simc

# --- Stage 2: the bot --------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.12.21-python3.14-trixie-slim

# Runtime libraries for the simc binary (libcurl for armory imports).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcurl4 \
        libstdc++6 \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=simc-builder /usr/local/bin/simc /usr/local/bin/simc

WORKDIR /app

ENV UV_LINK_MODE=copy

# Dependencies first so code changes don't invalidate the cached layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY agent.py cron.py main.py mcp_servers.py ./
COPY tools/ tools/

CMD ["uv", "run", "--no-sync", "main.py"]
