/* ============================================================
   App state
   ============================================================ */
/* Where this session's data lives. A closed set, so it is a frozen object and
   never a bare string: `MODE === "shared"` once sat next to `MODE = "api"` and
   was false forever, which told every server-backed user their work was "Saved
   in this browser" (#55). `Mode.APi` is undefined and a test fails; "apI" is
   just a different string and nothing does. */
const Mode = Object.freeze({
  CONNECTING: "connecting",  // booting; the store is not chosen yet
  LOCAL: "local",            // this browser only (localStorage)
  API: "api",                // the self-hosted server (PostgreSQL)
});
/* What the header says about each mode. Keyed by Mode, like SAVED_LABEL, so a
   new mode cannot ship without a label, and no two modes share one: a mode once
   carried the same label as the self-hosted server, which hid the difference between
   data inside a hospital's administrative boundary and data outside it (#64). */
/* The header's label for each mode, as a catalog key (the text is translated; the
   English text in MODE_LABEL below is what exports carry, so it stays stable). */
const MODE_LABEL_KEY = Object.freeze({
  [Mode.LOCAL]: "mode.local", [Mode.API]: "mode.api",
});
const MODE_LABEL = Object.freeze({
  [Mode.LOCAL]:    Object.freeze({text:"This browser only", cls:""}),
  [Mode.API]:      Object.freeze({text:"Shared workspace",  cls:"shared"}),
});
/* The data scope, stated in every storage mode (#34, R-49). The owner decided this
   tool holds governance metadata only, in any mode: there is no reason for a
   patient's data to be in a governance record, and organizational policy forbids
   it. It is a policy, not a detector, so the wording is an instruction, never a
   claim that no such data is present. */
const SCOPE_NOTICE = I18N_CATALOGS[Locale.EN]["safety.scope"];   // English: exports and tests read it
/* What an export says about where the record was kept, beside the header's label (#93).
   Keyed by Mode like MODE_LABEL, so a mode cannot ship without one and two modes cannot
   share one (R-04). It says where the record lived and what that means for sign-offs
   and audit. The data scope is the same in every mode (SCOPE_NOTICE, R-49), so
   nothing here implies one mode is fit for data another is not. */
const MODE_PROVENANCE = Object.freeze({
  [Mode.LOCAL]:    "Kept in one browser on one computer. Sign-offs here are self-asserted: nothing verifies who made them, and there is no server-side audit log or version history.",
  [Mode.API]:      "Kept on the self-hosted governance server, with server-side access control, a version history and an audit log. Sign-offs are recorded against the signed-in identity.",
});
/* The storage mode, as an export records it: the header's own label, a stable machine
   value, and the sentence above. */
/* The same, in the reader's language, for the reports a person reads (HTML, PDF,
   Markdown). storageNote() stays English: the JSON export is a machine contract. */
const MODE_PROVENANCE_KEY = Object.freeze({
  [Mode.LOCAL]: "provenance.local", [Mode.API]: "provenance.api",
});
function storageNoteShown(){
  return { label: MODE_LABEL_KEY[MODE] ? t(MODE_LABEL_KEY[MODE]) : t("provenance.unknownLabel"),
           note: t(MODE_PROVENANCE_KEY[MODE] || "provenance.unknown") };
}
function storageNote(){
  const l = MODE_LABEL[MODE];
  return { mode: MODE, label: l ? l.text : "Unknown",
           note: MODE_PROVENANCE[MODE] || "The storage mode was not known when this was produced." };
}
/* The export formats the dashboard can produce, as the server names them
   (server/app/accessaudit.py ExportFormat). Reported to it when one is produced. */
const ExportFormat = Object.freeze({
  MD: "md", HTML: "html", PDF: "pdf", JSON: "json", CSV: "csv",
});
/* `data-act` values for buttons. The older actions are still bare strings in
   70-events.js (baselined in scripts/enum_baseline.json); a NEW action goes here,
   so a typo is `Act.LOG_OLDR` -> undefined -> a failing test, not a comparison
   that is quietly false forever. */
const Act = Object.freeze({
  LOG_OLDER: "log-older",   // load a deeper page of the audit history
  UNLOCK: "unlock",         // leave the idle lock: reload, through the front door
  AGENT_OPEN: "agent-open", // the agent access page (#164)
});
let STORE=null, MODE=Mode.CONNECTING, RO=false;
const ME={id:null};
let PROJECTS=new Map(), LOADED=false;
let CUR=null;              // open project id
let S=null;                // working copy of open project
let LOG=[], unsubLog=null;
/* How many entries the project has in all, when the store says. LOG is a WINDOW
   onto the history (the newest page), never the whole of it, and an export or a
   view that renders it must say so: a PDF filed as the record of a two-year
   review used to show the newest 60 entries and nothing about the rest (#40).
   null means the store cannot tell. */
let LOG_TOTAL=null;
const openItems=new Set();
const pending={}, timers={}, flushing={};
let UI={view:"setup", project:null, filter:"all", q:""};
try{ UI=Object.assign(UI, JSON.parse(localStorage.getItem("chai-ui-v2"+BUILD_SUFFIX))||{}); }catch(e){}
function saveUI(){ try{ localStorage.setItem("chai-ui-v2"+BUILD_SUFFIX,JSON.stringify({view:UI.view,project:CUR,filter:UI.filter})); }catch(e){} }

/* names */
const NAMES={};
/* Ids a lookup could not name, so a render does not ask again for the same ghost. */
const UNNAMED=new Set();

/* What to show for a person: their name if known, "you" for the viewer, and
   otherwise what each mode can honestly say. The server-backed mode shows the id
   (ugly, but it is what a reviewer can match to a directory, and "someone" tells
   them nothing); the browser-only mode keeps "someone", since
   an id there is not something a person can use or should be shown (#39). */
function displayName(id){
  if(!id) return "someone";
  if(NAMES[id]) return NAMES[id];
  if(id===ME.id) return "you";
  return MODE===Mode.API ? id : "someone";
}

/* Where names come from: the server store's profiles(). */
function nameSource(){
  if(STORE && typeof STORE.profiles==="function") return STORE;
  return null;
}

/* Ask for the names of any ids not yet asked about, and remember the answers. */
async function primeNames(ids){
  const src = nameSource();
  const need=[...new Set((ids||[]).filter(i=>i && !(i in NAMES) && !UNNAMED.has(i)))];
  if(!need.length || !src) return;
  need.forEach(i=>UNNAMED.add(i));   // claimed up front, so concurrent renders do not repeat it
  try{
    const ps=await src.profiles(need);
    need.forEach(i=>{
      const p=ps[i];
      if(p){ UNNAMED.delete(i); NAMES[i]= p.isMe ? "you" : (p.name||p.email||""); if(!NAMES[i]) delete NAMES[i]; }
    });
  }catch(e){ /* a name is a convenience; the ids still show */ }
}

/* Every person a project document names: its access lists, who signed off and who
   last edited. The same set the server will agree to name (principals.ids_in_doc). */
function idsOfProject(p){
  const found=new Set(); if(!p) return [];
  const a=p.access||{};
  ["owners","writers","readers"].forEach(k=>(Array.isArray(a[k])?a[k]:[]).forEach(i=>found.add(i)));
  Object.values(p.gates||{}).forEach(g=>{ if(g && g.signedBy) found.add(g.signedBy); });
  ["updatedBy","cardUpdatedBy"].forEach(k=>{ if(p[k]) found.add(p[k]); });
  return [...found].filter(Boolean);
}
/* Fetch names for these ids, then refresh whatever is already on screen. */
function warmNames(ids){
  return primeNames(ids).then(()=>{ if(document.getElementById("main")) resolveNames(document); });
}

async function resolveNames(root){
  root=root||document;
  const els=[...root.querySelectorAll("[data-uid]")];
  const ids=[...new Set(els.map(e=>e.dataset.uid).filter(Boolean))];
  els.forEach(e=>{ if(!e.dataset.uid) e.textContent = t(MODE===Mode.LOCAL?"who.localYou":"who.someone"); });
  await primeNames(ids);
  els.forEach(e=>{ const i=e.dataset.uid; if(i) e.textContent = displayName(i); });
}
const who = id => `<bdi data-uid="${esc(id||"")}">${esc(displayName(id))}</bdi>`;
