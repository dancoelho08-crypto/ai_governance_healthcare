/* ============================================================
   Dashboard
   ============================================================ */
/* The lifecycle track: one pip per section of the primary framework, and a
   diamond for each checkpoint after the section it follows. Built from the
   framework's own sections and gates, so another framework draws its own (#168). */
const GATE_PIP = Object.freeze({
  [GateClass.GO]: "go", [GateClass.CONDITIONAL]: "cond", [GateClass.REVISE]: "cond",
  [GateClass.STOP]: "stop", [GateClass.RETIRE]: "stop",
});
function lcTrack(p){
  const fw=spine(), ph=fw.phase(p);
  const pip=s=>{const c=fw.score(p,s.items); const frac=c.total?c.answered/c.total:0;
    return `<span class="pip${frac===1?" full":""}${ph.stage===s.n?" cur":""}" title="${esc(t(uiKey(UiSlot.PIP_TITLE),{n:s.n,answered:c.answered,total:c.total}))}"><i style="height:${Math.round(frac*100)}%"></i>${esc(s.n)}</span>`;};
  const gd=g=>{const d=fw.gateRecord(p,g.id).decision||""; const c=fw.decisionClass(d,g.id); const cls=c?GATE_PIP[c]:""; return `<span class="gd ${cls}" title="${esc(fw.gateLabel(g.id))}: ${esc(d?fw.optionLabel(d):t("dash.gateOpen"))}"></span>`;};
  const gates=fw.gates();
  const track=fw.sections().map(s=>pip(s)+gates.filter(g=>g.after===s.id).map(gd).join("")).join("");
  return `<div class="lc" aria-hidden="true">${track}</div><div class="lc-label">${esc(phaseLabel(ph))}</div>`;
}
function dashData(){
  const fw=spine();
  const list=[...PROJECTS.values()].filter(isOwnRecord).map(p=>normalize(p));
  const rows=list.map(p=>({p, st:fw.status(p), f:fw.flags(p), score:fw.score(p).pct, nr:fw.nextReview(p)}));
  return rows;
}
/* The portfolio's search fields, by element id: one definition, read by the
   template and by the input handler (70-events.js). */
const SearchField = Object.freeze({ QUERY: "q", ALL_TEXT: "qall" });
const SEARCH_HINT = Object.freeze({ NAMES: "dash.searchNames", ALL_TEXT: "dash.searchAll" });
function renderDashboardShell(){
  agentLeave();   // the agent page's token never outlives the page (#164)
  document.body.classList.add("home");
  document.getElementById("projName").textContent = t("header.portfolio");
  const m=document.getElementById("main");
  let legacy=null;
  try{ const raw=localStorage.getItem("chai-review-v1"); if(raw && !localStorage.getItem("chai-legacy-imported")){ const j=JSON.parse(raw); if(j&&j.meta&&isOwnRecord(j)&&(j.meta.solution||Object.keys(j.items||{}).length)) legacy=j; } }catch(e){}
  m.innerHTML = `
    <div class="dash-head">
      <div><p class="eyebrow">${esc(t("dash.eyebrow"))}</p><h1>${esc(t("dash.title"))}</h1>
      <p class="lede">${esc(t(uiKey(UiSlot.DASH_LEDE),uiName()))}</p></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">
        <button class="btn ro-hide" data-act="samples" title="${esc(t("dash.addSamplesTitle"))}">${esc(t("dash.addSamples"))}</button>
        <button class="btn primary ro-hide" data-act="new">${esc(t("dash.newProject"))}</button>${MODE===Mode.API?`<button class="btn" data-act="${esc(Act.AGENT_OPEN)}">${esc(t("agent.open"))}</button>`:""}
      </div>
    </div>
    ${legacy?`<div class="banner ro-hide" id="legacyBanner"><span>${tHtml("dash.legacy",{},{name:`<b>${esc(legacy.meta.solution||t("dash.legacyUnnamed"))}</b>`})}</span><span style="display:flex;gap:8px"><button class="btn" data-act="legacy">${esc(t("dash.legacyAdd"))}</button><button class="btn ghost" data-act="legacy-dismiss">${esc(t("dash.legacyDismiss"))}</button></span></div>`:""}
    <form class="newform ro-hide" id="newform" hidden>
      <label for="newname" class="vh">${esc(t("dash.newName"))}</label>
      <input type="text" id="newname" placeholder="${esc(t("dash.newNamePlaceholder"))}" autocomplete="off">
      <button class="btn primary" type="submit">${esc(t("dash.create"))}</button>
      <button class="btn ghost" type="button" data-act="new-cancel">${esc(t("dash.cancel"))}</button>
    </form>
    <div class="tallies" id="tallies" role="group" aria-label="${esc(t("dash.filterLabel"))}"></div>
    <div class="toolbar">
      <label for="${SearchField.QUERY}" class="vh">${esc(t("dash.searchLabel"))}</label>
      <input type="search" id="${SearchField.QUERY}" placeholder="${esc(t(UI.qAll?SEARCH_HINT.ALL_TEXT:SEARCH_HINT.NAMES))}" value="${esc(UI.q||"")}">
      <label class="qall"><input type="checkbox" id="${SearchField.ALL_TEXT}"${UI.qAll?" checked":""}> ${esc(t("dash.searchAllToggle"))}</label>
      <span class="spacer"></span>
      <button class="btn ghost" data-act="dl-csv">${esc(t("dash.exportCsv"))}</button>
      <button class="btn ghost ro-hide" data-act="import">${esc(t("dash.importJson"))}</button>
    </div>
    <div id="plistHost"></div>`;
  applyRO(m);
  updateDashboard();
}
function updateDashboard(){
  const host=document.getElementById("plistHost"); if(!host) return;
  const tl=document.getElementById("tallies");
  if(!LOADED){ host.innerHTML=`<p style="color:var(--muted)">${esc(t("dash.loading"))}</p>`; tl.innerHTML=""; return; }
  const rows=dashData();
  const active=rows.filter(r=>!r.p.archived);
  const cnt=k=>active.filter(r=>r.st.key===k).length;
  const archived=rows.length-active.length;
  const T=[["red",t("dash.tally.red"),cnt("red")],["amber",t("dash.tally.amber"),cnt("amber")],["green",t("dash.tally.green"),cnt("green")],["retired",t("dash.tally.retired"),cnt("retired")],["all",t("dash.tally.all"),active.length]];
  if(archived) T.push(["archived",t("dash.tally.archived"),archived]);
  tl.innerHTML = T.map(([k,l,n])=>`<button class="tally ${k==="archived"?"retired":k}" data-filter="${k}" aria-pressed="${UI.filter===k}"><span class="n">${n}</span><span class="t">${esc(l)}</span></button>`).join("");
  const q=(UI.q||"").toLowerCase().trim();
  const everything = !!(UI.qAll && q);
  let list = UI.filter==="archived" ? rows.filter(r=>r.p.archived) : active.filter(r=>UI.filter==="all"||r.st.key===UI.filter);
  if(everything){
    // Every project the viewer can open, archived included, whatever the status filter.
    list = rows.map(r=>Object.assign(r,{hits:textHits(r.p,q)})).filter(r=>r.hits.length);
  }
  else if(q) list=list.filter(r=>[r.p.meta.solution,r.p.meta.developer,r.p.meta.sponsor,r.p.meta.org].join(" ").toLowerCase().includes(q));
  // Records of another framework (from another build on this server) are not this
  // build's to show; say how many are left out rather than hide them silently.
  const foreign=[...PROJECTS.values()].filter(p=>!isOwnRecord(p)).length;
  const hidden = foreign ? `<p class="small search-note" id="foreignNote">${esc(t("dash.foreignHidden",{count:foreign}))}</p>` : "";
  const note = hidden + (everything
    ? `<p class="small search-note" id="searchNote">${esc(t("dash.searchNote"))}${MODE===Mode.API?` ${esc(t("dash.searchNoteServer"))}`:""}</p>`
    : "");
  const rank={red:0,amber:1,green:2,retired:3};
  list.sort((a,b)=>(rank[a.st.key]-rank[b.st.key]) || (b.f.length-a.f.length) || (a.p.meta.solution||"").localeCompare(b.p.meta.solution||""));
  if(!rows.length){
    const samples=spine().samples;
    host.innerHTML=`${hidden}<div class="empty-state"><p>${esc(samples?t(uiKey(UiSlot.DASH_EMPTY),{count:samples.count()}):t("dash.emptyNoSamples"))}</p>
      <div class="ro-hide" style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" data-act="new">${esc(t("dash.newProject"))}</button>${samples?`<button class="btn" data-act="samples">${esc(t("dash.loadSamples"))}</button>`:""}</div></div>`;
    applyRO(host); return;
  }
  if(!list.length){ host.innerHTML= note + (everything
      ? `<p style="color:var(--muted);margin-top:18px">${esc(t("dash.noTextMatch"))}</p>`
      : `<p style="color:var(--muted);margin-top:18px">${esc(t("dash.noMatch"))}</p>`); return; }
  const today=parseDay(TODAY());
  host.innerHTML=`${note}<div class="phead" aria-hidden="true"><span>${esc(t("dash.col.project"))}</span><span>${esc(t("dash.col.lifecycle"))}</span><span>${esc(t("dash.col.readiness"))}</span><span>${esc(t("dash.col.nextReview"))}</span><span>${esc(t("dash.col.status"))}</span></div>
  <ul class="plist">${list.map(r=>{const p=r.p; const late=r.nr&&parseDay(r.nr)<today; const name=p.meta.solution||t("dash.thisProject");
    return `<li class="prow ${r.st.key}" data-open="${esc(p.id)}">
      <div><button class="pname" data-open="${esc(p.id)}">${p.meta.solution?bdi(p.meta.solution):esc(t("project.untitled"))}</button>
        <div class="psub">${[p.meta.developer&&bdi(p.meta.developer),p.meta.sponsor&&tHtml("dash.sponsor",{},{name:bdi(p.meta.sponsor)})].filter(Boolean).join(" · ")||esc(t("dash.noDeveloper"))}</div>
        <div class="psub">${tHtml("dash.updated",{when:ago(p.updatedAt)},{who:who(p.updatedBy)})}${p.archived?` · ${esc(t("dash.archivedTag"))}`:""}</div>
        ${r.hits&&everything?`<div class="psub hits">${esc(t("dash.foundIn",{places:r.hits.slice(0,4).join("; ")}))}${r.hits.length>4?` ${esc(t("dash.andMore",{count:r.hits.length-4}))}`:""}</div>`:""}</div>
      <div>${lcTrack(p)}</div>
      <div><span class="pct">${r.score}%</span></div>
      <div>${r.nr?`<span class="due${late?" late":""}">${esc(fmtDay(r.nr))}</span>${late?`<div class="small" style="color:var(--red)">${esc(t("dash.overdue"))}</div>`:""}`:`<span class="small">${esc(t(spine().isLive(spine().phase(p))?"dash.notSet":"dash.notLive"))}</span>`}</div>
      <div><span class="st ${r.st.key}">${esc(statusLabel(r.st))}</span>
        ${r.f.length?`<ul class="flags">${r.f.slice(0,3).map(f=>`<li class="${f.sev}">${esc(flagText(f))}</li>`).join("")}${r.f.length>3?`<li>${esc(t("dash.andMore",{count:r.f.length-3}))}</li>`:""}</ul>`:""}
        <button class="icon-btn ro-hide parchive" data-archive="${esc(p.id)}"
          aria-label="${esc(t(p.archived?"dash.restoreLabel":"dash.archiveLabel",{name}))}"
          title="${esc(t(p.archived?"dash.restoreTitle":"dash.archiveTitle"))}"
          >${esc(t(p.archived?"dash.restore":"dash.archive"))}</button></div>
    </li>`;}).join("")}</ul>`;
  resolveNames(host);
}
function goHome(){
  flushAllChanges();
  if(CUR && pending[CUR]) flush(CUR);
  if(unsubLog){ unsubLog(); unsubLog=null; }
  CUR=null; S=null; LOG=[]; LOG_TOTAL=null; openItems.clear(); saveUI();
  document.getElementById("panel").classList.remove("open");
  renderDashboardShell(); window.scrollTo({top:0});
}
function openProject(id,view){
  flushAllChanges();          // leaving a project ends any edit in progress
  const p=PROJECTS.get(id); if(!p) return;
  if(!isOwnRecord(p)){ toast(t("toast.foreignRecord",{name:String(recordFramework(p)).slice(0,64)})); return; }
  if(unsubLog){ unsubLog(); unsubLog=null; }
  CUR=id; S=normalizeStored(clone(storedRecord(p))); LOG=[]; LOG_TOTAL=null; openItems.clear();
  // Read-only is a property of this project and this user, not of the
  // workspace: the same person may own one review and only read another.
  RO = !canWrite(S);
  document.body.classList.toggle("ro", RO);
  UI.view=view||"setup"; saveUI();
  warmNames(idsOfProject(S));
  unsubLog=STORE.subscribeLog(id,(l,meta)=>{ LOG=l||[]; LOG_TOTAL=(meta && Number.isFinite(meta.total)) ? meta.total : null; warmNames(LOG.map(e=>e.by)); if(CUR===id && (UI.view==="setup"||UI.view===spine().reportViewId) && !editingInMain()){ const y=window.scrollY; renderMain(false); window.scrollTo(0,y);} });
  renderProject(true);
}
function go(view){ flushAllChanges(); UI.view=view; saveUI(); renderRail(); renderMain(true); document.getElementById("panel").classList.remove("open"); }
