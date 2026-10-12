# =============================================================================
# Thin wrapper over docker compose.
#
# It earns its place for one reason: the development stack is two -f flags
# (`-f compose.yaml -f compose.dev.yaml`) and getting them wrong silently runs
# the production file instead. Everything else here is a shortcut that would
# otherwise be a paragraph in a README nobody reads at 2am.
# =============================================================================

# pipefail: `backup` and `restore` are pipelines (pg_dump | gzip | gpg, and
# gpg | gunzip | psql). Without it a pipeline exits with its LAST command's status,
# so a failed pg_dump left an "encrypted" empty file and a success, and a restore
# with the wrong passphrase exited 0 having restored nothing.
SHELL       := bash
.SHELLFLAGS := -o pipefail -c

COMPOSE     := docker compose
DEV         := $(COMPOSE) -f compose.yaml -f compose.dev.yaml
DB_SERVICE  := db
BACKUP_DIR  := backups

# .env is read by compose automatically; these mirror its defaults so the
# backup and psql targets work without sourcing it.
POSTGRES_USER ?= chai
POSTGRES_DB   ?= chai
HTTP_PORT     ?= 8080

.DEFAULT_GOAL := help
.PHONY: help env preflight doctor up dev down logs ps config build-app shell psql backup backup-plaintext restore reapply-purges dispose agent-tokens verify-backup subject-access phi-scan prune check-isolation lock lock-mcp

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env: .env  ## Create .env from .env.example if it is missing
.env:
	@cp .env.example .env
	@echo ".env created from .env.example. It is deliberately incomplete:"
	@echo "  POSTGRES_PASSWORD      empty  -> openssl rand -base64 32"; \
	 echo "  APP_POSTGRES_PASSWORD  empty  -> a DIFFERENT openssl rand -base64 32"
	@echo "  IDENTITY_ID_SOURCE  empty  -> set to your SSO front door's header"
	@echo "`make up` will tell you what is still missing. For a laptop, `make dev`."

preflight:  ## Check .env for settings that would deploy insecurely
	@python3 scripts/preflight.py

# preflight reads .env and nothing else, so it cannot see the one failure .env
# causes and cannot explain: Postgres applies POSTGRES_PASSWORD only when it
# initializes an empty volume, so changing it later leaves the database on the
# old one. This asks the running database what it actually accepts.
doctor:  ## Diagnose a stack that is up but not working
	@python3 scripts/doctor.py

build-app:  ## Rebuild docs/app/index.html from app/ (runs on the host, not in Docker)
	pixi run build-app

up: env preflight  ## Production-shaped stack: no exposed API, no exposed database
	$(COMPOSE) up -d
	@echo "Dashboard: http://localhost:$(HTTP_PORT)/"

# POSTGRES_PASSWORD is supplied here rather than left to .env. The base file
# guards it with `${VAR:?...}`, and compose resolves that during interpolation
# of compose.yaml -- BEFORE compose.dev.yaml's default can override it. So an
# empty password in .env (which is what the template ships, on purpose) stops
# `make dev` too, for a stack that has no business needing a real one. Read the
# .env value if there is one, fall back to the dev-only string otherwise.
dev: env  ## Development stack: fixed dev identity, hot reload, exposed ports
	@PW="$$(sed -n 's/^POSTGRES_PASSWORD=//p' .env | tr -d '\"'\''')"; \
	 ID="$$(sed -n 's/^DEV_IDENTITY_ID=//p' .env | tr -d '\"'\''')"; \
	 POSTGRES_PASSWORD="$${PW:-dev-only-not-a-secret}" \
	 IDENTITY_ID_SOURCE="$${ID:-dev@localhost}" \
	 $(DEV) up

down:  ## Stop and remove containers (the MCP profile's too). The pgdata volume SURVIVES this.
	$(COMPOSE) --profile agent-mcp down

logs:  ## Follow logs for all services (the MCP profile's too, if running)
	$(COMPOSE) --profile agent-mcp logs -f --tail=100

ps:  ## Show service status and health (the MCP profile's too, if running)
	$(COMPOSE) --profile agent-mcp ps

config:  ## Render the merged production config (what actually runs)
	$(COMPOSE) config

shell:  ## Shell in the API container
	$(COMPOSE) exec api sh

psql:  ## Interactive psql inside the database container
	$(COMPOSE) exec $(DB_SERVICE) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

# Encrypted, because the dump is every governance record, every audit entry
# and every retained version in one file. BACKUP_PASSPHRASE is required: a
# plaintext dump sitting in the working directory is 164.310(d)(2)(i) waiting
# to happen, and making encryption opt-in means it is off.
#
# Uses gpg --symmetric, which is present on far more machines than age. Set
# BACKUP_RETAIN to prune older dumps (default: keep everything).
#
# The passphrase is read from the ENVIRONMENT as $$BACKUP_PASSPHRASE, never
# expanded as $(BACKUP_PASSPHRASE): make pastes an expanded variable into the
# recipe text, which is then the argv of `sh -c`, readable by every local
# account. scripts/backup_crypto.sh hands it to gpg through a mode-600 file.
# Export it; do not write `make backup BACKUP_PASSPHRASE=...` (that is make's argv).
backup:  ## Encrypted pg_dump to backups/<timestamp>.sql.gz.gpg
	@test -n "$$BACKUP_PASSPHRASE" || { \
	  echo "BACKUP_PASSPHRASE is not set."; \
	  echo; \
	  echo "  The dump contains every record, audit entry and retained"; \
	  echo "  version. Writing it in the clear is not a backup policy."; \
	  echo; \
	  echo "  Generate one and keep it somewhere other than this machine:"; \
	  echo "    export BACKUP_PASSPHRASE=\"\$$(openssl rand -base64 32)\""; \
	  echo; \
	  echo "  make backup-plaintext PLAINTEXT=1   # dev databases only"; \
	  exit 1; }
	@mkdir -p $(BACKUP_DIR) && chmod 700 $(BACKUP_DIR)
	@OUT=$(BACKUP_DIR)/$$(date -u +%Y%m%dT%H%M%SZ).sql.gz.gpg; \
	 $(COMPOSE) exec -T $(DB_SERVICE) pg_dump -U $(POSTGRES_USER) -d $(POSTGRES_DB) --clean --if-exists \
	   | gzip \
	   | scripts/backup_crypto.sh encrypt "$$OUT" \
	 && chmod 600 "$$OUT" && ls -lh "$$OUT" \
	 || { rm -f "$$OUT"; echo "backup FAILED: no file was kept" >&2; exit 1; }
	@if [ -n "$(BACKUP_RETAIN)" ]; then \
	  ls -1t $(BACKUP_DIR)/*.sql.gz.gpg 2>/dev/null | tail -n +$$(($(BACKUP_RETAIN)+1)) \
	    | xargs -r rm -v; \
	fi
	@echo "Dumped through the running server. Do NOT back this up by copying the volume's files -- a live cluster gives you a torn snapshot."
	@echo "Keep the passphrase somewhere other than this machine. Without it this file is unrecoverable."

backup-plaintext:  ## UNENCRYPTED pg_dump. Throwaway databases only.
	@test -n "$(PLAINTEXT)" || { echo "refusing: pass PLAINTEXT=1 to confirm"; exit 1; }
	@mkdir -p $(BACKUP_DIR) && chmod 700 $(BACKUP_DIR)
	$(COMPOSE) exec -T $(DB_SERVICE) pg_dump -U $(POSTGRES_USER) -d $(POSTGRES_DB) --clean --if-exists \
	  | gzip > $(BACKUP_DIR)/$$(date -u +%Y%m%dT%H%M%SZ).sql.gz
	@echo "UNENCRYPTED dump written. Do not do this with real records."

# Handles both shapes, so an older plaintext dump still restores.
#
# It asks first, like `make prune`, because it overwrites the live database with a
# dump (--clean drops what is there). CONFIRM=YES skips the question for automation;
# it is a deliberate word, not a flag that is easy to pass by accident.
#
# A dump taken before a purge still holds what the purge destroyed, so a plain restore
# undid it (#116). The live database's purges are captured to a ledger first and
# re-applied after. If the live database cannot be read, it says so and goes on: the
# ledger can be rebuilt from the security log (docs/privacy.md).
PSQL_OWNER = $(COMPOSE) exec -T $(DB_SERVICE) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)
restore:  ## Restore a dump: make restore FILE=backups/....sql.gz.gpg  (DESTRUCTIVE)
	@test -n "$(FILE)" || { echo "usage: make restore FILE=backups/<file>.sql.gz.gpg"; exit 1; }
	@if [ "$(CONFIRM)" != YES ]; then \
	  printf 'This will OVERWRITE the live database with %s. Type YES to continue: ' "$(FILE)"; \
	  read ans && [ "$$ans" = YES ] || { echo; echo aborted; exit 1; }; \
	fi
	@ledger="$(BACKUP_DIR)/purge-ledger-$$(date -u +%Y%m%dT%H%M%SZ).json"; \
	if ! python3 scripts/purge_ledger.py --psql "$(PSQL_OWNER)" capture --out "$$ledger"; then \
	  ledger=""; \
	  echo "WARNING: could not read the purges from the live database, so purges made after this dump will NOT be re-applied. See docs/privacy.md." >&2; \
	fi; \
	case "$(FILE)" in \
	  *.gpg) test -n "$$BACKUP_PASSPHRASE" || { echo "BACKUP_PASSPHRASE is needed to read $(FILE)" >&2; exit 1; }; \
	         scripts/backup_crypto.sh decrypt "$(FILE)" ;; \
	  *)     cat "$(FILE)" ;; \
	esac | gunzip -c | $(PSQL_OWNER) || exit 1; \
	if [ -n "$$ledger" ]; then python3 scripts/purge_ledger.py --psql "$(PSQL_OWNER)" reapply "$$ledger"; fi
	@echo "A restore can bring back records disposed of since the dump. What is due now:"
	@python3 scripts/dispose.py --psql "$(PSQL_OWNER)" || echo "Could not report it (a dump from before 008_retention.sql?). Run make dispose once the migrations have run." >&2

# Re-apply purges from ledger files: one `make restore` wrote, or one rebuilt from the
# security log with `python3 scripts/purge_ledger.py from-log LOG --out LEDGER` (#116).
reapply-purges:  ## Re-apply purges after a restore: make reapply-purges LEDGER=backups/purge-ledger-....json
	@test -n "$(LEDGER)" || { echo "usage: make reapply-purges LEDGER=<ledger.json>"; exit 1; }
	@python3 scripts/purge_ledger.py --psql "$(PSQL_OWNER)" reapply $(LEDGER)

# Records past their retention period (#57, R-54, R-56). Reports by default; APPLY=1
# disposes of them (a tombstone stays) and records who ran it. Held projects are kept.
dispose:  ## Report records past their retention period: make dispose [APPLY=1 BY=<name>]
	@python3 scripts/dispose.py --psql "$(PSQL_OWNER)" $(if $(APPLY),--apply --by "$(BY)",)

# Agent tokens (#164): list them, or end them as the operator. The app has no
# administrator role, so this is an operator action, like dispose.
agent-tokens:  ## List agent tokens, or revoke: make agent-tokens [REVOKE=1 (TOKEN=<id> | WHO=<user> | ALL=1)]
	@python3 scripts/agent_tokens.py --psql "$(PSQL_OWNER)" $(if $(REVOKE),revoke $(if $(TOKEN),--token "$(TOKEN)",$(if $(WHO),--user "$(WHO)",$(if $(ALL),--everyone,))),list $(if $(WHO),--user "$(WHO)",))

# Where one person's identifier is stored, for a subject access request (#57).
subject-access:  ## Find where one person's identifier is stored: make subject-access WHO=a@b.org
	@test -n "$(WHO)" || { echo "usage: make subject-access WHO=<identifier>"; exit 1; }
	@python3 scripts/subject_access.py "$(WHO)"

# Look for a patient identifier pasted where it should never be (#66, R-50): SSNs and
# labeled MRNs, dates of birth and patient names, in the live records, the unpurged
# history and the audit log. Reports where, never what. STRICT=1 exits 1 on a match.
phi-scan:  ## Look for pasted patient identifiers (never prints them): make phi-scan [STRICT=1]
	@python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "phi-scan needs Python 3.11 or newer"; exit 2; }
	@python3 scripts/phi_scan.py $(if $(STRICT),--strict,)

# What the API image installs is exactly this file, verified by hash (#37). Regenerated
# in the SAME Python the image uses, so the pins are the ones that image will resolve.
# Review the diff: a changed hash is a changed dependency.
lock:  ## Regenerate server/requirements.txt (hash-pinned) from server/pyproject.toml
	docker run --rm -v "$(CURDIR)/server:/work" -w /work python:3.12-slim sh -c \
	  "pip install -q pip-tools==7.6.2 && pip-compile --quiet --generate-hashes --strip-extras --output-file=requirements.txt pyproject.toml && chown \$$(stat -c %u:%g pyproject.toml) requirements.txt"

# The optional MCP service's lock, the same way (#164).
lock-mcp:  ## Regenerate mcp/requirements.txt (hash-pinned) from mcp/pyproject.toml
	docker run --rm -v "$(CURDIR)/mcp:/work" -w /work python:3.12-slim sh -c \
	  "pip install -q pip-tools==7.6.2 && pip-compile --quiet --generate-hashes --strip-extras --output-file=requirements.txt pyproject.toml && chown \$$(stat -c %u:%g pyproject.toml) requirements.txt"

# A backup that has never been restored is a hypothesis (#52). This restores one into a
# throwaway PostgreSQL (same major version as production, no network) and checks the
# tables, the rows and the append-only triggers survived. Default: the newest dump.
verify-backup:  ## Restore the newest backup (or FILE=...) into a throwaway database and check it
	@BACKUP_DIR="$(BACKUP_DIR)" python3 scripts/verify_backup.py $(FILE)

# The logic is scripts/check_isolation.py, so it can be tested and so it exits
# non-zero on a failure. It used to be shell that printed what it found and ended
# step 3 with `|| true` (#56).
check-isolation:  ## Prove the API is not reachable except through the proxy
	@HTTP_PORT=$(HTTP_PORT) python3 scripts/check_isolation.py

prune:  ## Remove containers AND the database volume. Destroys all data.
	@printf 'This deletes the pgdata volume permanently. Type YES to continue: ' \
	  && read ans && [ "$$ans" = YES ] || { echo aborted; exit 1; }
	$(COMPOSE) --profile agent-mcp down -v
