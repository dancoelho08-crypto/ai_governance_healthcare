/* ============================================================
   Events
   ============================================================ */
document.addEventListener("click",async e=>{
  const row=e.target.closest(".prow");
  const btn=e.target.closest("button");
  if(!btn && row){ openProject(row.dataset.open); return; }
  if(!btn) return;
  if(btn.dataset.archive){
    const id=btn.dataset.archive, p=PROJECTS.get(id);
    if(!p) return;
    if(!canOwn(p)){ toast(t("toast.ownerArchive")); return; }
    const v=!p.archived;
    p.archived=v;
    queuePatch(id, Object.assign({archived:v}, stamp()));
    writeLog(id, v?"Archived":"Restored");
    updateDashboard();
    toast(v?t("toast.archived"):t("toast.restored"));
    return;
  }
  if(btn.dataset.revoke && canOwn(S)){
    const id=btn.dataset.revoke;
    if(wouldOrphan(S,id,"")){ toast(t("toast.keepOwner")); return; }
    S.access=accessPatch(S,id,""); queuePatch(CUR,Object.assign({access:S.access},stamp()));
    writeLog(CUR,`Removed access for ${id}`); renderMain(false); toast(t("toast.accessRemoved")); return;
  }
  if(btn.dataset.addref && !RO){ const box=btn.closest(".refs"); if(box) await addRef(btn.dataset.addref, box); return; }
  if(btn.dataset.delref && !RO){ removeRef(btn.dataset.refpath, btn.dataset.delref); return; }
  if(btn.dataset.verifyref){
    const path=btn.dataset.refpath, id=btn.dataset.verifyref;
    const pick=document.createElement("input"); pick.type="file";
    pick.addEventListener("change",()=>verifyRef(path,id,pick.files[0]));
    pick.click(); return;
  }
  if(btn.dataset.open){ openProject(btn.dataset.open); return; }
  if(btn.dataset.home){ goHome(); return; }
  if(btn.dataset.go){ go(btn.dataset.go); return; }
  if(btn.dataset.framework && !RO){
    const f=frameworkById(btn.dataset.framework);
    if(f && f.toggle) f.toggle(!f.enabled(S));
    return;
  }
  if(btn.dataset.filter){ UI.filter=btn.dataset.filter; saveUI(); updateDashboard(); document.querySelector(`[data-filter="${CSS.escape(UI.filter)}"]`)?.focus(); return; }
  if(btn.dataset.set && !RO){
    const id=btn.dataset.set, store=btn.dataset.store||"items";
    const cur=((get(store)||{})[id]||{}).status||"";
    const val = cur===btn.dataset.s ? "" : btn.dataset.s;
    edit(`${store}.${id}.status`, val);
    const li=btn.closest(".ci");
    li.querySelectorAll(".seg button").forEach(b=>b.setAttribute("aria-pressed", String(b.dataset.s===val)));
    // A status that asks for a reason (OPTICA's Declined) adds or removes a field,
    // so the item is drawn again, open, with the field in place (#172). The item
    // names that status itself; the shell compares two values it was given.
    const reasonFor=li.dataset.reasonFor;
    if(reasonFor && (val===reasonFor || cur===reasonFor)){ openItems.add(id); renderMain(false); renderRail(); return; }
    if((val==="partial"||val==="notmet") && !openItems.has(id)){ openItems.add(id); li.classList.add("open"); const m=li.querySelector(".more"); m.textContent=t("ci.hide"); m.setAttribute("aria-expanded","true"); }
    renderRail(); return;
  }
  if(btn.dataset.toggle){
    const id=btn.dataset.toggle, li=btn.closest(".ci"); const open=!openItems.has(id);
    open?openItems.add(id):openItems.delete(id);
    li.classList.toggle("open",open); btn.textContent=t(open?"ci.hide":"ci.more"); btn.setAttribute("aria-expanded",String(open));
    if(open && !RO) li.querySelector("textarea").focus();
    return;
  }
  if(btn.dataset.gate && !RO){
    // The server would retire the record by rules this page does not show (D-83).
    if(rulesBlockWrites()){ toast(t("rules.refused")); return; }
    const k=btn.dataset.gate, g=S.gates[k]||{};
    const val = g.decision===btn.dataset.d ? "" : btn.dataset.d;
    const now=new Date().toISOString();
    const patch={gates:{[k]:{decision:val, signedBy:val?(ME.id||null):null, signedAt:val?now:null, date: val ? (g.date||TODAY()) : (g.date||"")}}};
    deepMerge(S,patch); const st=stamp(); Object.assign(S,st);
    queuePatch(CUR, Object.assign(patch,st));
    const title=(spine().gates().find(x=>x.id===k)||{title:k}).title;
    writeLog(CUR, val?`${title}: ${val}`:`${title}: decision cleared`);
    renderRail(); renderMain(false); return;
  }
  if(btn.dataset.holdAction){ openHoldDialog(btn.dataset.holdAction); return; }
  if(frameworkClick(btn)) return;
  const a=btn.dataset.act; if(!a) return;
  if(a===Act.UNLOCK){ location.reload(); return; }
  if(a==="new"){ const f=document.getElementById("newform"); if(f){ f.hidden=false; document.getElementById("newname").focus(); } return; }
  if(a==="new-cancel"){ document.getElementById("newform").hidden=true; return; }
  if(a==="samples"){
    btn.disabled=true;
    try{ const s=spine().samples; if(s) await s.loadAll(); }
    finally{ btn.disabled=false; }
    return;
  }
  if(a==="legacy"){
    try{ const j=JSON.parse(localStorage.getItem("chai-review-v1")); if(!isOwnRecord(j)) throw new Error("another framework's record"); const p=normalize(Object.assign(blankProject(j.meta.solution),{meta:j.meta,items:j.items||{},gates:j.gates||{},metrics:j.metrics||[],card:j.card||{}}));
      Object.values(p.items).forEach(x=>{ if(x) delete x._open; });
      const id=await createProject(p,"Imported from a review saved in this browser"); if(id){ localStorage.setItem("chai-legacy-imported","1"); document.getElementById("legacyBanner")?.remove(); toast(t("toast.legacyImported")); }
    }catch(err){ toast(t("toast.legacyFailed")); }
    return;
  }
  if(a==="legacy-dismiss"){ try{localStorage.setItem("chai-legacy-imported","1");}catch(e){} document.getElementById("legacyBanner")?.remove(); return; }
  if(a==="import"){ document.getElementById("importFile").click(); return; }
  if(a==="dl-csv"){ download(`ai-governance-portfolio-${TODAY()}.csv`, exportCSV()); noteExport(ExportFormat.CSV); return; }
  if(!S) return;
  if(a===Act.LOG_OLDER){ if(STORE && STORE.showOlderLog) STORE.showOlderLog(CUR); return; }
  if(a==="claim"){
    if(!ME.id){ toast(t("toast.noUserClaim")); return; }
    S.access=accessPatch(S,ME.id,"owner"); queuePatch(CUR,Object.assign({access:S.access},stamp()));
    writeLog(CUR,"Claimed ownership"); RO=false; renderProject(false); toast(t("toast.nowOwner")); return;
  }
  if(a==="grant"){
    if(!canOwn(S)){ toast(t("toast.ownerGrant")); return; }
    const el=document.querySelector("[data-grant-id]");
    const id=el&&el.value?el.value.trim():"";
    const roleEl=document.querySelector("[data-grant-role]");
    const role=roleEl?roleEl.value:"reader";
    if(!id){ toast(t("toast.enterId")); return; }
    S.access=accessPatch(S,id,role); queuePatch(CUR,Object.assign({access:S.access},stamp()));
    writeLog(CUR,`Granted ${ROLE_LABEL[role].toLowerCase()} to ${id}`); renderMain(false); toast(t("toast.accessGranted")); return;
  }
  else if(a==="example" && spine().samples){ const patch=spine().samples.fill(S); const st=stamp(); queuePatch(CUR,Object.assign(patch,st)); writeLog(CUR,"Example data filled in"); renderProject(false); toast(t("toast.exampleFilled")); }
  else if(a==="archive"){ if(!canOwn(S)){ toast(t("toast.ownerArchive")); return; } const v=!S.archived; S.archived=v; queuePatch(CUR,Object.assign({archived:v},stamp())); writeLog(CUR,v?"Archived":"Restored"); renderMain(false); toast(v?t("toast.archived"):t("toast.restored")); }
  else if(a==="delete"){ if(!canOwn(S)){ toast(t("toast.ownerDelete")); return; } openDeleteDialog(); }
  else if(a==="newreview"){ const k=spine().reviewGateId(); if(!k) return; const now=new Date().toISOString(); const patch={gates:{[k]:{date:TODAY(),signedBy:ME.id||null,signedAt:now}}}; deepMerge(S,patch); queuePatch(CUR,Object.assign(patch,stamp())); const title=(spine().gates().find(x=>x.id===k)||{title:k}).title; writeLog(CUR,`${title}: periodic review recorded (${S.gates[k].decision})`); renderRail(); renderMain(false); toast(t("toast.reviewRecorded")); }
  else if(a==="dl-html"){ download(`${slug(S.meta.solution)}-${spine().fileSuffix}.html`, exportHTML()); noteExport(ExportFormat.HTML); }
  else if(a==="dl-md"){ download(`${slug(S.meta.solution)}-${spine().fileSuffix}.md`, exportMD()); noteExport(ExportFormat.MD); }
  else if(a==="dl-json"){ download(`${slug(S.meta.solution)}-${spine().fileSuffix}.json`, JSON.stringify(projectJSON(S),null,2)); noteExport(ExportFormat.JSON); }
  else if(a==="dl-pdf"){ exportPDF(); noteExport(ExportFormat.PDF); }
  else if(a==="print"){ window.print(); noteExport(ExportFormat.PDF); }
});
document.addEventListener("submit",async e=>{
  if(e.target.id!=="newform") return; e.preventDefault();
  const name=document.getElementById("newname").value.trim(); if(!name){ document.getElementById("newname").focus(); return; }
  const id=await createProject(blankProject(name),"Project created");
  if(id){ const wait=()=>PROJECTS.has(id)?openProject(id,"setup"):setTimeout(wait,120); wait(); }
});
document.addEventListener("input",e=>{
  const el=e.target;
  if(el.id===HeaderControl.LANGUAGE){ setLocale(el.value); relocalize(); return; }
  if(el.id===SearchField.QUERY){ UI.q=el.value; updateDashboard(); return; }
  if(el.id===SearchField.ALL_TEXT){
    UI.qAll=el.checked;
    const q=document.getElementById(SearchField.QUERY);
    if(q) q.placeholder = t(UI.qAll ? SEARCH_HINT.ALL_TEXT : SEARCH_HINT.NAMES);
    // Names are what people search for, and the lists hold ids: learn the names first.
    if(UI.qAll) warmNames([...PROJECTS.values()].flatMap(idsOfProject)).then(updateDashboard);
    updateDashboard(); return;
  }
  if(el.dataset && el.dataset.md) updateMdPreview(el);
  const p=el.dataset && el.dataset.bind; if(!p || RO || !S) return;
  // Mark this as live typing so the changelog waits for the field to be
  // finished rather than describing each keystroke.
  setTyping(true);
  try{ edit(p, el.value); } finally { setTyping(false); }
  if(p.startsWith("meta.")||p.startsWith("card.")||p.startsWith("metrics.")) renderPanel();
  if(p==="meta.solution"||p.startsWith("card.")) renderRail();
});
/* A text edit is finished when focus leaves the field. Capture phase, because
   `blur` does not bubble. This is what turns a sentence into one changelog
   entry regardless of how long the typist paused in the middle of it. */
document.addEventListener("blur", e=>{
  const el=e.target;
  const p=el && el.dataset && el.dataset.bind;
  if(p && CUR) flushChanges(CUR, p);
}, true);

document.addEventListener("change",e=>{
  const el=e.target;
  if(frameworkChange(el)) return;
  if(el.dataset && el.dataset.bind && S && !RO && (el.tagName==="SELECT" || el.type==="date")){
    edit(el.dataset.bind, el.value);   // discrete: edit() flushes it already
    renderPanel(); renderRail();
  }
});
/* An edit still in the buffer when the page goes away would never be
   described. pagehide covers closing, navigating and mobile backgrounding;
   visibilitychange catches a tab switch, which is a common way to stop
   mid-sentence. */
addEventListener("pagehide", flushAllChanges);
addEventListener("visibilitychange", ()=>{ if(document.visibilityState==="hidden") flushAllChanges(); });

document.getElementById("brandBtn").onclick=()=>goHome();
document.getElementById("goReport").onclick=()=>{ if(S) go(spine().reportViewId); };
document.getElementById("importFile").onchange=async e=>{
  const f=e.target.files[0]; if(!f) return;
  try{
    const j=JSON.parse(await f.text()); const st=j._state||j;
    if(!st.meta||!st.items) throw new Error("not a review");
    const p=normalize(Object.assign(blankProject(st.meta.solution), clone(st))); delete p.id;
    Object.values(p.items).forEach(x=>{ if(x) delete x._open; }); delete p.view;
    p.updatedAt=new Date().toISOString(); p.updatedBy=ME.id||null;
    if(!isOwnRecord(p)){ toast(t("toast.foreignRecord",{name:String(recordFramework(p)).slice(0,64)})); e.target.value=""; return; }
    const id=await createProject(p,"Imported from a JSON export");
    if(id) toast(t("toast.imported"));
  }catch(err){ toast(t("toast.badImport")); }
  e.target.value="";
};
const panel=document.getElementById("panel");
// A primary with no side panel (a build of other frameworks) has none to land on.
panel.hidden=!hasPanel();
document.getElementById("openPreview").onclick=()=>{ renderPanel(); panel.classList.add("open"); document.getElementById("closePreview").focus(); };
document.getElementById("closePreview").onclick=()=>panel.classList.remove("open");
document.addEventListener("keydown",e=>{ if(e.key==="Escape") panel.classList.remove("open"); });
window.addEventListener("pagehide",()=>{ Object.keys(pending).forEach(flush); });

let toastT;
function toast(msg,ms){ const t=document.getElementById("toast"); t.textContent=msg; t.classList.add("show"); clearTimeout(toastT); toastT=setTimeout(()=>t.classList.remove("show"),ms||2400); }
