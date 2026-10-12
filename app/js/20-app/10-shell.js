/* ============================================================
   App shell: rail and routing
   Builds the step rail from whatever views the active frameworks
   contribute, and dispatches rendering back to the framework that
   owns the current view. Nothing here names CHAI or OPTICA.
   ============================================================ */
function railRow(v) {
  const cur = UI.view === v.id ? ' aria-current="step"' : "";
  const meta = typeof v.meta === "function" ? v.meta() : (v.meta || "");
  // numHTML lets a view supply its own marker element (the checkpoint
  // diamond); glyph covers the common case of a single character.
  const num = v.numHTML ? `<span class="num">${v.numHTML}</span>`
    : v.num == null ? `<span class="num" aria-hidden="true">${esc(v.glyph || "•")}</span>`
    : `<span class="num">${esc(String(v.num))}</span>`;
  // A view that computes a state class always gets the separating space, even
  // when the class is empty this render; a view with no metaCls gets none.
  // That reproduces the markup the hand-written rail emitted exactly.
  const metaCls = v.metaCls ? ` ${esc(v.metaCls())}` : "";
  const li = `<li${v.cls ? ` class="${v.cls}"` : ""}><button data-go="${esc(v.id)}"${cur}>`
    + `${num}<span>${esc(v.label)}</span>`
    + `<span class="meta${metaCls}">${meta}</span></button></li>`;
  const sep = `<li class="sep" role="presentation"></li>`;
  return (v.sep === "before" ? sep : "") + li + (v.sep === "after" ? sep : "");
}

function renderRail() {
  const ol = document.getElementById("rail");
  const home = `<li class="home-link"><button data-home="1">`
    + `<span class="num flip-rtl" aria-hidden="true">←</span><span>${esc(t("nav.allProjects"))}</span></button></li>`
    + `<li class="sep" role="presentation"></li>`;
  ol.innerHTML = home + activeViews().map(railRow).join("");
  document.getElementById("projName").textContent = S.meta.solution || t("project.untitled");
}

function renderMain(focusTop) {
  const views = activeViews();
  const v = views.find(x => x.id === UI.view) || views[0];
  const m = document.getElementById("main");
  const fk = focusTop ? null : focusKey(document.activeElement);

  m.innerHTML = v.fw.render(v, S);

  applyRO(m);
  resolveNames(m);
  fillHold();   // a no-op unless this view has the hold section
  if (focusTop) { window.scrollTo({ top: 0 }); m.focus({ preventScroll: true }); }
  else if (fk) { const el = m.querySelector(fk); if (el) el.focus({ preventScroll: true }); }
}

function renderProject(focusTop) {
  agentLeave();
  document.body.classList.remove("home");
  renderRail(); renderMain(focusTop); renderPanel();
  // A framework with no side panel has no button to open one.
  document.getElementById("openPreview").hidden = !hasPanel();
}

function softRefresh() {
  renderRail(); renderPanel();
  if (editingInMain()) syncInputs();
  else { const y = window.scrollY; renderMain(false); window.scrollTo(0, y); }
}
