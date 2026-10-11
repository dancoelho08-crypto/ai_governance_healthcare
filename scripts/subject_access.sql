-- Where one person's identifier appears, for a subject access request (#57).
-- Read-only. Run through scripts/subject_access.py, which passes :subject.
--
-- Exact columns match the identifier as a whole, ignoring case. The jsonb columns
-- match it as a substring of their text, so a match there is a place to look, not a
-- finding: an id that is a prefix of another will match both.
WITH s AS (
    SELECT :'subject'::text AS v,
           '%' || replace(replace(replace(:'subject'::text, '\', '\\'), '%', '\%'),
                          '_', '\_') || '%' AS pat
),
hit AS (
    SELECT 'projects.created_by' AS location, p.id AS project_id, NULL::text AS ref
      FROM projects p, s WHERE lower(p.created_by) = lower(s.v)
    UNION ALL
    SELECT 'projects.updated_by', p.id, NULL
      FROM projects p, s WHERE lower(p.updated_by) = lower(s.v)
    UNION ALL
    SELECT 'projects.doc', p.id, NULL
      FROM projects p, s WHERE p.doc::text ILIKE s.pat
    UNION ALL
    SELECT 'project_log.by_id', l.project_id, l.seq::text
      FROM project_log l, s WHERE lower(l.by_id) = lower(s.v)
    UNION ALL
    SELECT 'project_log.purged_by', l.project_id, l.seq::text
      FROM project_log l, s WHERE lower(l.purged_by) = lower(s.v)
    UNION ALL
    SELECT 'project_log.entry', l.project_id, l.seq::text
      FROM project_log l, s WHERE l.entry::text ILIKE s.pat
    UNION ALL
    SELECT 'project_version.changed_by', v.project_id, v.rev::text
      FROM project_version v, s WHERE lower(v.changed_by) = lower(s.v)
    UNION ALL
    SELECT 'project_version.purged_by', v.project_id, v.rev::text
      FROM project_version v, s WHERE lower(v.purged_by) = lower(s.v)
    UNION ALL
    SELECT 'project_version.doc', v.project_id, v.rev::text
      FROM project_version v, s WHERE v.doc::text ILIKE s.pat
    UNION ALL
    SELECT 'project_version.access', v.project_id, v.rev::text
      FROM project_version v, s WHERE v.access::text ILIKE s.pat
    UNION ALL
    SELECT 'project_deletion.deleted_by', d.project_id, d.incarnation::text
      FROM project_deletion d, s WHERE lower(d.deleted_by) = lower(s.v)
    UNION ALL
    SELECT 'access_event.actor', e.project_id, e.id::text
      FROM access_event e, s WHERE lower(e.actor) = lower(s.v)
    UNION ALL
    SELECT 'access_event.detail', e.project_id, e.id::text
      FROM access_event e, s WHERE e.detail::text ILIKE s.pat
    UNION ALL
    SELECT 'retention_hold.by_id', h.project_id, h.id::text
      FROM retention_hold h, s WHERE lower(h.by_id) = lower(s.v)
    UNION ALL
    SELECT 'retention_hold.reason', h.project_id, h.id::text
      FROM retention_hold h, s WHERE h.reason ILIKE s.pat
    UNION ALL
    SELECT 'disposal_run.run_by', NULL, r.id::text
      FROM disposal_run r, s WHERE lower(r.run_by) = lower(s.v)
    UNION ALL
    SELECT 'retention_policy.changed_by', NULL, 'policy'
      FROM retention_policy rp, s WHERE lower(rp.changed_by) = lower(s.v)
    UNION ALL
    SELECT 'retirement_rule_change.changed_by', NULL, rc.id::text
      FROM retirement_rule_change rc, s WHERE lower(rc.changed_by) = lower(s.v)
    UNION ALL
    SELECT 'agent_token.principal_id', NULL, t.token_id
      FROM agent_token t, s WHERE lower(t.principal_id) = lower(s.v)
    UNION ALL
    SELECT 'principals', NULL, pr.id
      FROM principals pr, s
     WHERE lower(pr.id) = lower(s.v) OR lower(pr.email) = lower(s.v)
)
SELECT jsonb_build_object(
    'subject', (SELECT v FROM s),
    'locations', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
                   'location', location,
                   'rows', n,
                   'projects', projects) ORDER BY location)
          FROM (SELECT location,
                       count(*) AS n,
                       COALESCE(jsonb_agg(DISTINCT project_id)
                                FILTER (WHERE project_id IS NOT NULL), '[]') AS projects
                  FROM hit GROUP BY location) g
    ), '[]'::jsonb),
    'principal', (
        SELECT jsonb_build_object('id', pr.id, 'name', pr.name, 'email', pr.email,
                                  'first_seen', pr.first_seen, 'last_seen', pr.last_seen)
          FROM principals pr, s
         WHERE lower(pr.id) = lower(s.v) OR lower(pr.email) = lower(s.v)
         LIMIT 1)
);
