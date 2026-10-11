-- 013_agent_tokens.sql -- per-user, short-lived, revocable tokens for a read-only
-- agent API (#164, R-71, D-89).
--
-- An agent has no browser session, so it cannot arrive through the front door's
-- single sign-on. The app mints a bearer token for a signed-in user. The token is
-- 256 bits of randomness, shown once at mint and kept only as a SHA-256 hash, valid
-- for exactly 8 hours, and accepted only on the read-only routes under
-- /api/agent/. It can never mint, list or revoke a token.
--
-- This migration does three things:
--
--   1. agent_token: the tokens. A token belongs to a principal and dies with it
--      (ON DELETE CASCADE): erasing the principal, which `make dispose` does when
--      nothing retained names the person (009), deletes their tokens too.
--   2. access_event gets `via` and `token_id`, so a read made through a token is
--      marked as agent access, with the token's id (never its secret).
--   3. access_event's action list gains the agent actions.
--
-- 001 to 012 are not edited. access_event is append-only (007): adding a column
-- with a constant default and replacing a CHECK touch no row and fire no trigger.

CREATE TABLE IF NOT EXISTS agent_token (
    -- The public half of the token: not a secret, safe to show and to log.
    token_id        text        PRIMARY KEY
        CONSTRAINT agent_token_id_shape CHECK (token_id ~ '^[0-9a-f]{16}$'),
    -- SHA-256, hex, of the whole token. The token is 256 random bits, so a fast
    -- hash is enough: there is nothing to guess from.
    secret_hash     text        NOT NULL
        CONSTRAINT agent_token_hash_shape CHECK (secret_hash ~ '^[0-9a-f]{64}$'),
    principal_id    text        NOT NULL
        REFERENCES principals (id) ON DELETE CASCADE,
    -- What the user called it, for their own list. Never in an agent response.
    label           text        NOT NULL DEFAULT ''
        CONSTRAINT agent_token_label_length CHECK (char_length(label) <= 64),
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    -- Who ended it early: the user through the API, or the operator's script.
    revoked_source  text,
    last_used_at    timestamptz,
    -- The lifetime is fixed, and the database says so: no code path, and no row an
    -- operator edits by mistake, can make a token last longer than 8 hours.
    CONSTRAINT agent_token_lifetime
        CHECK (expires_at = created_at + interval '8 hours'),
    CONSTRAINT agent_token_revoked_source_known
        CHECK (revoked_source IS NULL OR revoked_source IN ('user', 'operator')),
    CONSTRAINT agent_token_revocation_coherent
        CHECK ((revoked_at IS NULL) = (revoked_source IS NULL))
);

CREATE INDEX IF NOT EXISTS agent_token_principal_idx
    ON agent_token (principal_id, created_at DESC);

-- A token's identity never changes, and a revocation is not undone. Only
-- last_used_at moves freely, and revoked_at moves once, from null. The API role
-- holds UPDATE on this table, so the trigger is what stops a bug from rewriting a
-- token's owner or expiry, or reviving a revoked one. It does not fire on a DELETE,
-- so the cascade from principals still removes a person's tokens.
CREATE OR REPLACE FUNCTION agent_token_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.token_id IS DISTINCT FROM OLD.token_id
       OR NEW.secret_hash IS DISTINCT FROM OLD.secret_hash
       OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
       OR NEW.label IS DISTINCT FROM OLD.label
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
        RAISE EXCEPTION 'agent_token: only revocation and last use may change (id=%)',
            OLD.token_id USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL
       AND (NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
            OR NEW.revoked_source IS DISTINCT FROM OLD.revoked_source) THEN
        RAISE EXCEPTION 'agent_token: a revoked token stays revoked (id=%)',
            OLD.token_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS agent_token_no_rewrite ON agent_token;
CREATE TRIGGER agent_token_no_rewrite
    BEFORE UPDATE ON agent_token
    FOR EACH ROW EXECUTE FUNCTION agent_token_guard();

COMMENT ON TABLE agent_token IS
    'Per-user bearer tokens for the read-only agent API (#164). Hash only, 8 hours, '
    'revocable, deleted with the principal. The secret is shown once at mint.';

-- The read trail marks agent access.
ALTER TABLE access_event ADD COLUMN IF NOT EXISTS via text NOT NULL DEFAULT 'session';
ALTER TABLE access_event ADD COLUMN IF NOT EXISTS token_id text;

ALTER TABLE access_event DROP CONSTRAINT IF EXISTS access_event_via_known;
ALTER TABLE access_event ADD CONSTRAINT access_event_via_known
    CHECK (via IN ('session', 'agent'));

-- Only an agent call carries a token id (a refused call may carry none).
ALTER TABLE access_event DROP CONSTRAINT IF EXISTS access_event_token_only_via_agent;
ALTER TABLE access_event ADD CONSTRAINT access_event_token_only_via_agent
    CHECK (via = 'agent' OR token_id IS NULL);

ALTER TABLE access_event DROP CONSTRAINT IF EXISTS access_event_action_known;
ALTER TABLE access_event ADD CONSTRAINT access_event_action_known CHECK (
    action IN ('list', 'read_versions', 'read_version', 'read_log',
               'export', 'stream_attach',
               'agent_me', 'agent_portfolio', 'agent_project', 'agent_refused')
);

CREATE INDEX IF NOT EXISTS access_event_token_idx
    ON access_event (token_id, at DESC) WHERE token_id IS NOT NULL;

COMMENT ON COLUMN access_event.via IS
    'How the read arrived: session (the front door''s identity) or agent (a bearer '
    'token, #164).';
COMMENT ON COLUMN access_event.token_id IS
    'The agent token''s public id, never its secret. Null for a session read, and '
    'for an agent call whose token could not be read.';
