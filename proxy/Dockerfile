# Bake the proxy for a cloud deployment.
#
# compose.yaml does NOT use this file: locally the Caddyfile and the dashboard
# are bind-mounted, so editing either takes effect on `docker compose restart
# proxy` with no rebuild. But Cloud Run, ECS and Container Apps have nothing to
# bind-mount from -- the config and the static file have to be inside an image.
#
# The dashboard is COPIED, not built. Build it on the host first:
#
#     pixi run build-app
#     docker build -f proxy/Dockerfile -t REGISTRY/chai-proxy:$(git rev-parse --short HEAD) .
#
# Build context is the repository root, because docs/app/ is outside proxy/.

# The Caddy binary is rebuilt from the same release with a patched Go toolchain
# (D-72). The official caddy:2 image of 2026-10-05 is Caddy v2.11.7 built with
# Go 1.26.8, which has two HIGH denial-of-service fixes pending in net/http and
# crypto/tls (CVE-2026-78667, CVE-2026-97031, fixed in Go 1.26.9 and 1.27.2), and
# this is the process every request reaches first. caddy:2-builder is the
# official image for building Caddy and carries Go 1.27.2. Revert to the plain
# official binary (drop this stage and the COPY --from below) once an official
# caddy:2 is built with a fixed Go; the image scan says when.
FROM caddy:2-builder@sha256:b25f47453fa02f7e66c0828b4b1343658808b9000950b6825c4a1cb0c988f5f8 AS caddy-build
ARG CADDY_VERSION=v2.11.7
# golang.org/x/net is raised for the same reason: v0.59.0, which v2.11.7 uses, has
# a HIGH fix pending in its HTTP/2 code (CVE-2026-78669, fixed in v0.60.0). xcaddy
# cannot pin a dependency, so this is Caddy's documented build from source: the
# standard modules, the release, and the one raised dependency, nothing added.
ARG X_NET_VERSION=v0.60.0
WORKDIR /src
RUN printf '%s\n' \
      'package main' \
      'import caddycmd "github.com/caddyserver/caddy/v2/cmd"' \
      'import _ "github.com/caddyserver/caddy/v2/modules/standard"' \
      'func main() { caddycmd.Main() }' > main.go \
 && go mod init caddy \
 && go get "github.com/caddyserver/caddy/v2@$CADDY_VERSION" "golang.org/x/net@$X_NET_VERSION" \
 && go mod tidy \
 && CGO_ENABLED=0 go build -trimpath -ldflags "-w -s" -o /usr/bin/caddy .

FROM caddy:2@sha256:f2a1290d0463aad60660d4ec134943f183ee2a5f6c3eb7bf32dd984f2f020772

COPY --from=caddy-build /usr/bin/caddy /usr/bin/caddy

COPY proxy/Caddyfile /etc/caddy/Caddyfile

# The Content-Security-Policy, generated from the built dashboard by
# scripts/build_app.py: its script-src is the hash of that page's script (#154).
COPY proxy/csp.caddy /etc/caddy/csp.caddy

# The single self-contained index.html produced by scripts/build_app.py.
COPY docs/app/ /srv/app/

# Unprivileged, like the compose stack's proxy (#50). /data and /config are where
# Caddy keeps certificates and config, so they are handed to this user here; in
# the image there is no root-owned volume to fix afterwards. The listener is on
# 8080, which needs no privilege.
RUN chown -R 65532:65532 /data /config
USER 65532:65532

# Cloud Run hands the port in $PORT (8080 by default) and routes only to the
# ingress container; sidecars are reachable on localhost and nowhere else.
# ECS awsvpc and Container Apps give the same localhost-only arrangement.
ENV SITE_ADDRESS=http://:8080
EXPOSE 8080

# Fail the build rather than ship a proxy that will not start.
RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
