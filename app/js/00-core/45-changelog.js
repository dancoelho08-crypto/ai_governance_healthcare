/* ============================================================
   Changelog
   What changed, who changed it, when, and what the record hashed to
   afterwards.

   The audit log already existed, but it recorded prose: "Archived",
   "Project created". That answers "something happened" and not "what
   is different now", which is the question a reviewer asks six
   months later when a checkpoint decision is challenged.

   So every edit is described in the terms the user sees -- the
   criterion's own text, the checkpoint's title, the model-card
   field's label -- rather than as a state path. A reader should not
   have to know that `gates.B.decision` is Checkpoint B.

   Entries are written through the store's existing log, which means
   this works in all three backends rather than only the one with a
   database. The server additionally keeps full snapshots; see
   server/migrations/002_versions.sql.
   ============================================================ */

/* Human labels for state paths. Anything not matched here falls back
   to a cleaned-up path, so a new field still logs something useful
   rather than nothing. */
function describePath(path) {
  const parts = String(path).split(".");

  // A framework's own keys (CHAI's items, gates, card and metrics; OPTICA's
  // answers) are described by that framework (#168).
  const own = frameworkDescribePath(parts);
  if (own) return own;

  if (parts[0] === "meta") {
    const labels = { solution: "solution name", org: "organization", developer: "developer",
      sourcing: "sourcing", sponsor: "clinical sponsor", riskTier: "risk tier",
      reviewCadence: "review cadence", startDate: "review start date",
      reviewers: "review team", scope: "scope" };
    return labels[parts[1]] || parts[1];
  }

  if (parts[0] === "access") return "who has access";
  if (parts[0] === "archived") return "archived state";
  return parts.join(" › ");
}

/* Values as a reader would recognize them. Statuses get their label,
   long text is elided rather than dumped into a log line. */
function describeValue(path, value) {
  if (value === undefined || value === null || value === "") return "empty";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (typeof value === "object" && /\.refs\.[^.]+$/.test(path)) {
    const label = String(value.title || (value.file && value.file.name) || value.url || "").slice(0, 60);
    return `“${label}”${value.url ? ` ${value.url}` : ""}${value.file && value.file.sha256 ? ` (SHA-256 ${value.file.sha256})` : ""}`;
  }
  if (typeof value === "object") return "updated";

  const text = String(value);
  if (/\.status$/.test(path)) {
    return frameworkStatusName(path, text) || text;
  }
  return text.length > 60 ? `“${text.slice(0, 57)}…”` : `“${text}”`;
}

/* One log entry per edit, carrying enough to reconstruct what moved.
   `from` and `to` are kept as well as the prose, so a later version of
   this tool can render a better diff from old entries. */
function logChange(pid, path, from, to, doc) {
  if (RO) return;
  // A record stored before credentials were removed on entry (R-70) can still hold
  // some; the history must not copy them. A copy, so the record is not touched.
  from = scrubAddressCredentials(from && typeof from === "object" ? clone(from) : from).value;
  to = scrubAddressCredentials(to && typeof to === "object" ? clone(to) : to).value;
  const same = JSON.stringify(from ?? null) === JSON.stringify(to ?? null);
  if (same) return;   // a save that changed nothing is not a change

  const entry = {
    at: new Date().toISOString(),
    by: ME.id || null,
    text: `Changed ${describePath(path)}: ${describeValue(path, from)} → ${describeValue(path, to)}`,
    change: {
      path,
      from: from === undefined ? null : from,
      to: to === undefined ? null : to,
    },
  };
  if (doc) entry.hash = contentHash(doc);
  // The shared queue retries a transient failure and says so when one cannot be
  // written (see enqueueLog). Not `.catch(() => {})`: that loses the entry and
  // leaves a history that looks complete (#45).
  enqueueLog(pid, entry);
}

/* Compare two whole documents and list what differs, for the version
   history where only snapshots are available. Returns leaf-level
   paths, which is the granularity a reviewer wants: "the decision
   changed", not "the gates object changed". */
function diffDocs(before, after, prefix = "", out = []) {
  const a = before && typeof before === "object" ? before : {};
  const b = after && typeof after === "object" ? after : {};
  for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
    if (CANON_SKIP.has(key)) continue;
    const path = prefix ? `${prefix}.${key}` : key;
    const av = a[key], bv = b[key];
    const bothObjects = av && bv && typeof av === "object" && typeof bv === "object"
      && !Array.isArray(av) && !Array.isArray(bv);
    if (bothObjects) diffDocs(av, bv, path, out);
    else if (JSON.stringify(av ?? null) !== JSON.stringify(bv ?? null)) {
      out.push({ path, from: av ?? null, to: bv ?? null });
    }
  }
  return out;
}

/* LOG is the newest page of the history, not the history. Say so wherever it is
   shown or exported, so a view of 60 entries is never taken for all of them (#40).
   Empty when LOG is the whole of it. */
const LOG_PAGE = 60;
function logWindowNote(){
  if(LOG_TOTAL!==null && LOG_TOTAL>LOG.length) return `Showing the newest ${LOG.length} of ${LOG_TOTAL} entries.`;
  if(LOG_TOTAL===null && LOG.length>=LOG_PAGE) return `Showing the newest ${LOG.length} entries; older entries may exist.`;
  return "";
}
