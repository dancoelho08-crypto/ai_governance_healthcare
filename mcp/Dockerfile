# syntax=docker/dockerfile:1
#
# The optional MCP service (#164, R-73, D-91). Built exactly like the API image
# (server/Dockerfile): two stages, a lock verified by hash, base images pinned by
# digest, a non-root user with no shell, and no pip in the runtime image.
#
# It holds NO credential and writes nothing: compose runs it read-only with every
# capability dropped, and it is in a profile, so it does not start unless asked.

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src

# --require-hashes refuses anything not in the lock; the project itself is not
# installed (the runtime stage copies the source in and sets PYTHONPATH).
COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --require-hashes --no-deps -r requirements.txt \
 && /opt/venv/bin/pip uninstall --yes pip setuptools


FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

# Non-root, no login shell, no home directory.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 10002 chaimcp

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=root:root chai_mcp ./chai_mcp

USER 10002:10002

EXPOSE 8000

# Python, not curl: the slim image has no curl. /healthz is served to any Host and
# says nothing about the data.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request; p=os.environ.get('MCP_PORT') or '8000'; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=3).status==200 else 1)"]

# exec form, no shell: python is PID 1 and receives SIGTERM directly.
CMD ["python", "-m", "chai_mcp"]
