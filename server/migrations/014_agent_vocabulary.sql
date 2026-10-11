-- 014_agent_vocabulary.sql -- the words an agent may be shown (#164, D-89).
--
-- A stored project record is opaque JSON the browser owns, so its item ids, checkpoint
-- ids, statuses and decisions can hold anything a writer typed, a name included. The
-- agent API returns such a key or value only when it is a word of the build's
-- framework definitions. The server image is framework-neutral (D-76), so the words
-- travel the way the retirement rules do: scripts/build_manifest.py writes them into
-- manifest.json, and the migrate job (or an API with RUN_MIGRATIONS=true and a
-- manifest) loads them here, replacing the table's rows wholesale on every run.
--
-- It decides only what an agent may see, never disposal, so it keeps no history and
-- needs no acknowledgment. Only the owner writes it; the API role may only read it.
--
-- kind 'framework' lists a framework id, its value being its role in the build.

CREATE TABLE IF NOT EXISTS agent_vocabulary (
    framework_id text NOT NULL,
    kind         text NOT NULL,
    value        text NOT NULL,
    PRIMARY KEY (framework_id, kind, value),
    CONSTRAINT agent_vocabulary_kind_known CHECK (
        kind IN ('framework', 'items', 'gates', 'statuses', 'decisions')
    ),
    CONSTRAINT agent_vocabulary_role_known CHECK (
        kind <> 'framework' OR value IN ('primary', 'supplement')
    )
);

COMMENT ON TABLE agent_vocabulary IS
    'The framework words an agent may be shown, loaded from the build''s manifest '
    'by the migrate job (D-89). Replaced wholesale; the API only reads it.';
