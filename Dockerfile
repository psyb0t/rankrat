FROM ghcr.io/astral-sh/uv:0.11.31@sha256:ecd4de2f060c64bea0ff8ecb182ddf46ba3fcccdc8a60cfdbaf20d1a047d7437 AS uv

FROM public.ecr.aws/docker/library/python:3.14.6-slim-trixie@sha256:d4fea6e20c09820028eea3f5c17f5b8ebd2ecb9c2bf28e561681a74a96090e4f AS builder

COPY --from=uv /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM public.ecr.aws/docker/library/python:3.14.6-slim-trixie@sha256:d4fea6e20c09820028eea3f5c17f5b8ebd2ecb9c2bf28e561681a74a96090e4f AS runtime

# The MCP registry verifies namespace ownership of an oci package by reading this
# label off the pushed image and matching it against server.json's "name".
# Without it, mcp-registry-publish rejects the entry.
LABEL io.modelcontextprotocol.server.name="io.github.psyb0t/rankrat"

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 rankrat \
    && useradd --create-home --uid 10001 --gid rankrat --shell /usr/sbin/nologin rankrat \
    && install --directory --owner=rankrat --group=rankrat --mode=0750 \
        /run/config \
        /run/oauth \
        /run/lighthouse \
        /run/secrets/google \
        /run/secrets/bing \
        /run/secrets/indexnow \
        /run/secrets/rankrat

WORKDIR /app
COPY --from=builder --chown=rankrat:rankrat /app/.venv /app/.venv

USER rankrat:rankrat

EXPOSE 8080
ENTRYPOINT ["rankrat"]
CMD ["stdio"]
