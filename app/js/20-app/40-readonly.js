/* ============================================================
   Read-only handling, mode badge
   ============================================================ */
function setMode(text,cls){ const el=document.getElementById("mode"); el.textContent=text; el.className="mode "+(cls||""); }
function setModeFor(mode){ const l=MODE_LABEL[mode]; if(l) setMode(t(MODE_LABEL_KEY[mode]),l.cls); }
function setReadOnly(v){ RO=v; document.body.classList.toggle("ro",v); if(v) setMode(t("mode.viewOnly"),"ro"); if(CUR) renderMain(false); else if(document.getElementById("plistHost")) renderDashboardShell(); }
function applyRO(root){
  // While the server's retirement rules are not this page's, no decision (D-83),
  // and each disabled button says why: the banner describes it.
  if(rulesBlockWrites()) root.querySelectorAll("[data-gate]").forEach(e=>{ e.disabled=true; e.setAttribute("aria-describedby", "rulesBanner"); });
  fillRulesBanner();   // whether "other changes still save" is true here
  if(!RO) return;
  root.querySelectorAll("input:not([type=search]),textarea,select").forEach(e=>{ if(!e.closest(".fallback")) e.disabled=true; });
  root.querySelectorAll("[data-set],[data-gate],[data-delmetric]").forEach(e=>e.disabled=true);
}

/* A blocking failure screen, for when continuing would be worse than stopping.

   There is exactly one situation that warrants this: the page is served by a
   self-hosted deployment and the app cannot reach its API, or reached it and
   was refused. The tempting alternative -- quietly switch to browser-local
   storage -- is what this replaces. It stranded work in a store colleagues
   could not see, and it handed a user the server had DENIED a fully working
   private workspace.

   So: no store, no dashboard, no editing. Say which of the two happened,
   because the remedies are completely different, and offer a retry. */
function fatalError(title, detail, opts){
  const o = opts || {};
  agentLeave();
  document.body.classList.remove("home");
  document.body.classList.add("ro");
  setMode(o.mode || t("mode.notConnected"), "ro");
  const rail = document.getElementById("rail");
  if(rail) rail.innerHTML = "";
  const m = document.getElementById("main");
  m.innerHTML = `
    <div class="empty-state" role="alert">
      <p class="eyebrow">${esc(t("fatal.eyebrow"))}</p>
      <h1 style="margin-top:4px">${esc(title)}</h1>
      <p class="lede">${esc(detail)}</p>
      ${o.hint ? `<p class="small" style="color:var(--muted);max-width:60ch">${esc(o.hint)}</p>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
        <button class="btn primary" data-act="retry-boot">${esc(t("fatal.retry"))}</button>
      </div>
    </div>`;
  const retry = m.querySelector('[data-act="retry-boot"]');
  if(retry) retry.onclick = ()=>location.reload();
}

/* Say, permanently and in the layout rather than in a toast, that this mode
   stores everything in one browser.

   The storage mode is the single most consequential thing about a deployment
   of this tool and the least visible: the UI is otherwise identical whether a
   record is on a shared, access-controlled, audited server or in localStorage
   on one laptop. A user cannot be expected to infer "do not type a patient
   identifier here" from a two-word label in the header. */
/* The server mode's statement of the same scope. It used to carry none, so the
   mode that scores best on access control and audit read as the one fit for
   patient data (#34). The scope is the same in every mode (R-49): it is a policy,
   and a mistake is corrected by the purge path, which is what it was built for. */
function showScopeNotice(){
  if(document.getElementById("scopeNotice")) return;
  const el = document.createElement("div");
  el.id = "scopeNotice";
  el.className = "storage-warning";
  el.setAttribute("role", "note");
  el.innerHTML = `<b>${esc(t("safety.scope"))}</b>
    <span class="sw-detail">${esc(t("safety.server.detail"))}</span>`;
  const header = document.querySelector("header.top");
  if(header && header.parentNode) header.parentNode.insertBefore(el, header.nextSibling);
}

function showStorageWarning(){
  if(document.getElementById("storageWarning")) return;
  const el = document.createElement("div");
  el.id = "storageWarning";
  el.className = "storage-warning";
  el.setAttribute("role", "note");
  el.innerHTML = `<b>${esc(t("safety.local.title"))}</b>
    <span class="sw-detail">${esc(t("safety.local.detail"))} ${esc(t("safety.scope"))}</span>`;
  const header = document.querySelector("header.top");
  if(header && header.parentNode) header.parentNode.insertBefore(el, header.nextSibling);
}

/* Re-render everything a reader sees in the new language: static header markup, the
   mode label, the standing notice for the mode, and the current page. */
function relocalize(){
  applyStaticI18n(document);
  const pick = document.getElementById(HeaderControl.LANGUAGE);
  if(pick) pick.innerHTML = localeOptions();
  if(RO) setMode(t("mode.viewOnly"), "ro"); else setModeFor(MODE);
  ["storageWarning", "scopeNotice"].forEach(id => {
    const el = document.getElementById(id); if(el) el.remove();
  });
  if(MODE === Mode.LOCAL) showStorageWarning();
  else if(MODE === Mode.API) showScopeNotice();
  showRulesBanner();
  if(agentPageShown()) renderAgentPage(false);   // draws it again, without the token
  else if(document.body.classList.contains("home")) renderDashboardShell();
  else if(S) renderProject(false);
}
