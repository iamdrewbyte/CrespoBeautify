(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  
  const form = $("#qa-form"), errBox = $("#error");

  const store = { get: k => { try { return localStorage.getItem(k) || ""; } catch { return ""; } },
                  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };

  CQ.nav("/");
  CQ.call("/api/services").then(d => {
    const sel = $("#service");
    d.services.forEach(s => sel.append(new Option(s, s)));
    const last = store.get("crespoqa.service"); if (last) sel.value = last;
    $("#ai-wrap").hidden = !d.ai_review;
  });
  $("#consultant").value = store.get("crespoqa.consultant");

  function showError(msg) { errBox.textContent = msg; errBox.hidden = !msg; if (msg) errBox.scrollIntoView({ block: "nearest" }); }

  document.querySelectorAll(".drop").forEach(d => {
    const input = $("input", d), label = $(".fname", d);
    const set = f => {
      if (!f) return;
      const dt = new DataTransfer(); dt.items.add(f); input.files = dt.files;
      label.textContent = f.name; d.classList.add("has");
    };
    d.addEventListener("click", () => input.click());
    d.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    input.addEventListener("click", e => e.stopPropagation());
    input.addEventListener("change", () => set(input.files[0]));
    ["dragenter", "dragover"].forEach(ev => d.addEventListener(ev, e => { e.preventDefault(); d.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => d.addEventListener(ev, e => { e.preventDefault(); d.classList.remove("over"); }));
    d.addEventListener("drop", e => set(e.dataTransfer.files[0]));
  });

  form.addEventListener("submit", async e => {
    e.preventDefault(); showError("");
    const fd = new FormData(form);
    if (!fd.get("technical").name || !fd.get("executive").name) return showError("Please add both the Technical and Executive reports.");
    if (!String(fd.get("consultant")).trim()) return showError("Consultant full name is required.");
    fd.set("dry_run", $("#dry_run").checked ? "true" : "false");
    fd.set("ai_review", !$("#ai-wrap").hidden && $("#ai_review").checked ? "true" : "false");
    store.set("crespoqa.consultant", String(fd.get("consultant")).trim());
    store.set("crespoqa.service", String(fd.get("service")));
    const btn = $("#submit"); btn.disabled = true; btn.textContent = "Uploading…";
    try {
      const r = await CQ.api("/api/jobs", { method: "POST", body: fd });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || "Upload failed.");
      track(body.job_id, $("#dry_run").checked);
    } catch (err) { showError(err.message); btn.disabled = false; btn.textContent = "Run QA"; }
  });

  $("#again").addEventListener("click", () => location.reload());

  function track(jobId, dry) {
    $("#form-view").hidden = true; $("#result-view").hidden = false; document.body.classList.add("results");
    $("#h-result").textContent = dry ? "Dry run in progress" : "Processing";
    const docsBox = $("#docs"), rows = {};
    CQ.call(`/api/jobs/${jobId}`).then(snap => {
      Object.entries(snap.plan).forEach(([name, steps]) => {
        const card = el("div", "box pane"), h = el("h2", "dochead"); h.append(el("span", null, name));
        const ol = el("ol", "steps"); rows[name] = { steps: {} };
        steps.forEach(s => { const li = el("li", "pending"); li.append(el("span", null, s.label));
          ol.append(li); rows[name].steps[s.key] = { li }; });
        card.append(h, ol); docsBox.append(card);
      });
      const es = new EventSource(`/api/jobs/${jobId}/events`);
      es.onmessage = m => {
        const ev = JSON.parse(m.data);
        if (ev.type === "step") {
          const s = rows[ev.doc]?.steps[ev.key]; if (!s) return;
          s.li.className = ev.state === "running" ? "running" : "done";
        } else if (ev.type === "end") { es.close(); finish(jobId, dry); }
      };
      es.onerror = () => { es.close(); finish(jobId, dry); };
    });
  }

  let finished = false;
  async function finish(jobId, dry) {
    if (finished) return; finished = true;
    const r = await CQ.api(`/api/jobs/${jobId}`);
    if (!r.ok) return showError("This job has expired.");
    const snap = await r.json(), docsBox = $("#docs");
    $("#h-result").textContent = dry ? "Dry run complete" : "Done";
    docsBox.replaceChildren();
    snap.reports.forEach(rep => {
      const card = el("div", "box pane"), h = el("div", "dochead");
      const nm = el("span", "dname", rep.input_name); nm.title = rep.input_name;
      h.append(el("span", "kicker", rep.report_type === "technical" ? "Technical" : "Executive"), nm);
      card.append(h);
      if (rep.error) card.append(el("div", "alert", rep.error));
      const ol = el("ol", "steps");
      rep.tasks.filter(t => t.key !== "prechecks" || t.warnings.length).forEach(t => {
        const li = el("li"), items = [...t.changes.map(c => ["", c]), ...t.warnings.map(w => ["w", "Warning: " + w])];
        const warn = t.warnings.length > 0;
        const count = warn ? `${t.warnings.length} to check` : t.changes.length === 1 && /^No |nothing/i.test(t.changes[0]) ? "no change" : `${t.changes.length} change${t.changes.length === 1 ? "" : "s"}`;
        if (items.length) {
          const d = el("details"); d.open = warn;
          const s = el("summary"); s.append(el("span", "t", t.title), el("span", warn ? "c warnc" : "c", count));
          const ul = el("ul", "det"); items.forEach(([c, txt]) => ul.append(el("li", c, txt)));
          d.append(s, ul); li.append(d);
        } else { const r = el("div", "row"); r.append(el("span", "t", t.title)); li.append(r); }
        ol.append(li);
      });
      card.append(ol);
      if ((rep.locations || []).length) {
        const box = el("div", "where"); box.append(el("h3", null, "Where to check by hand"));
        const tb = el("div", "wtable");
        rep.locations.forEach(L => {
          const place = L.where ? L.where : L.page ? `p. ${L.page}${L.approx ? " ≈" : ""}` : "?";
          const row = el("div", "wrow"); row.append(el("span", "wp", place));
          const tx = el("span", "wt", L.what + (L.count > 1 ? ` (${L.count}x)` : ""));
          if (L.hint) tx.append(el("em", null, `  ${L.hint}…`));
          row.append(tx); tb.append(row);
        });
        box.append(tb); card.append(box);
      }
      docsBox.append(card);
    });
    const sv = $("#saved"); sv.replaceChildren(); sv.hidden = !(snap.saved && snap.saved.length);
    (snap.saved || []).forEach(x => sv.append(el("div", x.ok ? "" : "alert",
      x.ok ? `Saved over the old file: ${x.folder}/${x.name}` : `${x.name}: ${x.error}`)));
    const dl = $("#downloads"); dl.replaceChildren();
    if (!dry && snap.outputs.length) {
      const urls = snap.outputs.map(n => [n, `/api/jobs/${jobId}/files/${encodeURIComponent(n)}`]);
      const both = el("button", "primary", urls.length > 1 ? "Download both files" : "Download file"); both.type = "button";
      both.addEventListener("click", () => urls.forEach(([n, u], i) => setTimeout(() => {
        const a = document.createElement("a"); a.href = u; a.download = n; document.body.append(a); a.click(); a.remove(); }, i * 700)));
      dl.append(both);
      urls.forEach(([n, u]) => { const a = el("a", "btn", n); a.href = u; a.title = "Download this file"; dl.append(a); });
      dl.hidden = false;
    }
    $("#again").hidden = false;
    if (snap.review_status && snap.review_status !== "off") pollReview(jobId);
  }

  const SEV = { warning: "warning", info: "ok" };
  function pollReview(jobId) {
    const box = $("#review"); box.hidden = false;
    const tick = async () => {
      let rv; try { rv = await CQ.call(`/api/jobs/${jobId}/review`); } catch { return; }
      $("#review-progress").textContent = rv.status === "error" ? rv.error : rv.status === "done" ? "" : (rv.progress || "Waiting for the model…");
      const notes = $("#review-notes"); notes.replaceChildren(); rv.notes.forEach(n => notes.append(el("div", null, n)));
      const ul = $("#findings"); ul.replaceChildren();
      if (rv.status === "done" && !rv.findings.length) ul.append(el("li", null, "No issues flagged."));
      rv.findings.forEach(f => {
        const li = el("li", "finding " + f.decision);
        const head = el("div", "fhead"); head.append(el("strong", null, `${f.check.replace("_", " ")} (${f.doc})${f.pages && f.pages.length ? ", page " + f.pages.join(", ") : ""}`), el("span", null, f.message));
        li.append(head);
        if (f.evidence) li.append(el("div", "ev", f.evidence));
        if (f.suggestion) li.append(el("div", "sug", "Suggestion: " + f.suggestion));
        const act = el("div", "row-actions");
        [["accepted", "Accept"], ["ignored", "Ignore"], ["open", "Reset"]].forEach(([d, label]) => {
          const b = el("button", "small ghost", label); b.type = "button"; b.disabled = f.decision === d;
          b.addEventListener("click", async () => { await CQ.call(`/api/jobs/${jobId}/review/${f.id}`, { method: "POST", json: { decision: d } }); tick(); });
          act.append(b); });
        li.append(act); ul.append(li);
      });
      if (rv.status === "pending" || rv.status === "running") setTimeout(tick, 2000);
    };
    tick();
  }
})();
