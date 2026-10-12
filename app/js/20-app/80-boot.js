/* ============================================================
   Boot
   ============================================================ */
applyStaticI18n(document);
{ const pick = document.getElementById(HeaderControl.LANGUAGE); if(pick) pick.innerHTML = localeOptions(); }
renderDashboardShell();
(async()=>{
  // Self-hosted backend, if this page is served by one; otherwise this is the static
  // example page and everything stays in this browser.
  const api = await detectApi("/api");

  if(api.verdict === "ok"){
    rememberApiHere();
    STORE=new ApiStore("/api"); MODE=Mode.API;
    setModeFor(MODE);
    renderDashboardShell();   // drawn before the mode was known: now with what only this mode offers (agent access)
    showScopeNotice();
    startSession(api.health);   // sign-out link and idle lock, as the server configured
    checkRetirementRules(api.health);   // does it retire records by this page's rules? (D-83)
    // Identity is established by the proxy, so the browser cannot choose it.
    try{
      const me = await fetch("/api/me",{credentials:"same-origin"}).then(r=>r.json());
      if(me && me.id){ ME.id=me.id; if(me.name) NAMES[me.id]=me.name; }
    }catch(e){}
  }
  else if(api.verdict === "denied"){
    // The server knows who you are and said no. Falling back here would
    // hand a denied user a working private workspace -- access control
    // failing open into a usable app. Stop instead.
    fatalError(t("fatal.denied.title"), t("fatal.denied.detail"),
      {mode:t("mode.noAccess"), hint:t("fatal.denied.hint")});
    return;
  }
  else if(api.verdict === "error" || api.verdict === "unreachable" || apiSeenHere()){
    // This origin has served a real API before, or something is there and
    // failing. Either way this is a deployment with a server, and browser-
    // local storage is not a substitute for it: the work would be invisible
    // to colleagues, absent from the audit log, and stranded on this machine.
    fatalError(t("fatal.unreachable.title"), t("fatal.unreachable.detail"),
      {hint:t("fatal.unreachable.hint")});
    return;
  }
  else {
    // Nothing API-shaped at this origin and none ever seen: a genuinely
    // static host. localStorage is the intended mode here.
    STORE=new LocalStore(); MODE=Mode.LOCAL;
    setModeFor(MODE);
    showStorageWarning();
  }

  document.body.classList.toggle("ro",RO);
  STORE.subscribeAll(onProjects,onDbError);
})();
