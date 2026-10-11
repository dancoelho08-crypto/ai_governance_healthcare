/* ============================================================
   Project setup
   The project itself: who is reviewing what, the history, and which
   optional frameworks are switched on. This is not CHAI's screen --
   it belongs to the project, which is why it lives outside the
   framework directories and registers first so it heads the rail.

   The compliance banner does read CHAI's flags(). That is deliberate
   and documented: CHAI is the spine the dashboard status comes from,
   and only one framework can own that. See docs/crosswalk.md.
   ============================================================ */
function frameworkToggles(){
  // The frameworks a project may switch on: the build's opt-in supplements.
  const optional = FRAMEWORKS.filter(f => !f.primary && f.optIn);
  if(!optional.length) return "";
  const rows = optional.map(f=>{
    const on = f.enabled(S);
    return `<li style="display:flex;align-items:center;gap:10px;padding:6px 0">
      <button class="btn${on?" primary":""}" data-framework="${esc(f.id)}" aria-pressed="${on}">${esc(t(on?"fw.on":"fw.off"))}</button>
      <span><b>${esc(f.label)}</b> \u2014 ${esc(t(f.facade.slot(on?UiSlot.TOGGLE_ON_DETAIL:UiSlot.TOGGLE_OFF_DETAIL),{count:f.facade.fw.items.length}))}</span>
    </li>`;
  }).join("");
  return `<h2 class="ro-hide">${esc(t("fw.title"))}</h2>
  <p class="ro-hide" style="font-size:13px;color:var(--muted)">${esc(t(uiKey(UiSlot.FW_LEDE),uiName()))}</p>
  <ul class="ro-hide" style="list-style:none;padding:0;margin:0">${rows}</ul>`;
}

/* The stored values of the setup's choice fields (English, as records hold them),
   each with the catalog key of what the reader sees. */
const SOURCING_KEY = Object.freeze({
  "Purchased from a vendor": "opt.sourcing.vendor", "Built internally": "opt.sourcing.internal",
  "Co-developed": "opt.sourcing.codev", "Open-source model, locally adapted": "opt.sourcing.open",
});
const RISK_KEY = Object.freeze({ Low: "opt.risk.low", Moderate: "opt.risk.moderate", High: "opt.risk.high" });
const CADENCE_KEY = Object.freeze({
  "3 months": "opt.cadence.3", "6 months": "opt.cadence.6",
  "12 months": "opt.cadence.12", "24 months": "opt.cadence.24",
});

function renderSetup(){
  const fw=spine(), f=fw.flags(S), st=fw.status(S), nr=fw.nextReview(S);
  const empty = !Object.keys(fw.answers(S)).length && !Object.keys(S.card || {}).length;
  return `<p class="eyebrow">${esc(t(uiKey(UiSlot.SETUP_EYEBROW)))}</p><h1>${esc(t("setup.title"))}</h1>
  <p class="lede">${esc(t("setup.lede"))}</p>
  <div class="note ${st.key==="green"?"ok":""}" style="${st.key==="retired"?"border-color:var(--muted);background:var(--sunk)":""}"><b>${esc(statusLabel(st))}</b> · ${esc(phaseLabel(fw.phase(S)))}${nr?` · ${esc(t("setup.nextReview",{date:fmtDay(nr)}))}`:""}
    ${f.length?`<ul class="gaplist">${f.map(x=>`<li>${esc(flagText(x))}</li>`).join("")}</ul>`:""}</div>
  <div class="fields">
    ${field("meta.solution",t("setup.f.solution"),"",0)}
    ${field("meta.org",t("setup.f.org"),"",0)}
    ${field("meta.developer",t("setup.f.developer"),"",0)}
    ${field("meta.sourcing",t("setup.f.sourcing"),"",0,Object.keys(SOURCING_KEY),null,v=>t(SOURCING_KEY[v]))}
    ${field("meta.sponsor",t("setup.f.sponsor"),t("setup.f.sponsorHint"),0)}
    ${field("meta.riskTier",t("setup.f.riskTier"),t("setup.f.riskTierHint"),0,Object.keys(RISK_KEY),null,v=>t(RISK_KEY[v]))}
    ${field("meta.reviewCadence",t("setup.f.cadence"),t("setup.f.cadenceHint"),0,Object.keys(CADENCE_KEY),null,v=>t(CADENCE_KEY[v]))}
    ${field("meta.startDate",t("setup.f.startDate"),"",0,null,"date")}
    ${field("meta.reviewers",t("setup.f.reviewers"),t("setup.f.reviewersHint"),1)}
    ${field("meta.scope",t("setup.f.scope"),t("setup.f.scopeHint"),1)}
  </div>
  ${frameworkToggles()}

  <h2>${esc(t("setup.history"))}</h2>
  ${historyHTML()}
  ${accessHTML()}
  ${holdHTML()}

  <h2>${esc(t("setup.manage"))}</h2>
  <div style="display:flex;flex-wrap:wrap;gap:8px">
    ${empty&&!RO&&spine().samples?`<button class="btn" data-act="example">${esc(t("setup.example"))}</button>`:""}
    ${canOwn(S)?`<button class="btn" data-act="archive">${esc(t(S.archived?"setup.restore":"setup.archive"))}</button>
    <button class="btn danger" data-act="delete">${esc(t("setup.delete"))}</button>`
    :`<p style="font-size:13px;color:var(--muted);margin:0">${esc(t("setup.ownerOnly",{note:roleNote()}))}</p>`}
  </div>
  ${pager()}`;
}

registerFramework({
  id: "project",
  label: "Project",
  enabled: () => true,
  blank: () => ({}),
  views: () => [
    { id: "setup", kind: "setup", label: t("rail.setup"), num: 0, sep: "after" },
    { id: "changelog", kind: "changelog", label: t("rail.changelog"), glyph: "\u21bb",
      short: t("rail.changelogShort"), order: "end", sep: "before",
      meta: () => LOG.length ? String(LOG.length) : "" },
  ],
  render: v => v.kind === "changelog" ? changelogHTML() : renderSetup(),
});


/* The litigation hold (#57, R-56): a placeholder the page fills once the server
   answers (fillHold, after each render). Only an owner sees it, and only with a
   server, which is the only place anything is disposed of. */
function holdHTML(){
  if(typeof STORE.getHold !== "function" || !identityKnown() || !canOwn(S)) return "";
  return `<section id="holdHost" aria-live="polite"><h2>${esc(t("hold.title"))}</h2>
    <p class="small" style="color:var(--muted)">${esc(t("hold.lede"))}</p>
    <div data-hold-body><p class="small">${esc(t("hold.loading"))}</p></div></section>`;
}
const HOLD_ENTRY_KEY = Object.freeze({ [HoldAction.PLACE]: "hold.entry.place", [HoldAction.LIFT]: "hold.entry.lift" });

async function fillHold(){
  const host = document.querySelector("#holdHost [data-hold-body]");
  if(!host) return;
  const id = CUR;
  let state;
  try{ state = await STORE.getHold(id); }
  catch(e){ host.innerHTML = `<p class="small">${esc(t("hold.unavailable"))}</p>`; return; }
  if(CUR !== id || !host.isConnected) return;
  const next = state.held ? HoldAction.LIFT : HoldAction.PLACE;
  host.innerHTML = `<div class="note${state.held ? "" : " ok"}"><p><b>${esc(t(state.held ? "hold.on" : "hold.off"))}</b></p></div>
    ${state.history.length ? `<ul class="history">${state.history.slice(0, 6).map(h => `<li><time>${esc(fmtDay(h.at.slice(0,10)))}</time><span>${tHtml(HOLD_ENTRY_KEY[h.action], {}, {who: who(h.by), reason: bdi(h.reason)})}</span></li>`).join("")}</ul>` : ""}
    <button class="btn${state.held ? "" : " danger"}" data-hold-action="${esc(next)}">${esc(t(state.held ? "hold.lift" : "hold.place"))}</button>`;
  resolveNames(host);
}

function openHoldDialog(action){
  const placing = action === HoldAction.PLACE;
  const host = document.createElement("div");
  host.className = "modal-backdrop";
  host.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="holdTitle">
      <h2 id="holdTitle" style="margin-top:0">${esc(t(placing ? "hold.dialogPlace" : "hold.dialogLift"))}</h2>
      <p>${esc(t(placing ? "hold.explainPlace" : "hold.explainLift"))}</p>
      <label for="holdReason">${esc(t("hold.reason"))}</label>
      <input type="text" id="holdReason" maxlength="1000" autocomplete="off" aria-describedby="holdHint">
      <p id="holdHint" class="small" style="color:var(--muted)">${esc(t("hold.reasonHint"))}</p>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
        <button class="btn" data-hold-cancel>${esc(t("dash.cancel"))}</button>
        <button class="btn primary" data-hold-go disabled>${esc(t(placing ? "hold.confirmPlace" : "hold.confirmLift"))}</button>
      </div>
    </div>`;
  document.body.appendChild(host);
  const field = host.querySelector("#holdReason");
  const go = host.querySelector("[data-hold-go]");
  const close = () => { host.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if(e.key === "Escape") close(); };  // enum-ok: DOM KeyboardEvent.key value
  field.addEventListener("input", () => { go.disabled = !field.value.trim(); });
  field.addEventListener("keydown", e => { if(e.key === "Enter" && !go.disabled) go.click(); });  // enum-ok: DOM KeyboardEvent.key value
  host.querySelector("[data-hold-cancel]").onclick = close;
  host.addEventListener("click", e => { if(e.target === host) close(); });
  document.addEventListener("keydown", onKey);
  go.onclick = async () => {
    const cut = stripAddressCredentials(field.value.trim());
    const reason = cut.text;
    if(!reason) return;
    go.disabled = true;
    close();
    try{
      await STORE.setHold(CUR, action, reason);
      toast(t(placing ? "toast.holdPlaced" : "toast.holdLifted"));
      if(cut.removed) setTimeout(() => toast(t("toast.credsRemoved")), 2600);  // after the first has been read
    }catch(e){ toast(t("toast.holdFailed")); }
    fillHold();
  };
  setTimeout(() => field.focus(), 0);
}

/* Who holds what on this project. Owner-only to change, because
   granting access is itself a privilege. */
function accessHTML(){
  const a=accessOf(S), mine=roleOf(S), owner=canOwn(S);
  const rows=ROLES.flatMap(role=>a[role+"s"].map(id=>({id,role})));

  if(!identityKnown()){
    return `<h2>${esc(t("access.title"))}</h2>
    <div class="note"><p><b>${esc(t("access.unenforced.title"))}</b> ${esc(t("access.unenforced.detail"))}</p></div>`;
  }

  const list = rows.length
    ? `<table class="tbl"><thead><tr><th>${esc(t("access.col.person"))}</th><th>${esc(t("access.col.role"))}</th>${owner?`<th><span class="vh">${esc(t("access.col.change"))}</span></th>`:""}</tr></thead><tbody>
       ${rows.map(r=>`<tr>
         <td>${who(r.id)}${r.id===ME.id?` <span class="small">${esc(t("access.youTag"))}</span>`:""}</td>
         <td>${owner?`<select data-role-for="${esc(r.id)}">${ROLES.map(x=>`<option value="${x}"${x===r.role?" selected":""}>${esc(roleLabel(x))}</option>`).join("")}</select>`:esc(roleLabel(r.role))}</td>
         ${owner?`<td><button class="icon-btn" data-revoke="${esc(r.id)}" aria-label="${esc(t("access.removeLabel"))}">${esc(t("access.remove"))}</button></td>`:""}
       </tr>`).join("")}</tbody></table>`
    : `<p style="font-size:13px;color:var(--muted)">${esc(t("access.open"))}</p>`;

  /* The commonest way a record becomes unreachable: whoever created it is its
     only owner, and their account is later disabled. Nobody left can read, export,
     reassign or delete it, short of an emergency-access identity or a database
     edit (#42). Said to the one person who can fix it. */
  const soleOwner = owner && a.owners.length===1 && a.owners[0]===ME.id
    ? `<div class="note"><p><b>${esc(t("access.sole.title"))}</b> ${esc(t("access.sole.detail"))}</p></div>`
    : "";

  return `<h2>${esc(t("access.title"))}</h2>
  <p style="font-size:13px;color:var(--muted)">${esc(t("access.lede"))}
  ${esc(t(mine?ROLE_YOU_KEY[mine]:"access.you.none"))}</p>
  ${soleOwner}
  ${list}
  ${owner?`<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin-top:10px">
    <div class="field" style="margin:0"><label for="grantWho">${esc(t("access.add"))}</label>
      <input type="text" id="grantWho" placeholder="${esc(t("access.idPlaceholder"))}" data-grant-id></div>
    <div class="field" style="margin:0"><label for="grantRole">${esc(t("access.role"))}</label>
      <select id="grantRole" data-grant-role>${ROLES.map(x=>`<option value="${x}">${esc(roleLabel(x))}</option>`).join("")}</select></div>
    <button class="btn" data-act="grant">${esc(t("access.grant"))}</button>
  </div>`:""}
  ${unclaimed(S)&&identityKnown()?`<button class="btn primary" data-act="claim" style="margin-top:10px">${esc(t("access.claim"))}</button>`:""}`;
}

const roleNote = () => {
  const r = roleOf(S);
  return t(r ? ROLE_YOU_KEY[r] : "access.you.none");
};


/* ============================================================
   Changelog view
   The audit trail, rendered as what changed rather than that
   something did. Grouped by day, because "what happened at this
   meeting" is how a committee reads it.
   ============================================================ */
function changelogHTML(){
  const now = contentHash(storedRecord(S));

  if(!LOG.length){
    return `<p class="eyebrow">${esc(t("log.eyebrow"))}</p><h1>${esc(t("log.title"))}</h1>
    <p class="lede">${esc(t("log.lede"))}</p>
    <div class="note"><p>${esc(t("log.none"))}</p></div>
    ${fingerprintHTML(now)}
    ${pager()}`;
  }

  // Group by calendar day. The log arrives newest-first and stays that way.
  const days = [];
  LOG.forEach(e=>{
    const day = (e.at||"").slice(0,10);
    const last = days[days.length-1];
    if(last && last.day===day) last.entries.push(e);
    else days.push({day, entries:[e]});
  });

  const rows = days.map(d=>`
    <h2 style="font-size:15px;margin:18px 0 6px">${esc(fmtDay(d.day)||t("log.undated"))}</h2>
    <ul class="history">${d.entries.map(e=>{
      const c = e.change;
      const detail = c
        ? `<div class="small" style="color:var(--muted);margin-top:2px">
             <code>${esc(c.path)}</code></div>`
        : "";
      return `<li>
        <time>${esc((e.at||"").slice(11,16))}</time>
        <span>${esc(e.text)}
          <span style="color:var(--muted)">${tHtml("log.by",{},{who:who(e.by)})}</span>
          ${e.hash?`<span class="small" style="color:var(--muted)" title="${esc(t("log.fpAfter"))}">\u00b7 ${esc(shortHash(e.hash))}</span>`:""}
          ${detail}</span>
      </li>`;}).join("")}</ul>`).join("");

  return `<p class="eyebrow">${esc(t("log.eyebrow"))}</p><h1>${esc(t("log.title"))}</h1>
  <p class="lede">${esc(t("log.lede"))}
  ${logWindowNote()?`<br><strong>${esc(logWindowNote())}</strong>`:""}</p>
  ${olderLogControl()}
  ${rows}
  ${fingerprintHTML(now)}
  ${pager()}`;
}

/* Older entries, where the store can fetch them. Past the server's page cap the
   rest is reached through the API, and this says so rather than going quiet. */
function olderLogControl(){
  if(LOG_TOTAL===null || LOG_TOTAL<=LOG.length) return "";
  if(STORE && typeof STORE.showOlderLog==="function" && LOG.length<500)
    return `<p><button class="btn" data-act="${Act.LOG_OLDER}">${esc(t("log.older"))}</button></p>`;
  if(STORE && typeof STORE.showOlderLog==="function")
    return `<p class="small" style="color:var(--muted)">${tHtml("log.cap",{},{api:"<code>GET /api/projects/{id}/log?before=&lt;X-Log-Next&gt;</code>"})}</p>`;
  return "";
}

/* The record's current fingerprint, with the caveat attached. A hash
   printed without saying what it proves will be read as proving more
   than it does. */
function fingerprintHTML(md5hex){
  return `<h2 style="font-size:15px;margin-top:22px">${esc(t("fp.title"))}</h2>
  <p style="font-size:13px;color:var(--muted)">${esc(t("fp.lede"))}</p>
  <p><code style="font-size:13px">MD5 ${esc(md5hex)}</code></p>
  <div class="note"><p><b>${esc(t("fp.warnTitle"))}</b> ${esc(t("fp.warnDetail"))}</p></div>`;
}
