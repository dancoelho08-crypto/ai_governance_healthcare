/* ============================================================
   Evidence references

   A reference points at evidence that lives somewhere else: a link, and
   optionally a file that is fingerprinted in this browser. The file is never
   uploaded and its bytes are never stored; only its name, size and SHA-256 are.
   That is the point (R-61): the record can say "this is the document we relied
   on, and here is how to tell whether it changed" without this tool holding
   a document that may name a patient.

   Stored at <holder>.refs, an object keyed by reference id, so two people who
   each add a reference at the same time both keep theirs (arrays replace
   wholesale on merge) and a removal is a null at one key.
   ============================================================ */
const REF_MAX_URL = 2000;
const REF_MAX_TITLE = 200;
const REF_MAX_PER_HOLDER = 50;
const REF_MAX_FILE_BYTES = 256 * 1024 * 1024;
const REF_URL_SCHEMES = Object.freeze(new Set(["http:", "https:"]));
const REF_ID = /^r[a-z0-9]{6,24}$/;
/* encodeURIComponent leaves ( and ) alone, which is the problem here. */
const REF_MD_ESCAPE = Object.freeze({ "<": "%3C", ">": "%3E", "(": "%28", ")": "%29" });
const SHA256_HEX = /^[0-9a-f]{64}$/;

/* The only way a person's text becomes a link. http and https, no credentials
   in the address, no whitespace or control characters, bounded. Anything else
   (javascript:, data:, file:, a relative path) is refused, not repaired. */
function safeUrl(raw){
  const s = String(raw ?? "").trim();
  if(!s || s.length > REF_MAX_URL || /[\s\u0000-\u001f\u007f]/.test(s)) return "";
  let u;
  try{ u = new URL(s); }catch(e){ return ""; }
  if(!REF_URL_SCHEMES.has(u.protocol) || u.username || u.password || !u.hostname) return "";
  return u.href;
}

/* ---- Credentials in an address (R-70, D-88) ------------------------------
   A Markdown or GitHub-style renderer turns a bare https://user:pass@host/ in a
   value into a link, so a password typed into any field would be printed in the
   report and offered as a click. safeUrl() above refuses such an address as a
   reference; this removes the credentials from an address wherever text is
   typed, pasted, imported or written to the Markdown report, and leaves the rest.

   What counts: the userinfo ("user:pass@" or "user@") of an address that has a
   scheme and "://", whatever the scheme (a renderer links http, https and ftp
   bare, and any scheme in angle brackets), and of a protocol-relative "//". The
   userinfo runs to the LAST "@" before the first "/", "?" or "#", as in the URL
   standard, so https://host/path?email=a@b.c keeps its "@" and
   https://a@b@host/ loses both. Removed even when nothing follows the "@": a
   person typing it one character at a time has not typed the host yet.
   Not credentials: user:pass@host with no scheme (no renderer links it) and an
   email address. The URL parser is the test's oracle, not a dependency: it
   refuses a half-typed address that this must still clean. */
const AddrRule = Object.freeze({ SCHEME: "scheme", RELATIVE: "relative" });
const ADDR_SCHEME = "[A-Za-z][A-Za-z0-9+.\\-]{0,31}";
const ADDR_USERINFO = "[^\\s/?#<>]*@";
const ADDR_RULES = Object.freeze([
  Object.freeze({ rule: AddrRule.SCHEME, re: new RegExp(`(${ADDR_SCHEME}://)${ADDR_USERINFO}`, "g") }),
  Object.freeze({ rule: AddrRule.RELATIVE, re: new RegExp(`(^|[^:/\\w])(//)${ADDR_USERINFO}`, "g") }),
]);

/* The text without the credentials of any address in it: {text, removed}, where
   removed counts addresses cleaned. Pure, and idempotent: the userinfo runs to the
   last "@", so cutting it cannot leave another for a second pass to find. */
function stripAddressCredentials(text){
  let out = String(text ?? "");
  let removed = 0;
  for(const {rule, re} of ADDR_RULES){
    out = out.replace(re, (m, a, b) => {
      removed++;
      switch(rule){
        case AddrRule.SCHEME: return a;
        case AddrRule.RELATIVE: return a + b;
        default: return assertNever(rule);
      }
    });
  }
  return {text: out, removed};
}

/* The same for every string inside a value, in place (a record, a reference, an
   imported file): {value, removed}. Keys are not text and are left alone. */
function scrubAddressCredentials(v, depth = 0){
  if(typeof v === "string"){ const r = stripAddressCredentials(v); return {value: r.text, removed: r.removed}; }
  if(!v || typeof v !== "object" || depth > 64) return {value: v, removed: 0};
  let removed = 0;
  for(const k of Object.keys(v)){
    const r = scrubAddressCredentials(v[k], depth + 1);
    if(r.removed){ v[k] = r.value; removed += r.removed; }
  }
  return {value: v, removed};
}

const newRefId = () => "r" + Date.now().toString(36).slice(-6) + Math.random().toString(36).slice(2, 8);

/* Whatever is stored, as a clean list: unknown or malformed entries are dropped
   and every field is coerced, so a poisoned record cannot reach markup by way
   of a field this code did not expect. */
function refList(holder){
  const refs = holder && isObj(holder.refs) ? holder.refs : {};
  const out = [];
  for(const id of Object.keys(refs)){
    const r = refs[id];
    if(!REF_ID.test(id) || !isObj(r)) continue;
    const f = isObj(r.file) && SHA256_HEX.test(String(r.file.sha256 || "")) ? {
      name: String(r.file.name ?? "").slice(0, 255),
      size: Number.isFinite(r.file.size) && r.file.size >= 0 ? r.file.size : 0,
      sha256: r.file.sha256,
    } : null;
    out.push({
      id,
      title: String(r.title ?? "").slice(0, REF_MAX_TITLE),
      url: safeUrl(r.url),
      date: /^\d{4}-\d{2}-\d{2}$/.test(String(r.date ?? "")) ? r.date : "",
      at: typeof r.at === "string" ? r.at.slice(0, 40) : "",
      file: f,
    });
  }
  return out.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : a.id < b.id ? -1 : 1));
}

function refLabel(r){ return r.title || (r.file && r.file.name) || r.url; }

function fmtBytes(n){
  if(n < 1024) return `${n} B`;
  if(n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

/* A file's SHA-256, read here and nowhere else. Web Crypto where the page
   has it (fast, and not available on plain http), the page's own SHA-256
   otherwise, so the answer does not depend on how the page was opened. */
async function hashFile(file){
  const bytes = new Uint8Array(await file.arrayBuffer());
  if(globalThis.crypto && crypto.subtle){
    try{
      const d = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
      return Array.from(d, b => b.toString(16).padStart(2, "0")).join("");
    }catch(e){ /* fall through to the page's own implementation */ }
  }
  return sha256Bytes(bytes);
}

/* The block shown under an item's other fields. `path` is where the holder's
   refs live ("items.s4-1"); it becomes data attributes, escaped. */
function refsHTML(path, holder){
  const list = refList(holder);
  const items = list.map(r => {
    const label = r.url
      ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer nofollow">${bdi(refLabel(r))}</a> <span class="ref-url">${bdi(r.url)}</span>`  // url-ok: refList() passes every address through safeUrl()
      : bdi(refLabel(r));
    const file = r.file
      ? `<span class="ref-file">${esc(t("refs.file"))}: ${bdi(r.file.name)}, ${esc(fmtBytes(r.file.size))}, SHA-256 <code>${esc(r.file.sha256)}</code></span>`
      : "";
    const date = r.date ? `<span class="ref-date">${esc(fmtDay(r.date))}</span>` : "";
    const verify = r.file ? `<button class="icon-btn ro-hide" data-verifyref="${esc(r.id)}" data-refpath="${esc(path)}">${esc(t("refs.verify"))}</button>` : "";
    return `<li data-ref="${esc(r.id)}">${label}${date}${file}${verify}<button class="icon-btn ro-hide" data-delref="${esc(r.id)}" data-refpath="${esc(path)}" aria-label="${esc(t("refs.removeLabel", {title: refLabel(r)}))}">${esc(t("refs.remove"))}</button></li>`;
  }).join("");
  const full = list.length >= REF_MAX_PER_HOLDER;
  return `<div class="wide refs" data-refs="${esc(path)}">
    <span class="refs-h">${esc(t("refs.title"))}</span>
    ${list.length ? `<ul class="refs-list">${items}</ul>` : `<p class="refs-none">${esc(t("refs.none"))}</p>`}
    <div class="refs-add ro-hide">
      <input type="text" data-refin="title" maxlength="${esc(REF_MAX_TITLE)}" placeholder="${esc(t("refs.titlePh"))}" aria-label="${esc(t("refs.titleLabel"))}">
      <input type="url" data-refin="url" maxlength="${esc(REF_MAX_URL)}" placeholder="https://" aria-label="${esc(t("refs.urlLabel"))}">
      <input type="date" data-refin="date" aria-label="${esc(t("refs.dateLabel"))}">
      <input type="file" data-refin="file" aria-label="${esc(t("refs.fileLabel"))}">
      <button class="btn" data-addref="${esc(path)}"${full ? " disabled" : ""}>${esc(t("refs.add"))}</button>
    </div>
    <p class="refs-hint ro-hide">${esc(t("refs.hint"))}</p>
  </div>`;
}

/* Add the reference typed into the block at `path`. Returns without a write
   (and says why) rather than saving something half-valid. */
async function addRef(path, box){
  const val = n => { const el = box.querySelector(`[data-refin="${n}"]`); return el ? el.value : ""; };  // xss-ok: a selector built from a fixed field name, never markup
  const fileEl = box.querySelector('[data-refin="file"]');
  const file = fileEl && fileEl.files && fileEl.files[0];
  const rawUrl = val("url").trim();
  const url = safeUrl(rawUrl);
  if(rawUrl && !url){ toast(t("refs.badUrl")); return; }
  if(!url && !file){ toast(t("refs.needOne")); return; }
  if(file && file.size > REF_MAX_FILE_BYTES){ toast(t("refs.tooBig", {mb: REF_MAX_FILE_BYTES / 1048576})); return; }
  if(refList(get(path)).length >= REF_MAX_PER_HOLDER){ toast(t("refs.full")); return; }
  let fp = null;
  if(file){
    try{ fp = {name: file.name.slice(0, 255), size: file.size, sha256: await hashFile(file)}; }
    catch(e){ toast(t("refs.unreadable")); return; }
  }
  const ref = {title: val("title").trim().slice(0, REF_MAX_TITLE), url, date: val("date"), at: new Date().toISOString(), file: fp};
  const id = newRefId();
  edit(`${path}.refs.${id}`, ref);
  renderMain(false);
}

function removeRef(path, id){
  if(!REF_ID.test(id)) return;
  edit(`${path}.refs.${id}`, null);
  renderMain(false);
}

/* Compare a file a person picks now with the fingerprint on record. Nothing
   is changed; the answer is a message. */
async function verifyRef(path, id, file){
  const r = refList(get(path)).find(x => x.id === id);
  if(!r || !r.file || !file) return;
  const now = await hashFile(file);
  toast(t(now === r.file.sha256 ? "refs.match" : "refs.mismatch"));
}

/* In a report: the same references, read-only. The address is printed as
   text beside the link, so a reader sees where a click goes. */
function refsReportHTML(holder){
  const list = refList(holder);
  if(!list.length) return "";
  return `<ul class="refs-list">${list.map(r => `<li>${r.url
    ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer nofollow">${bdi(refLabel(r))}</a> (${bdi(r.url)})`  // url-ok: refList() passes every address through safeUrl()
    : bdi(refLabel(r))}${r.date ? ` ${esc(fmtDay(r.date))}` : ""}${r.file
    ? ` <span class="ref-file">${bdi(r.file.name)}, ${esc(fmtBytes(r.file.size))}, SHA-256 <code>${esc(r.file.sha256)}</code></span>` : ""}</li>`).join("")}</ul>`;
}

/* In Markdown: a link only for a safe address, with its parentheses encoded so
   it cannot end the link early (and no angle brackets, which a reader of the
   file would take for raw HTML), and the address printed after it. */
function refsMarkdown(holder, line){
  return refList(holder).map(r => {
    const label = line(refLabel(r));
    const link = r.url ? `[${label}](${r.url.replace(/[<>()]/g, c => REF_MD_ESCAPE[c])}) ${line(r.url)}` : label;
    const file = r.file ? ` (${line(r.file.name)}, ${fmtBytes(r.file.size)}, SHA-256 ${r.file.sha256})` : "";
    return `${link}${r.date ? ` ${r.date}` : ""}${file}`;
  });
}

/* In JSON: plain data, no ids, so two exports of the same evidence compare. */
const refsData = holder => refList(holder).map(r => ({title: r.title, url: r.url || null, date: r.date || null, file: r.file}));
