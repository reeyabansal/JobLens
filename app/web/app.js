const $ = (s, r = document) => r.querySelector(s);
console.log("JobHunt UI build v3 loaded");
const api = (p, o) => fetch(p, o).then(r => { if (!r.ok) return r.json().then(e => Promise.reject(e)); return r.json(); });

let state = { status: "all", order: "score", selected: null, statuses: [] };

function toast(msg, ms = 2200) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(t._t); t._t = setTimeout(() => (t.hidden = true), ms);
}

function scoreColor(s) {
  if (s == null) return "var(--faint)";
  if (s < 40) return "var(--red)";
  if (s < 60) return "var(--amber)";
  return "var(--green)";
}

async function loadConfig() {
  try {
    const c = await api("/api/config");
    window.CAPS = c.capabilities || {};
    const f = c.filters || {};
    const kw = (f.role_keywords || f.keywords || []).join(", ");
    const loc = (f.location && (f.location.allowed_countries || []).join("/")) || "any";
    $("#filterSummary").textContent =
      `${kw || "any role"}  ·  ${loc}  ·  start ≥ ${f.earliest_start || "any"}`;
    const flag = $("#resumeFlag");
    if (c.resume_loaded) { flag.textContent = "resume ✓"; flag.className = "resume-flag ok"; }
    else { flag.textContent = "no resume"; flag.className = "resume-flag missing"; }
  } catch { /* ignore */ }
}

async function loadJobs() {
  const data = await api(`/api/jobs?status=${state.status}&order=${state.order}`);
  state.statuses = data.statuses;
  renderStatusFilter(data.jobs);
  renderList(data.jobs);
}

function renderStatusFilter(jobs) {
  const wrap = $("#statusFilter");
  if (wrap.dataset.built) return;
  const opts = ["all", ...state.statuses];
  wrap.innerHTML = opts.map(s =>
    `<button data-s="${s}" class="${s === state.status ? "active" : ""}">${s.replace("_", " ")}</button>`
  ).join("");
  wrap.dataset.built = "1";
  wrap.querySelectorAll("button").forEach(b => b.onclick = () => {
    state.status = b.dataset.s;
    wrap.querySelectorAll("button").forEach(x => x.classList.toggle("active", x === b));
    loadJobs();
  });
}

function renderList(jobs) {
  const list = $("#jobList");
  if (!jobs.length) {
    list.innerHTML = `<div style="padding:24px;color:var(--faint);text-align:center">
      No jobs yet. Hit <b>Run ingestion</b> to pull postings.</div>`;
    return;
  }
  list.innerHTML = jobs.map(j => {
    const s = j.ats_score;
    const chip = s == null
      ? `<span class="score-chip none">—</span>`
      : `<span class="score-chip" style="color:${scoreColor(s)};background:${scoreColor(s)}18">${Math.round(s)}%</span>`;
    const loc = j.location || (j.remote ? "Remote" : "—");
    const start = j.start_date || j.start_year || "start n/a";
    return `<div class="job-row ${j.id === state.selected ? "selected" : ""}" data-id="${j.id}">
      <div>
        <div class="jr-title">${esc(j.title)}</div>
        <div class="jr-company">${esc(j.company)}</div>
      </div>
      ${chip}
      <div class="jr-meta">
        <span class="status-pill st-${j.status}">${j.status.replace("_", " ")}</span>
        <span>${esc(loc)}</span><span>${esc(String(start))}</span><span>${j.source}</span>
      </div>
    </div>`;
  }).join("");
  list.querySelectorAll(".job-row").forEach(r =>
    r.onclick = () => selectJob(r.dataset.id));
}

async function selectJob(id) {
  state.selected = id;
  location.hash = `#/job/${id}`;
  document.querySelectorAll(".job-row").forEach(r =>
    r.classList.toggle("selected", r.dataset.id === id));
  const job = await api(`/api/job/${id}`);
  renderDetail(job);
}

function renderDetail(job) {
  $("#emptyState").hidden = true;
  const d = $("#detail");
  d.hidden = false;
  const loc = job.location || (job.remote ? "Remote" : "—");
  const start = job.start_date || job.start_year || "n/a";
  const statusOpts = state.statuses.map(s =>
    `<option value="${s}" ${s === job.status ? "selected" : ""}>${s.replace("_", " ")}</option>`).join("");

  d.innerHTML = `
    <h1>${esc(job.title)}</h1>
    <div class="company-line">${esc(job.company)}</div>
    <div class="meta-line">
      <span>📍 ${esc(loc)}</span><span>🗓 start ${esc(String(start))}</span>
      <span>src ${job.source}</span><span>id ${job.id.slice(0, 8)}</span>
    </div>
    <div class="detail-controls">
      <label style="color:var(--muted);font-size:12.5px">Status</label>
      <select id="statusSelect">${statusOpts}</select>
      <button class="btn btn-primary" id="analyzeBtn">
        ${job.analysis ? "Re-analyze score" : "Analyze score"}</button>
      <button class="btn btn-ghost" id="deepDiveBtn" title="Ask Gemini for concrete resume edits (requires GEMINI_API_KEY)">Deep dive ✨</button>
      <button class="btn btn-danger" id="deleteBtn">Delete</button>
      <a class="ext-link" href="${job.url}" target="_blank" rel="noopener">Open posting ↗</a>
    </div>
    <details class="jd-editor">
      <summary>Job description &nbsp;<span class="jd-hint">paste the full JD if the posting is thin or auto-fetch missed it</span></summary>
      <textarea id="jdText" class="jd-text" placeholder="Paste the full job description here…">${esc(job.description || "")}</textarea>
      <div class="jd-actions">
        <button class="btn btn-primary" id="saveJdBtn">Save &amp; analyze this text</button>
        <span class="jd-count" id="jdCount">${(job.description || "").length} chars</span>
      </div>
    </details>
    <div id="analysisArea"></div>`;

  $("#statusSelect").onchange = async (e) => {
    await api(`/api/job/${job.id}/status`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: e.target.value }),
    });
    toast(`Status → ${e.target.value.replace("_", " ")}`);
    loadJobs();
  };
  $("#analyzeBtn").onclick = () => runAnalyze(job.id, $("#analyzeBtn"));
  $("#deleteBtn").onclick = () => deleteJob(job);
  $("#deepDiveBtn").onclick = () => runDeepDive(job.id, $("#deepDiveBtn"));
  $("#jdText").oninput = (e) => { $("#jdCount").textContent = `${e.target.value.length} chars`; };
  $("#saveJdBtn").onclick = async (e) => {
    const text = $("#jdText").value.trim();
    if (!text) { toast("Paste a description first"); return; }
    e.target.disabled = true; e.target.innerHTML = `<span class="spin"></span> saving…`;
    await api(`/api/job/${job.id}/description`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description: text }),
    });
    // analyze against exactly this text — no auto-refetch overwrite
    const a = await api(`/api/job/${job.id}/analyze?refetch=false`, { method: "POST" });
    const fresh = await api(`/api/job/${job.id}`);
    renderAnalysis(fresh, a);
    loadJobs();
    e.target.disabled = false; e.target.innerHTML = "Save &amp; analyze this text";
    toast(`Analyzed pasted JD · match ${Math.round(a.score)}%`);
  };

  if (job.analysis) renderAnalysis(job, job.analysis);
}

async function deleteJob(job) {
  if (!confirm(`Delete "${job.title}" at ${job.company}?\n\nIt won't be pulled back in on future ingests.`))
    return;
  await api(`/api/job/${job.id}`, { method: "DELETE" });
  state.selected = null;
  location.hash = "";
  $("#detail").hidden = true;
  $("#emptyState").hidden = false;
  loadJobs();
  toast("Job deleted");
}

async function runAnalyze(id, btn) {
  btn.disabled = true;
  btn.innerHTML = `<span class="spin"></span> analyzing…`;
  try {
    const a = await api(`/api/job/${id}/analyze`, { method: "POST" });
    const job = await api(`/api/job/${id}`);
    renderAnalysis(job, a);
    loadJobs();
    toast(`Match score ${Math.round(a.score)}%`);
  } catch (e) {
    toast(e.detail || "Analysis failed");
    btn.disabled = false; btn.textContent = "Analyze against my resume";
  }
}

function renderAtsAudit(ats) {
  if (!ats) return "";
  const bd = ats.breakdown || {};
  const labels = {
    keyword_match: "Keyword match", title_match: "Title match",
    education_match: "Education", experience_match: "Experience",
    format_compliance: "Format", action_verbs_grammar: "Action verbs",
    readability: "Readability",
  };
  const bars = Object.keys(labels).filter(k => k in bd).map(k => {
    const v = Math.round(bd[k] || 0);
    const c = v < 40 ? "var(--red)" : v < 60 ? "var(--amber)" : "var(--green)";
    return `<div class="audit-row"><span class="audit-k">${labels[k]}</span>
      <span class="audit-bar"><span style="width:${v}%;background:${c}"></span></span>
      <span class="audit-v">${v}</span></div>`;
  }).join("");
  const recs = (ats.recommendations || []).slice(0, 6).map(r => `<li>${esc(r)}</li>`).join("");
  const grade = ats.grade ? `<span class="audit-grade">grade ${esc(ats.grade)}</span>` : "";
  return `
    <div class="sec-title">Resume ATS audit <span class="audit-src">ats-resume-scorer</span></div>
    <div class="audit">
      <div class="audit-head">Overall resume score <b>${Math.round(ats.overall_score || 0)}</b>/100 ${grade}
        <span class="audit-note">structure &amp; format audit of the resume itself — distinct from the JD keyword match above</span></div>
      <div class="audit-bars">${bars}</div>
      ${recs ? `<div class="audit-recs"><b>Fix-ups:</b><ul>${recs}</ul></div>` : ""}
    </div>`;
}

async function runDeepDive(jobId, btn) {
  const area = $("#deepDiveArea");
  if (!area) { toast("Run Analyze score first"); return; }
  btn.disabled = true; btn.innerHTML = `<span class="spin"></span> thinking…`;
  area.innerHTML = `<div class="sec-title">Gemini deep dive</div>
    <div class="deepdive loading">Gemini is reading the JD and your resume…</div>`;
  try {
    const r = await api(`/api/job/${jobId}/deepdive`, { method: "POST" });
    if (r.ok) {
      area.innerHTML = `<div class="sec-title">Gemini deep dive
        <span class="audit-src">${esc(r.model || "gemini")}</span></div>
        <div class="deepdive">${mdToHtml(r.markdown || "")}</div>`;
      toast("Deep dive ready");
    } else {
      area.innerHTML = `<div class="sec-title">Gemini deep dive</div>
        <div class="deepdive hint">⚠️ ${esc(r.hint || r.error || "unavailable")}</div>`;
    }
  } catch (e) {
    area.innerHTML = `<div class="sec-title">Gemini deep dive</div>
      <div class="deepdive hint">⚠️ ${esc(e.detail || "request failed")}</div>`;
  }
  btn.disabled = false; btn.innerHTML = "Deep dive ✨";
}

// very small, safe markdown → HTML (escapes first, then adds structure)
function mdToHtml(md) {
  let h = esc(md);
  h = h.replace(/^### (.*)$/gm, "<h4>$1</h4>")
       .replace(/^## (.*)$/gm, "<h3>$1</h3>")
       .replace(/^# (.*)$/gm, "<h3>$1</h3>")
       .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
       .replace(/`([^`]+)`/g, "<code>$1</code>")
       .replace(/^\s*[-*] (.*)$/gm, "<li>$1</li>");
  h = h.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, "<ul>$1</ul>");
  h = h.replace(/\n{2,}/g, "</p><p>").replace(/\n/g, "<br>");
  return `<p>${h}</p>`;
}

function renderAnalysis(job, a) {
  const col = scoreColor(a.score);
  const matched = (a.matched_keywords || []).map(k =>
    `<span class="chip matched">${esc(k)}</span>`).join("") || `<span class="no-spot">none detected</span>`;

  const tag = (sec) =>
    sec === "required" ? `<span class="gap-req">required</span>`
    : sec === "preferred" ? `<span class="gap-pref">nice to have</span>` : "";

  const gaps = (a.missing_keywords || []).map((m, i) => {
    const spots = (m.spots || []).length
      ? m.spots.map(s => `<div class="spot">
          <div class="spot-text">${esc(s.bullet)}</div>
          <div class="spot-sim">closeness
            <span class="sim-bar"><span class="sim-fill" style="width:${Math.round(s.similarity * 100)}%"></span></span>
            ${Math.round(s.similarity * 100)}%</div></div>`).join("")
      : `<div class="no-spot">No close bullet — this may be a genuine gap, not just wording.</div>`;
    return `<div class="gap gap-${m.section}" data-gap>
      <div class="gap-head">
        <span class="gap-rank">${String(i + 1).padStart(2, "0")}</span>
        <span class="gap-kw">${esc(m.keyword)}</span>
        ${tag(m.section)}
        <span class="gap-imp">
          <span class="imp-bar"><span class="imp-fill" style="width:${Math.round(m.importance * 100)}%"></span></span>
          <span class="gap-caret">▶</span>
        </span>
      </div>
      <div class="gap-body">${spots}</div>
    </div>`;
  }).join("") || `<span class="no-spot">No missing keywords — strong coverage.</span>`;

  const reqLine = a.required_total
    ? ` · <b>${a.required_matched}/${a.required_total}</b> required keywords covered`
    : "";
  const srcBadge = a.jd_source === "full posting"
    ? `<span class="jd-badge ok" title="analyzed against the full job posting">full JD</span>`
    : a.jd_source === "manual paste"
    ? `<span class="jd-badge ok" title="analyzed against the description you pasted">pasted JD</span>`
    : `<span class="jd-badge" title="only a short listing summary was available — paste the full JD or open the posting for a sharper read">listing only</span>`;

  $("#analysisArea").innerHTML = `
    <div class="score-block">
      <div class="score-head">
        <span class="score-num" style="color:${col}">${Math.round(a.score)}<span style="font-size:16px">%</span></span>
        <span class="score-label">ATS match${reqLine} ${srcBadge}</span>
      </div>
      <div class="meter"><div class="meter-fill" style="width:${a.score}%;background:${col}"></div></div>
      <div class="meter-ticks"><span>0 · filtered out</span><span>40 · borderline</span><span>60 · likely passes</span><span>100</span></div>
    </div>

    <div class="sec-title">Already covered</div>
    <div class="chips">${matched}</div>

    <div class="sec-title">Missing keywords · ranked · click to see where they fit</div>
    <div class="ledger">${gaps}</div>

    ${renderAtsAudit(a.ats)}

    <div id="deepDiveArea"></div>

    <div class="prompt-block">
      <div class="sec-title">Claude tailoring prompt</div>
      <div class="prompt-toggles">
        <label><input type="checkbox" id="tglResume" checked> include resume</label>
        <label><input type="checkbox" id="tglRules" checked> include rules</label>
        <span class="prompt-hint">Uncheck both if pasting into a Claude Project that already holds them.</span>
      </div>
      <div class="prompt-actions">
        <button class="btn btn-primary" id="copyPromptBtn">Copy prompt</button>
        <button class="btn btn-ghost" id="showPromptBtn">Show / edit</button>
      </div>
      <textarea class="prompt-out" id="promptOut" hidden placeholder="Prompt appears here…"></textarea>
    </div>`;

  $("#analysisArea").querySelectorAll("[data-gap]").forEach(g =>
    $(".gap-head", g).onclick = () => g.classList.toggle("open"));

  const fetchPrompt = () => api(
    `/api/job/${job.id}/prompt?include_resume=${$("#tglResume").checked}&include_rules=${$("#tglRules").checked}`
  ).then(r => r.prompt);

  $("#copyPromptBtn").onclick = async () => {
    const p = await fetchPrompt();
    try { await navigator.clipboard.writeText(p); toast("Prompt copied — paste into Claude"); }
    catch { $("#promptOut").hidden = false; $("#promptOut").value = p; toast("Copy blocked — selecting text"); $("#promptOut").select(); }
  };
  $("#showPromptBtn").onclick = async () => {
    const ta = $("#promptOut");
    ta.hidden = !ta.hidden;
    if (!ta.hidden) ta.value = await fetchPrompt();
  };
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// ingestion
$("#ingestBtn").onclick = async (e) => {
  e.target.disabled = true; e.target.innerHTML = `<span class="spin"></span> ingesting…`;
  try {
    await api("/api/ingest", { method: "POST" });
    toast("Ingestion running — refreshing in 6s");
    setTimeout(() => { loadJobs(); loadConfig();
      e.target.disabled = false; e.target.textContent = "Run ingestion"; }, 6000);
  } catch {
    e.target.disabled = false; e.target.textContent = "Run ingestion";
    toast("Ingestion failed to start");
  }
};

// add job (manual)
const addModal = $("#addModal");
function setModal(open) {              // toggle both attribute and inline display
  addModal.hidden = !open;
  addModal.style.display = open ? "flex" : "none";
}
setModal(false);                       // force-hidden on load, even if CSS is stale
$("#addJobBtn").onclick = () => { setModal(true); $("#mTitle").focus(); };
$("#mCancel").onclick = () => setModal(false);
addModal.onclick = (e) => { if (e.target === addModal) setModal(false); };
$("#mSave").onclick = async (e) => {
  const body = {
    title: $("#mTitle").value.trim(), company: $("#mCompany").value.trim(),
    url: $("#mUrl").value.trim(), location: $("#mLocation").value.trim(),
    description: $("#mDesc").value.trim(), remote: $("#mRemote").checked,
  };
  if (!body.title || !body.company) { toast("Title and company are required"); return; }
  e.target.disabled = true; e.target.innerHTML = `<span class="spin"></span> adding…`;
  try {
    const r = await api("/api/jobs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setModal(false);
    ["mTitle", "mCompany", "mUrl", "mLocation", "mDesc"].forEach(id => $("#" + id).value = "");
    $("#mRemote").checked = false;
    await loadJobs();
    toast("Job added");
    selectJob(r.id);
  } catch (err) {
    toast(err.detail || "Could not add job");
  }
  e.target.disabled = false; e.target.textContent = "Add job";
};

// prune stale / non-matching jobs
$("#pruneBtn").onclick = async (e) => {
  if (!confirm("Remove every stored job that no longer matches your current filters?\n\n(Managerial, off-target, or expired roles pulled in under older settings. They won't be re-ingested.)"))
    return;
  e.target.disabled = true; e.target.innerHTML = `<span class="spin"></span> pruning…`;
  try {
    const r = await api("/api/prune", { method: "POST" });
    toast(r.removed ? `Removed ${r.removed} stale job${r.removed === 1 ? "" : "s"}` : "Nothing to prune — all jobs match");
    loadJobs();
  } catch { toast("Prune failed"); }
  e.target.disabled = false; e.target.textContent = "Prune stale";
};

$("#orderSelect").onchange = (e) => { state.order = e.target.value; loadJobs(); };

// deep-link support (#/job/{id})
window.addEventListener("hashchange", () => {
  const m = location.hash.match(/#\/job\/(.+)/);
  if (m && m[1] !== state.selected) selectJob(m[1]);
});

(async function init() {
  await loadConfig();
  await loadJobs();
  const m = location.hash.match(/#\/job\/(.+)/);
  if (m) selectJob(m[1]);
})();