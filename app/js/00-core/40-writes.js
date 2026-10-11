/* ============================================================
   Writes
   ============================================================ */
function setSaved(t){ document.getElementById("saved").textContent=t; }
/* What a save tells the user about where it went. Keyed by Mode, so adding a
   mode without deciding its wording is a gap the test in test_boot_storage.py
   finds, and an unknown mode falls back to a label that claims nothing rather
   than to one that claims the wrong place. Only LOCAL may say "browser". */
const SAVED_LABEL = Object.freeze({   // catalog keys: the text is the reader's language
  [Mode.LOCAL]: "saved.local",
  [Mode.API]: "saved.api",
});
function savedLabel(mode){ return t(SAVED_LABEL[mode] || "saved.generic"); }
function stamp(extra){ return Object.assign({updatedAt:new Date().toISOString(), updatedBy:ME.id||null}, extra||{}); }
function queuePatch(pid,patch){
  if(RO) return;
  deepMerge(pending[pid]||(pending[pid]={}), patch);
  if(S && pid===CUR && STORED.has(S)) deepMerge(STORED.get(S), patch);  // see storedRecord()
  setSaved(t("saved.saving"));
  clearTimeout(timers[pid]); timers[pid]=setTimeout(()=>flush(pid),550);
}
/* Send one project's pending patch.

   The patch is REMOVED from `pending` before the request and put back if the
   request fails, rather than being deleted outright. It used to be deleted up
   front and restored for exactly one error code on exactly the first attempt,
   so a 403, a 404, or a second consecutive outage discarded the user's typing
   while telling them to "try again" -- with nothing left to try again with.

   `attempt` counts retries for backoff. Anything still pending when this
   returns is merged on top, so an edit made DURING the request is not lost
   either. */
const MAX_SAVE_ATTEMPTS = 6;

async function flush(pid,attempt){
  if(flushing[pid]){ clearTimeout(timers[pid]); timers[pid]=setTimeout(()=>flush(pid,attempt),300); return; }
  const p=pending[pid]; if(!p) return; delete pending[pid];
  flushing[pid]=true;
  const restore = ()=>{ pending[pid] = deepMerge(p, pending[pid]||{}); };
  try{
    await STORE.update(pid,p);
    if(!pending[pid]) setSaved(savedLabel(MODE));
  }
  catch(e){
    const c=e&&e.code;
    const n=(attempt||0)+1;

    // Transient: keep the edit and come back for it.
    if(e && e.outcome===SaveOutcome.RETRY && n < MAX_SAVE_ATTEMPTS){
      restore();
      flushing[pid]=false;
      setSaved(t("saved.retrying"));
      setTimeout(()=>flush(pid,n), Math.min(8000, 400*Math.pow(2,n)) + Math.random()*400);
      return;
    }

    // Permanent, and about permission rather than connectivity. Keep the
    // edit anyway: the user can still see and copy what they wrote, which
    // they cannot do if we drop it.
    if(e && e.outcome===SaveOutcome.REFUSED){
      // The server is up and said no (#186). The same bytes would be refused
      // again, so there is no retry; keep the edit so it can be corrected.
      restore();
      toast(e.detail ? t("toast.saveRefused",{detail:e.detail}) : t("toast.saveRefusedBare"), 8000);
      setSaved(t("saved.refused"));
    }
    else if(c==="permission_denied" || c==="invalid_argument" || c==="revoked"){
      restore();
      setReadOnly(true);
      toast(t("toast.accessChanged"));
      setSaved(t("saved.noLongerEditable"));
    }
    else if(c==="not_found"){
      toast(t("toast.projectGone"));
      setSaved(t("saved.not"));
    }
    else if(c==="quota_exceeded"){
      restore();
      toast(t("toast.full"));
      setSaved(t("saved.full"));
    }
    else {
      restore();
      toast(t("toast.saveFailed"));
      setSaved(t("saved.not"));
    }
  } finally { flushing[pid]=false; }
}
function patchFromPath(path,val){
  const ks=path.split("."); const out={}; let o=out;
  if(!ks.every(safeKey)) return out;
  for(let i=0;i<ks.length-1;i++){ o=o[ks[i]]={}; } o[ks[ks.length-1]]=val; return out;
}
function setLocal(path,val){
  const ks=path.split("."); let o=S;
  if(!ks.every(safeKey)) return;
  for(let i=0;i<ks.length-1;i++){ if(o[ks[i]]==null||typeof o[ks[i]]!=="object") o[ks[i]]={}; o=o[ks[i]]; }
  o[ks[ks.length-1]]=val;
}
/* Every typed, pasted or programmatic write of a field comes through here, so this
   is where credentials in an address are removed (R-70): before the value is
   stored, queued for the server or described in the history. Returns the value
   stored, so a text field can show what it holds. */
function edit(path,val){
  if(!String(path).split(".").every(safeKey)) return val;  // never a write to a prototype
  const cleaned = scrubAddressCredentials(val && typeof val === "object" ? clone(val) : val);
  val = cleaned.value;
  if(cleaned.removed) toast(t("toast.credsRemoved"));
  const before = path.startsWith("metrics.") ? clone(S.metrics) : clone(get(path));
  setLocal(path,val);
  let patch;
  if(path.startsWith("metrics.")) patch={metrics:clone(S.metrics), cardUpdatedAt:new Date().toISOString()};
  else { patch=patchFromPath(path,val); if(path.startsWith("card.")) patch.cardUpdatedAt=new Date().toISOString(); }
  if(patch.cardUpdatedAt) S.cardUpdatedAt=patch.cardUpdatedAt;
  const st=stamp(); S.updatedAt=st.updatedAt; S.updatedBy=st.updatedBy;
  queuePatch(CUR, Object.assign(patch,st));
  bufferChange(CUR, path, before);
  // Typing is the ONLY continuous edit: it arrives one character at a time
  // and is not finished until focus leaves. Everything else -- a status
  // button, a dropdown, a date, a programmatic change -- is complete the
  // moment it happens, so it is described straight away.
  //
  // Expressed as "flush unless typing" rather than by listing the discrete
  // controls, because a list would need extending every time a control is
  // added, and the one that got missed would silently stop logging.
  if(!TYPING) flushChanges(CUR, path);
  return val;
}

/* Changelog coalescing.

   One entry per completed edit, not per keystroke and not per save.

   Two earlier versions were wrong in instructive ways. Logging inside edit()
   wrote one entry per character: forty entries to record one sentence, burying
   the record it exists to document. Logging at save-flush was better but still
   split a sentence in two whenever the typist paused longer than the 550ms
   save debounce -- which is just "stopped to think mid-sentence", a completely
   normal thing to do.

   So the trigger is the edit being FINISHED, which for a text field means
   focus leaving it. Saving still debounces independently: data is written
   while you type, and the changelog describes what you wrote once you are
   done. The two concerns were conflated; they are now separate.

   Discrete controls -- a status button, a dropdown, a date picker -- are
   complete the moment they change, so they flush immediately. */
const changeBuf = {};

/* True only while an `input` event from a text field is being handled.
   Set around the edit() call in the input handler, nowhere else. */
let TYPING = false;
const setTyping = v => { TYPING = !!v; };

function bufferChange(pid, path, before){
  if(RO) return;
  const buf = changeBuf[pid] || (changeBuf[pid] = {});
  // Keep the earliest value only; later keystrokes are the same edit.
  if(!(path in buf)) buf[path] = before;
}

/* Write the entry for one path, or for every buffered path when no path is
   given. Called on blur, when leaving a view, and before the page unloads --
   anywhere an in-progress edit stops being in progress. */
function flushChanges(pid, path){
  const buf = changeBuf[pid];
  if(!buf) return;
  const paths = path ? (path in buf ? [path] : []) : Object.keys(buf);
  for(const key of paths){
    const before = buf[key];
    delete buf[key];
    const now = key.startsWith("metrics.") ? clone(S && S.metrics) : (S ? get(key) : undefined);
    logChange(pid, key, before, now, storedRecord(S));
  }
  if(!Object.keys(buf).length) delete changeBuf[pid];
}

/* Everything in flight, for every project. */
function flushAllChanges(){
  Object.keys(changeBuf).forEach(pid => flushChanges(pid));
}
function saveMetrics(){
  const now=new Date().toISOString(); S.cardUpdatedAt=now; const st=stamp(); Object.assign(S,st);
  queuePatch(CUR, Object.assign({metrics:clone(S.metrics), cardUpdatedAt:now}, st));
}
/* Append one audit entry.

   This used to end in `.catch(()=>{})`. A log that can silently lose entries
   while continuing to look complete is worse than no log: a reviewer cannot
   tell a quiet period from a dropped write, and the whole point of the record
   is that someone will rely on it a year later.

   So a failure is retried, and a failure that survives the retries is said
   out loud rather than swallowed. The entry is kept in `logQueue` across
   retries so a transient outage does not lose it. */
const logQueue = [];
let logDraining = false;

function writeLog(pid,text){
  if(RO) return;
  enqueueLog(pid, {at:new Date().toISOString(), by:ME.id||null, text});
}

/* The one way an audit entry gets written. Every caller -- a checkpoint note,
   a created project, a per-edit changelog entry -- goes through here, so a fix
   to how failures are handled lands everywhere at once. It did not: logChange()
   kept its own copy ending in `.catch(()=>{})` after this one was fixed, and an
   edit's history could vanish without a word (#45). */
function enqueueLog(pid, entry){
  if(RO) return;
  logQueue.push({pid, entry, tries:0});
  drainLog();
}

async function drainLog(){
  if(logDraining || !logQueue.length) return;
  logDraining = true;
  try{
    while(logQueue.length){
      const item = logQueue[0];
      try{
        await STORE.log(item.pid, item.entry);
        logQueue.shift();
      }catch(e){
        const code = e && e.code;
        // A permission failure or a project that is gone will not succeed on
        // a retry. Drop the item, but say so: the user just did something the
        // record now does not show.
        if(code === "permission_denied" || code === "not_found"){
          logQueue.shift();
          setSaved(t("saved.auditNot"));
          toast(t("toast.auditFailed"));
          continue;
        }
        if(++item.tries >= 5){
          logQueue.shift();
          setSaved(t("saved.auditNot"));
          toast(t("toast.auditFailed"));
          continue;
        }
        // Back off and let a later call pick it up.
        logDraining = false;
        setTimeout(drainLog, 400 * item.tries + Math.random() * 300);
        return;
      }
    }
  } finally {
    logDraining = false;
  }
}

/* Entries still in flight, for the unload path. */
const pendingLogCount = () => logQueue.length;

async function createProject(data,logText){
  if(RO) return null;
  // A new record would follow rules this page does not show (D-83).
  if(rulesBlockWrites()){ toast(t("rules.refused")); return null; }
  const id=newId();
  scrubAddressCredentials(data);  // the callers that tell the person do it first; this is the net (R-70)
  try{
    await STORE.create(id,data);
    // Goes through the same queue as every other entry, so a transient
    // failure here is retried rather than dropped. See writeLog().
    // The hash is the record's with its id, as every later entry, the setup page
    // and the exports compute it; without the id it was a different number for
    // the same record (#177).
    enqueueLog(id, {
      at:new Date().toISOString(), by:ME.id||null,
      text:logText||"Project created", hash:contentHash({...data, id})});
    return id;
  }
  catch(e){ toast(e&&e.code==="quota_exceeded"?t("toast.full"):t("toast.createFailed")); return null; }
}
