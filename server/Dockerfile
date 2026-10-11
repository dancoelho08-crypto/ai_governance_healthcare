# syntax=docker/dockerfile:1
#
# Two stages so the runtime image carries no compiler, no pip cache, no pip and no
# build metadata: only the interpreter, the virtualenv and the app.
#
# What is installed is exactly what requirements.txt says, verified by hash
# (#37): a rebuild in six months produces the same dependencies from the same
# source, and a tampered or substituted package fails the build. The base images
# are pinned by digest for the same reason; Dependabot keeps both moving, so a new
# base image is a reviewed change, not whatever the tag points at that day.
#
# Regenerate the lock with `make lock` (pip-compile --generate-hashes).
#
# Nothing in this image refers to its directory by name, so the build context
# can be ./server or ./api without edits.

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src

# This layer is cached until the lock itself changes, not on every source edit.
# --require-hashes refuses anything not in the lock, and the project itself is NOT
# installed: the runtime stage copies the source in at /app and sets PYTHONPATH, and
# installing it from PyPI-resolved build dependencies would be an unpinned step in a
# pinned build.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --require-hashes --no-deps -r requirements.txt \
 && /opt/venv/bin/pip uninstall --yes pip setuptools
# pip is removed on purpose: nothing at runtime installs anything, and the pip
# that ships here vendors copies of urllib3, msgpack and others that vulnerability
# scanners (rightly) flag, in a place the application can never use them (#37).


FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS runtime

# PYTHONUNBUFFERED: without it, logs sit in a pipe buffer and a container that
# dies takes its last words with it.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

# Non-root, with no shell and no home directory to write into. The app needs
# neither; a process that cannot write to disk cannot be made to persist
# anything an attacker leaves behind.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin --uid 10001 chai

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=root:root app ./app
COPY --chown=root:root migrations ./migrations

USER 10001:10001

EXPOSE 8000

# Python rather than curl: the slim image has no curl, and adding one for a
# health check is a package of attack surface for a single HTTP GET.
# /api/health is unauthenticated precisely so this works -- there is no proxy
# inside the container to add an identity header.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request; p=os.environ.get('PORT') or os.environ.get('API_PORT') or '8000'; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health', timeout=3).status==200 else 1)"]

# PORT is what Cloud Run and most platforms set; API_PORT is what this
# repository's compose.yaml sets. exec so uvicorn is PID 1 and receives
# SIGTERM directly -- otherwise shutdown waits for the 10s kill timeout and
# every open SSE stream dies hard instead of closing.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-${API_PORT:-8000}} --no-server-header --no-proxy-headers --timeout-graceful-shutdown 20"]
