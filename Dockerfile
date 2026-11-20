FROM python:3.12-slim

# Ownership verification for the MCP Registry (registry.modelcontextprotocol.io):
# must match the "name" field in server.json.
LABEL io.modelcontextprotocol.server.name="io.github.b-ak/kanboard-mcp-server"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTMCP_HOME=/data \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . \
    && useradd --system --uid 10001 --no-create-home app \
    && mkdir -p /data && chown app /data

USER app
# OAuth client registrations and tokens live here; mount a volume so logins survive restarts.
VOLUME /data
EXPOSE 8000
CMD ["kanboard-mcp"]
