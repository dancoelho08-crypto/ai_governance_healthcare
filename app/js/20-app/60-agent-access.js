/* ============================================================
   Agent access (#164, R-71, D-89, R-72)

   Where a signed-in person creates, sees and revokes their own agent tokens: a
   bearer token a program they run can use to READ what their dashboard shows
   (docs/agent-api.md). API mode only: a browser-only copy has no server to mint
   anything, so the page is not offered there.

   The token is the only secret on this page, and its whole life in the browser is:

     POST /api/agent-tokens -> AGENT_SECRET (one variable) -> the text of one element
     -> the person copies it -> "I have copied it" (or leaving, or a language change,
     or closing the page) sets the variable to null and removes the element.

   It is never written to storage, the address, the history or LOG, a toast, the
   console, `pending`, PROJECTS or STORE; never put in markup (textContent only);
   never in a live region (a screen reader would read it aloud to the room). The list
   of tokens holds public ids and labels only, read through an allowlist, so a
   server that sent a secret there would not get it shown or kept either.

   What a person typed (the label) and what the server said are text, always.
   ============================================================ */

/* The three words of a token's state, as the server names them (agent.py TokenState). */
const AgentState = Object.freeze({ ACTIVE: "active", EXPIRED: "expired", REVOKED: "revoked" });
/* Where loading the list has got to, and what the page can therefore offer. */
const AgentLoad = Object.freeze({ IDLE: "idle", LOADING: "loading", READY: "ready", OFF: "off", FAILED: "failed" });
/* What the page was doing when a request failed: the same status means different things. */
const AgentOp = Object.freeze({ LOAD: "load", MINT: "mint", REVOKE: "revoke" });
/* Why a request failed, each with the sentence the person reads. */
const AgentFailure = Object.freeze({
  OFF: "off", RATE: "rate", DENIED: "denied", CAP: "cap", REFUSED: "refused",
  SERVER: "server", NETWORK: "network", SHAPE: "shape", GONE: "gone",
});
const AGENT_FAILURE_KEY = Object.freeze({
  [AgentFailure.OFF]: "agent.off.detail", [AgentFailure.RATE]: "agent.err.rate",
  [AgentFailure.DENIED]: "agent.err.denied", [AgentFailure.CAP]: "agent.err.cap",
  [AgentFailure.REFUSED]: "agent.err.refusedBare", [AgentFailure.SERVER]: "agent.err.server",
  [AgentFailure.NETWORK]: "agent.err.network", [AgentFailure.SHAPE]: "agent.err.shape",
  [AgentFailure.GONE]: "agent.err.gone",
});
/* The page's own elements, by id. */
const AgentEl = Object.freeze({
  PAGE: "agentPage", TITLE: "agentTitle", ERR: "agentErr", STATUS: "agentStatus",
  OFF: "agentOff", MINT: "agentMint", FORM: "agentForm", LABEL: "agentLabel",
  CREATE: "agentCreate", REVEAL: "agentReveal", REVEAL_TITLE: "agentRevealTitle",
  SECRET: "agentSecret", COPY: "agentCopy", DONE: "agentDone",
  TOKENS: "agentTokens", COUNT: "agentCount", LIST: "agentList", CONFIRM: "agentConfirm",
});

const AGENT_LABEL_MAX = 64;   // the server's cap is authoritative (agent_tokens.LABEL_MAX_LENGTH)
const AGENT_TOKEN_SHAPE = /^agt_[0-9a-f]{16}\.[A-Za-z0-9_-]{43}$/;   // agent_tokens._TOKEN_SHAPE
const AGENT_ID_SHAPE = /^[0-9a-f]{16}$/;
const AGENT_DOCS_URL = "https://tonyreina.github.io/ai_governance_healthcare/agent-api/";
const AGENT_PATH = "/agent-tokens";

/* The only place a token lives. See the header. */
let AGENT_SECRET = null;
let AGENT = { load: AgentLoad.IDLE, tokens: [], busy: false };
let AGENT_DIALOG_CLOSE = null;

function agentPageShown(){ return !!document.getElementById(AgentEl.PAGE); }

/* Forget the token: the variable and every node that showed it. Safe to call anywhere,
   any number of times. */
function dropAgentSecret(){
  AGENT_SECRET = null;
  const code = document.getElementById(AgentEl.SECRET);
  if(code) code.textContent = "";
  const panel = document.getElementById(AgentEl.REVEAL);
  if(panel) panel.remove();
}
/* Leaving the page by any route (the portfolio, a project, a failure screen, the page
   closing, a language change that draws it again): the token goes with it. */
function agentLeave(){
  dropAgentSecret();
  if(AGENT_DIALOG_CLOSE) AGENT_DIALOG_CLOSE(false);
}
addEventListener("pagehide", agentLeave);

function agentEl(tag, cls, text){
  const e = document.createElement(tag);
  if(cls) e.className = cls;
  if(text != null) e.textContent = text;   // text, never markup
  return e;
}
const agentById = id => document.getElementById(id);

/* A time for a person, in their language: the date, then the minutes (a token lives
   8 hours, so the day alone is not enough). */
function agentWhen(iso){
  const d = new Date(iso);
  if(!iso || isNaN(d)) return "";
  return new Intl.DateTimeFormat(intlTag(), {dateStyle: "medium", timeStyle: "short"}).format(d);
}

/* What the list says about a token now: the server's word, moved on if the clock has
   passed the expiry while the page was open. */
function agentStateOf(tok, now){
  if(tok.revoked_at) return AgentState.REVOKED;
  if(tok.state === AgentState.REVOKED) return AgentState.REVOKED;
  if(tok.state === AgentState.EXPIRED) return AgentState.EXPIRED;
  const end = new Date(tok.expires_at);
  return !isNaN(end) && end <= now ? AgentState.EXPIRED : AgentState.ACTIVE;
}
const AGENT_STATE_KEY = Object.freeze({
  [AgentState.ACTIVE]: "agent.state.active", [AgentState.EXPIRED]: "agent.state.expired",
  [AgentState.REVOKED]: "agent.state.revoked",
});

/* A token row, from an allowlist of fields. Nothing else the server sent is kept. */
function agentCleanRow(r){
  if(!isObj(r) || typeof r.id !== "string" || !AGENT_ID_SHAPE.test(r.id)) return null;
  const s = v => (typeof v === "string" ? v : "");
  return {
    id: r.id, label: s(r.label).slice(0, AGENT_LABEL_MAX), created_at: s(r.created_at),
    expires_at: s(r.expires_at), revoked_at: s(r.revoked_at), last_used_at: s(r.last_used_at),
    state: Object.values(AgentState).includes(r.state) ? r.state : AgentState.ACTIVE,
  };
}

function agentFailureOf(err, op){
  const st = err && err.status;
  if(!st) return err && err.outcome === SaveOutcome.RETRY ? AgentFailure.NETWORK : AgentFailure.SHAPE;
  if(st === HttpStatus.NOT_FOUND) return op === AgentOp.REVOKE ? AgentFailure.GONE : AgentFailure.OFF;
  if(st === HttpStatus.UNAUTHORIZED || st === HttpStatus.FORBIDDEN) return AgentFailure.DENIED;
  if(st === HttpStatus.TOO_MANY) return AgentFailure.RATE;
  if(st === HttpStatus.CONFLICT && op === AgentOp.MINT) return AgentFailure.CAP;
  if(classifyStatus(st) === SaveOutcome.REFUSED) return AgentFailure.REFUSED;
  return AgentFailure.SERVER;
}
function agentSay(failure, detail){
  const box = agentById(AgentEl.ERR); if(!box) return;
  box.textContent = failure === AgentFailure.REFUSED && detail
    ? t("agent.err.refused", {detail}) : t(AGENT_FAILURE_KEY[failure]);
}
function agentClearError(){ const box = agentById(AgentEl.ERR); if(box) box.textContent = ""; }
/* A polite announcement. Never the token. */
function agentAnnounce(text){ const s = agentById(AgentEl.STATUS); if(s) s.textContent = text; }

function openAgentPage(){
  if(MODE !== Mode.API) return;   // no server, no tokens: the page is not offered
  flushAllChanges();
  agentLeave();
  AGENT = { load: AgentLoad.IDLE, tokens: [], busy: false };   // nothing stale from the last visit
  document.body.classList.add("home");
  renderAgentPage(true);
  loadAgentTokens();
}

function renderAgentPage(focusTop){
  agentLeave();
  document.getElementById("projName").textContent = t("agent.title");
  const m = document.getElementById("main");
  const html = `<div id="agentPage" class="agent-page">
    <p class="eyebrow">${esc(t("agent.eyebrow"))}</p>
    <h1 id="agentTitle" tabindex="-1">${esc(t("agent.title"))}</h1>
    <p class="lede">${esc(t("agent.lede"))}</p>
    <section class="agent-card" aria-labelledby="agentCanTitle">
      <h2 id="agentCanTitle">${esc(t("agent.can.title"))}</h2>
      <ul>
        <li>${esc(t("agent.can.read"))}</li>
        <li>${esc(t("agent.can.same"))}</li>
        <li>${esc(t("agent.can.values"))}</li>
        <li>${esc(t("agent.can.life"))}</li>
        <li>${esc(t("agent.can.noTokens"))}</li>
      </ul>
      <p class="agent-warn" dir="auto">${esc(t("agent.storeWarning"))}</p>
      <p><a id="agentDocs" target="_blank" rel="noopener noreferrer">${esc(t("agent.docs"))}</a></p>
    </section>
    <div id="agentErr" class="agent-err" role="alert"></div>
    <div id="agentStatus" class="vh" role="status" aria-live="polite"></div>
    <section id="agentOff" class="agent-card" hidden>
      <h2>${esc(t("agent.off.title"))}</h2>
      <p>${esc(t("agent.off.detail"))}</p>
    </section>
    <section id="agentMint" class="agent-card" aria-labelledby="agentMintTitle" hidden>
      <h2 id="agentMintTitle">${esc(t("agent.create.title"))}</h2>
      <form id="agentForm" class="agent-form">
        <div class="field">
          <label for="agentLabel">${esc(t("agent.label"))}</label>
          <span class="hint" id="agentLabelHint">${esc(t("agent.labelHint", {max: AGENT_LABEL_MAX}))}</span>
          <input type="text" id="agentLabel" autocomplete="off"
                 spellcheck="false" aria-describedby="agentLabelHint">
        </div>
        <button class="btn primary" type="submit" id="agentCreate">${esc(t("agent.create"))}</button>
      </form>
      <div id="agentRevealHost"></div>
    </section>
    <section id="agentTokens" class="agent-card" aria-labelledby="agentListTitle" hidden>
      <h2 id="agentListTitle">${esc(t("agent.list.title"))}</h2>
      <p class="small" id="agentCount"></p>
      <div id="agentList"></div>
    </section>
    <p><button class="btn ghost" type="button" data-home="1">${esc(t("pager.home"))}</button></p>
  </div>`;
  m.innerHTML = html;   // xss-ok: every interpolation above is t() through esc() and no value is a person's or the server's; the secret is never in it
  agentById(AgentEl.LABEL).maxLength = AGENT_LABEL_MAX;
  agentById("agentDocs").href = AGENT_DOCS_URL;   // url-ok: a constant address
  agentById(AgentEl.FORM).addEventListener("submit", e => { e.preventDefault(); mintAgentToken(); });
  paintAgentPage();
  if(focusTop){ window.scrollTo({top: 0}); agentById(AgentEl.TITLE).focus({preventScroll: true}); }
}

/* Show what the load state allows: the form and the list when the server has the
   feature, one explanation when it does not. */
function paintAgentPage(){
  const off = AGENT.load === AgentLoad.OFF;
  const ready = AGENT.load === AgentLoad.READY;
  const set = (id, hide) => { const e = agentById(id); if(e) e.hidden = hide; };
  set(AgentEl.OFF, !off);
  set(AgentEl.MINT, off || AGENT.load === AgentLoad.IDLE);
  set(AgentEl.TOKENS, off || AGENT.load === AgentLoad.IDLE);
  const create = agentById(AgentEl.CREATE);
  if(create){ create.disabled = AGENT.busy; create.textContent = t(AGENT.busy ? "agent.creating" : "agent.create"); }
  paintAgentList(ready);
}

function paintAgentList(ready){
  const host = agentById(AgentEl.LIST), count = agentById(AgentEl.COUNT);
  if(!host || !count) return;
  host.textContent = "";
  if(AGENT.load === AgentLoad.LOADING){ count.textContent = t("agent.list.loading"); return; }
  if(AGENT.load === AgentLoad.FAILED){
    count.textContent = "";
    const retry = agentEl("button", "btn", t("agent.retry"));
    retry.type = "button"; retry.addEventListener("click", () => loadAgentTokens());
    host.appendChild(retry); return;
  }
  if(!ready) return;
  const now = new Date();
  const rows = AGENT.tokens;
  const live = rows.filter(r => agentStateOf(r, now) === AgentState.ACTIVE).length;
  count.textContent = rows.length ? t("agent.live", {count: live}) : t("agent.list.empty");
  if(!rows.length) return;
  const ul = agentEl("ul", "agent-tokens");
  rows.forEach(r => {
    const state = agentStateOf(r, now);
    const li = agentEl("li", `agent-token ${state}`);
    const head = agentEl("div", "agent-token-head");
    const name = agentEl("strong", "agent-token-label", r.label || t("agent.noLabel"));
    name.dir = "auto";
    head.appendChild(name);
    head.appendChild(agentEl("span", `agent-badge ${state}`, t(AGENT_STATE_KEY[state])));
    li.appendChild(head);
    const dl = agentEl("dl", "agent-token-facts");
    const fact = (k, v, ltr) => {
      const dt = agentEl("dt", "", t(k)); const dd = agentEl("dd", "", v);
      if(ltr) dd.dir = "ltr";
      dl.appendChild(dt); dl.appendChild(dd);
    };
    fact("agent.id", r.id, true);
    fact("agent.created", agentWhen(r.created_at));
    fact("agent.expires", agentWhen(r.expires_at));
    fact("agent.lastUsed", r.last_used_at ? agentWhen(r.last_used_at) : t("agent.neverUsed"));
    if(r.revoked_at) fact("agent.revokedAt", agentWhen(r.revoked_at));
    li.appendChild(dl);
    if(state === AgentState.ACTIVE){
      const b = agentEl("button", "btn danger", t("agent.revoke"));
      b.type = "button"; b.dataset.tokenId = r.id;
      b.setAttribute("aria-label", t("agent.revokeLabel", {id: r.id}));
      b.addEventListener("click", () => confirmRevokeAgentToken(r, b));
      li.appendChild(b);
    }
    ul.appendChild(li);
  });
  host.appendChild(ul);
}

async function loadAgentTokens(keepError){
  if(!STORE || MODE !== Mode.API) return;
  AGENT.load = AgentLoad.LOADING; if(keepError !== true) agentClearError(); paintAgentPage();
  try{
    const list = await STORE.req(AGENT_PATH);
    AGENT.tokens = (Array.isArray(list) ? list : []).map(agentCleanRow).filter(Boolean);
    AGENT.load = AgentLoad.READY;
  }catch(err){
    const f = agentFailureOf(err, AgentOp.LOAD);
    AGENT.load = f === AgentFailure.OFF ? AgentLoad.OFF : AgentLoad.FAILED;
    if(AGENT.load === AgentLoad.FAILED) agentSay(f, err && err.detail);
  }
  if(agentPageShown()) paintAgentPage();
}

async function mintAgentToken(){
  if(AGENT.busy || MODE !== Mode.API) return;
  const input = agentById(AgentEl.LABEL);
  const label = input ? input.value.trim().slice(0, AGENT_LABEL_MAX) : "";
  agentClearError(); dropAgentSecret();
  AGENT.busy = true; paintAgentPage();
  let res = null;
  try{
    res = await STORE.req(AGENT_PATH, {method: "POST", body: JSON.stringify({label})});
  }catch(err){
    AGENT.busy = false;
    const f = agentFailureOf(err, AgentOp.MINT);
    if(f === AgentFailure.OFF){ AGENT.load = AgentLoad.OFF; }
    else agentSay(f, err && err.detail);
    if(agentPageShown()) paintAgentPage();
    return;
  }
  AGENT.busy = false;
  const token = res && typeof res.token === "string" ? res.token : "";
  res = null;
  if(!AGENT_TOKEN_SHAPE.test(token)){
    agentSay(AgentFailure.SHAPE); paintAgentPage(); loadAgentTokens(true); return;
  }
  if(!agentPageShown()) return;   // the person left while it was made: it is not shown, and is gone
  AGENT_SECRET = token;
  if(input) input.value = "";
  showAgentReveal();
  paintAgentPage();
  loadAgentTokens();
}

/* The one-time panel. The token is the text of one element, set here and nowhere else. */
function showAgentReveal(){
  const host = agentById("agentRevealHost"); if(!host || AGENT_SECRET == null) return;
  const panel = agentEl("div", "agent-reveal");
  panel.id = AgentEl.REVEAL;
  panel.setAttribute("role", "region");
  panel.setAttribute("aria-labelledby", AgentEl.REVEAL_TITLE);
  panel.tabIndex = -1;
  const h = agentEl("h3", "", t("agent.reveal.title")); h.id = AgentEl.REVEAL_TITLE;
  panel.appendChild(h);
  panel.appendChild(agentEl("p", "agent-warn", t("agent.shownOnce"))).dir = "auto";
  const code = agentEl("code", "agent-secret");
  code.id = AgentEl.SECRET; code.dir = "ltr";
  code.textContent = AGENT_SECRET;
  panel.appendChild(code);
  const row = agentEl("div", "agent-reveal-actions");
  const copy = agentEl("button", "btn primary", t("agent.copy")); copy.type = "button"; copy.id = AgentEl.COPY;
  copy.addEventListener("click", copyAgentToken);
  const done = agentEl("button", "btn", t("agent.done")); done.type = "button"; done.id = AgentEl.DONE;
  done.addEventListener("click", dismissAgentReveal);
  row.appendChild(copy); row.appendChild(done);
  panel.appendChild(row);
  host.appendChild(panel);
  agentAnnounce(t("agent.tokenMade"));
  panel.focus();
}

async function copyAgentToken(){
  const token = AGENT_SECRET; if(token == null) return;
  let ok = false;
  try{
    if(navigator.clipboard && navigator.clipboard.writeText){ await navigator.clipboard.writeText(token); ok = true; }
  }catch(e){ /* refused or unavailable: try the older way */ }
  const code = agentById(AgentEl.SECRET);
  if(!ok && code){
    try{
      const range = document.createRange(); range.selectNodeContents(code);
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
      ok = document.execCommand("copy");
    }catch(e){ ok = false; }
  }
  if(!ok && code){   // leave it selected, so a manual copy is one keystroke
    try{ const range = document.createRange(); range.selectNodeContents(code); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range); }catch(e){}
  }
  agentAnnounce(t(ok ? "agent.copied" : "agent.copyFailed"));
}

function dismissAgentReveal(){
  dropAgentSecret();
  try{ const sel = getSelection(); if(sel) sel.removeAllRanges(); }catch(e){}
  agentAnnounce(t("agent.dismissed"));
  const input = agentById(AgentEl.LABEL); if(input) input.focus();
}

/* Revoking cannot be undone, so it asks (the same modal as deleting a project, without
   the typed name: nothing here is lost but a token). Cancel has the focus. */
function confirmRevokeAgentToken(tok, opener){
  if(AGENT_DIALOG_CLOSE) AGENT_DIALOG_CLOSE(false);
  const host = agentEl("div", "modal-backdrop"); host.id = AgentEl.CONFIRM;
  const box = agentEl("div", "modal");
  box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-labelledby", "agentConfirmTitle");
  const h = agentEl("h2", "", t("agent.confirm.title")); h.id = "agentConfirmTitle"; h.style.marginTop = "0";
  const named = agentEl("p", "agent-token-label", tok.label || t("agent.noLabel")); named.dir = "auto";
  const body = agentEl("p", "", t("agent.confirm.body", {id: tok.id}));
  const actions = agentEl("div", "agent-reveal-actions");
  const cancel = agentEl("button", "btn", t("dash.cancel")); cancel.type = "button";
  const go = agentEl("button", "btn danger", t("agent.confirm.go")); go.type = "button";
  actions.appendChild(cancel); actions.appendChild(go);
  [h, named, body, actions].forEach(n => box.appendChild(n));
  host.appendChild(box); document.body.appendChild(host);
  const onKey = e => {
    if(e.key === "Escape") close(true);   // enum-ok: a DOM key name
    else if(e.key === "Tab"){   // enum-ok: a DOM key name
      const first = e.shiftKey ? cancel : go, last = e.shiftKey ? go : cancel;
      if(document.activeElement === last){ e.preventDefault(); first.focus(); }
    }
  };
  function close(restore){
    document.removeEventListener("keydown", onKey);
    host.remove(); AGENT_DIALOG_CLOSE = null;
    if(restore && opener && opener.isConnected) opener.focus();
  }
  AGENT_DIALOG_CLOSE = close;
  document.addEventListener("keydown", onKey);
  cancel.addEventListener("click", () => close(true));
  host.addEventListener("click", e => { if(e.target === host) close(true); });
  go.addEventListener("click", () => { close(false); revokeAgentToken(tok.id); });
  cancel.focus();
}

async function revokeAgentToken(id){
  if(AGENT.busy || !AGENT_ID_SHAPE.test(id)) return;
  AGENT.busy = true; agentClearError();
  let failed = false;
  try{
    await STORE.req(`${AGENT_PATH}/${id}`, {method: "DELETE"});
    agentAnnounce(t("agent.revoked", {id}));
  }catch(err){
    failed = true;
    agentSay(agentFailureOf(err, AgentOp.REVOKE), err && err.detail);
  }
  AGENT.busy = false;
  if(agentPageShown()){ paintAgentPage(); await loadAgentTokens(failed); }
}
