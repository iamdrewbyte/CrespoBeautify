(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  const form = $("#qa-form"), errBox = $("#error");
  const store = { get: k => { try { return localStorage.getItem(k) || ""; } catch { return ""; } },
                  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };
  let services = [], maxBatch = 40, aiAvailable = false;
  const files = [];                                   // {file, type, service}

  CQ.nav("/");
  CQ.call("/api/services").then(d => {
    services = d.services; maxBatch = d.max_batch || 40; aiAvailable = !!d.ai_review;
    const sel = $("#service");
    d.services.forEach(s => sel.append(new Option(s, s)));
    const last = store.get("crespoqa.service"); if (last) sel.value = last;
    renderFiles();
  });
  $("#consultant").value = store.get("crespoqa.consultant");

  function showError(msg) { errBox.textContent = msg; errBox.hidden = !msg; if (msg) errBox.scrollIntoView({ block: "nearest" }); }

  // ---------------------------------------------------------------- choosing files
  const norm = s => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  const guessType = n => /exec/i.test(n) ? "executive" : /tech/i.test(n) ? "technical" : "";
  const guessService = n => services.find(s => {      // long names match anywhere; short ones (VA, PCI) only as a whole word
    if (norm(s).length >= 4) return norm(n).includes(norm(s));
    const re = new RegExp("(^|[^a-z0-9])" + s.toLowerCase().replace(/[^a-z0-9]+/g, "[^a-z0-9]*") + "([^a-z0-9]|$)");
    return re.test(n.toLowerCase());
  }) || "";

  function addFiles(list) {
    let skipped = 0;
    [...list].forEach(f => {
      if (!/\.docx$/i.test(f.name)) { skipped++; return; }
      if (files.some(x => x.file.name === f.name && x.file.size === f.size)) return;
      if (files.length >= maxBatch) { skipped++; return; }
      files.push({ file: f, type: guessType(f.name), service: guessService(f.name) });
    });
    showError(skipped ? `${skipped} file(s) skipped: only .docx files are accepted, up to ${maxBatch} at a time.` : "");
    renderFiles();
  }

  function renderFiles() {
    const box = $("#flist"); box.replaceChildren(); box.hidden = !files.length;
    $("#dz").classList.toggle("small", files.length > 0);
    const miss = files.filter(f => !f.type).length;
    $("#count").textContent = files.length ? `${files.length} file${files.length > 1 ? "s" : ""}${miss ? `, ${miss} need a type` : ""}` : "";
    files.forEach((f, i) => {
      const row = el("div", "frow" + (f.type ? "" : " need"));
      const nm = el("span", "fname2", f.file.name); nm.title = f.file.name;
      const ty = el("select"); ty.title = "Report type";
      [["", "Type?"], ["technical", "Technical"], ["executive", "Executive"]].forEach(([v, l]) => ty.append(new Option(l, v)));
      ty.value = f.type; ty.addEventListener("change", () => { f.type = ty.value; renderFiles(); });
      const sv = el("select"); sv.title = "Service for this file";
      sv.append(new Option("Default service", "")); services.forEach(s => sv.append(new Option(s, s)));
      sv.value = f.service; sv.addEventListener("change", () => { f.service = sv.value; });
      const rm = el("button", "x", "×"); rm.type = "button"; rm.title = "Remove"; rm.setAttribute("aria-label", "Remove " + f.file.name);
      rm.addEventListener("click", () => { files.splice(i, 1); renderFiles(); });
      row.append(nm, ty, sv, rm); box.append(row);
    });
    const isPair = files.length === 2 && new Set(files.map(f => f.type)).size === 2 && !files.some(f => !f.type);
    $("#ai-wrap").hidden = !(aiAvailable && isPair);
    const btn = $("#submit"); if (!btn.disabled) btn.textContent = files.length > 2 ? `Run QA on ${files.length} reports` : "Run QA";
  }

  const dz = $("#dz"), input = $("#files");
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("click", e => e.stopPropagation());
  input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
  ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", e => addFiles(e.dataTransfer.files));
  // dropping anywhere on the form works too
  form.addEventListener("dragover", e => e.preventDefault());
  form.addEventListener("drop", e => { if (e.target.closest("#dz")) return; e.preventDefault(); addFiles(e.dataTransfer.files); });

  // ---------------------------------------------------------------- submit
  form.addEventListener("submit", async e => {
    e.preventDefault(); showError("");
    if (!files.length) return showError("Please add at least one report.");
    if (files.some(f => !f.type)) return showError("Choose Technical or Executive for every report.");
    if (!$("#consultant").value.trim()) return showError("Consultant full name is required.");
    const fd = new FormData();
    ["service", "consultant", "reviewer", "client", "report_date", "period"].forEach(n => fd.set(n, (form.elements[n]?.value || "").trim()));
    files.forEach(f => { fd.append("files", f.file); fd.append("types", f.type); fd.append("services", f.service); });
    const dry = $("#dry_run").checked;
    fd.set("dry_run", dry ? "true" : "false");
    fd.set("ai_review", !$("#ai-wrap").hidden && $("#ai_review").checked ? "true" : "false");
    store.set("crespoqa.consultant", $("#consultant").value.trim());
    store.set("crespoqa.service", $("#service").value);
    const btn = $("#submit"); btn.disabled = true; btn.textContent = "Uploading…";
    try {
      const r = await CQ.api("/api/jobs/bulk", { method: "POST", body: fd });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Upload failed.");
      track(body.job_id, dry);
    } catch (err) { showError(err.message); btn.disabled = false; renderFiles(); }
  });

  $("#again").addEventListener("click", () => location.reload());

  // ---------------------------------------------------------------- live progress
  let bulk = false, completed = 0;
  function track(jobId, dry) {
    $("#form-view").hidden = true; $("#result-view").hidden = false; document.body.classList.add("results");
    $("#h-result").textContent = dry ? "Dry run in progress" : "Processing";
    const docsBox = $("#docs"), rows = {};
    CQ.call(`/api/jobs/${jobId}`).then(snap => {
      const names = Object.keys(snap.plan); bulk = names.length > 2;
      if (bulk) {
        const pane = el("div", "box pane flist-pane"), ul = el("div", "plist");
        names.forEach(n => {
          const r = el("button", "prow"); r.type = "button"; r.disabled = true;
          const k = el("span", "kicker", (snap.kinds[n] || "").slice(0, 4)); const nm = el("span", "pn", n); nm.title = n;
          const st = el("span", "ps", "Waiting"); r.append(k, nm, st); ul.append(r);
          rows[n] = { row: r, st, done: 0, total: snap.plan[n].length };
        });
        pane.append(ul); docsBox.append(pane); $("#rgrid").classList.add("bulk");
      } else {
        names.forEach(name => {
          const card = el("div", "box pane"), h = el("div", "dochead");
          h.append(el("span", "kicker", snap.kinds[name] === "technical" ? "Technical" : "Executive"), el("span", "dname", name));
          const ol = el("ol", "steps"); rows[name] = { steps: {} };
          snap.plan[name].forEach(s => { const li = el("li", "pending"); li.append(el("span", null, s.label));
            ol.append(li); rows[name].steps[s.key] = { li }; });
          card.append(h, ol); docsBox.append(card);
        });
      }
      const es = new EventSource(`/api/jobs/${jobId}/events`);
      es.onmessage = m => {
        const ev = JSON.parse(m.data), r = rows[ev.doc];
        if (ev.type === "step" && r) {
          if (bulk) {
            if (ev.state === "running") r.st.textContent = `Step ${r.done + 1} of ${r.total}`;
            else r.done++;
            r.row.classList.add("running");
          } else { const s = r.steps[ev.key]; if (s) s.li.className = ev.state === "running" ? "running" : "done"; }
        } else if (ev.type === "doc" && r && bulk) {
          r.st.textContent = "Done"; r.row.classList.remove("running"); completed++;
          $("#h-result").textContent = `${dry ? "Dry run" : "Processing"}: ${completed} of ${names.length}`;
        }
        else if (ev.type === "end") { es.close(); finish(jobId, dry); }
      };
      es.onerror = () => { es.close(); finish(jobId, dry); };
    });
  }

  // ---------------------------------------------------------------- results
  function reportCard(rep, snap, jobId) {
    const card = el("div", "box pane"), h = el("div", "dochead");
    const nm = el("span", "dname", rep.input_name); nm.title = rep.input_name;
    const svc = snap.services && snap.services[rep.input_name];
    h.append(el("span", "kicker", (rep.report_type === "technical" ? "Technical" : "Executive") + (svc && bulk ? " · " + svc : "")), nm);
    if (bulk && rep.output_name && (snap.outputs || []).includes(rep.output_name)) {
      const a = el("a", "dl", "Download this file"); a.href = `/api/jobs/${jobId}/files/${encodeURIComponent(rep.output_name)}`; h.append(a);
    }
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
    return card;
  }

  // Plain-language reasons for every error / warning / manual check, grouped by file (rule-based, no report content)
  function renderWhy(snap) {
    const box = $("#why"), list = $("#why-list"); list.replaceChildren();
    const withProblems = snap.reports.filter(r => (r.problems || []).length);
    box.hidden = !withProblems.length;
    withProblems.forEach(r => {
      const g = el("div", "wgroup"); const gh = el("div", "wfile", r.input_name); gh.title = r.input_name; g.append(gh);
      r.problems.forEach(p => {
        const d = el("details", "wi " + p.level); d.open = p.level === "error";
        const s = el("summary"); s.append(el("span", "wl " + p.level, p.level === "error" ? "Error" : p.level === "warning" ? "Warning" : "Check"),
          el("span", "wtitle", p.title + (p.page ? ` (${String(p.page).includes(",") ? "pages" : "page"} ${p.page})` : "")));
        const b = el("div", "wbody");
        const why = el("p"); why.append(el("strong", null, "Why: "), p.why);
        const fix = el("p"); fix.append(el("strong", null, "What to do: "), p.fix);
        b.append(why, fix);
        if (p.detail && p.detail !== p.title) b.append(el("p", "wdetail", p.detail));
        d.append(s, b); g.append(d);
      });
      list.append(g);
    });
  }

  let finished = false;
  async function finish(jobId, dry) {
    if (finished) return; finished = true;
    const r = await CQ.api(`/api/jobs/${jobId}`);
    if (!r.ok) return showError("This job has expired.");
    const snap = await r.json(), docsBox = $("#docs");
    docsBox.replaceChildren();
    const nOk = snap.reports.filter(x => x.status === "success").length;
    const nFail = snap.reports.filter(x => x.status === "failed").length;
    const nWarn = snap.reports.length - nOk - nFail;
    $("#h-result").textContent = (dry ? "Dry run complete" : "Done") + (bulk ? `: ${snap.reports.length} reports, ${nOk} clean${nWarn ? `, ${nWarn} to check` : ""}${nFail ? `, ${nFail} failed` : ""}` : "");

    if (bulk) {
      const pane = el("div", "box pane flist-pane"), list = el("div", "plist"), detail = el("div", "detailwrap");
      let current = null;
      const show = (rep, row) => {
        if (current) current.classList.remove("sel"); current = row; row.classList.add("sel");
        detail.replaceChildren(reportCard(rep, snap, jobId));
      };
      const order = [...snap.reports].sort((a, b) => (b.status === "failed") - (a.status === "failed") || (b.status !== "success") - (a.status !== "success"));
      order.forEach(rep => {
        const row = el("button", "prow"); row.type = "button";
        const nm = el("span", "pn", rep.input_name); nm.title = rep.input_name;
        const label = rep.status === "failed" ? "Failed" : rep.status === "success" ? "OK" : "To check";
        row.append(el("span", "kicker", rep.report_type.slice(0, 4)), nm, el("span", "ps " + rep.status, label));
        row.addEventListener("click", () => show(rep, row)); list.append(row);
      });
      pane.append(list); docsBox.append(pane, detail);
      $("#rgrid").classList.add("has-detail");
      const first = list.querySelector(".prow"); if (first) first.click();
    } else {
      snap.reports.forEach(rep => docsBox.append(reportCard(rep, snap, jobId)));
    }

    renderWhy(snap);
    const sv = $("#saved"); sv.replaceChildren(); sv.hidden = !(snap.saved && snap.saved.length);
    const bad = (snap.saved || []).filter(x => !x.ok), good = (snap.saved || []).filter(x => x.ok);
    if (good.length) sv.append(el("div", null, good.length === 1 ? `Saved over the old file: ${good[0].folder}/${good[0].name} (the old one is kept in ${good[0].folder}/CrespoBeautify_originals)` : `Saved ${good.length} files over the old ones in ${good[0].folder} (old versions kept in CrespoBeautify_originals)`));
    bad.forEach(x => sv.append(el("div", "alert", `${x.name}: ${x.error}`)));

    const dl = $("#downloads"); dl.replaceChildren();
    if (!dry && snap.outputs.length) {
      const urls = snap.outputs.map(n => [n, `/api/jobs/${jobId}/files/${encodeURIComponent(n)}`]);
      const click = (u, n) => { const a = document.createElement("a"); a.href = u; if (n) a.download = n; document.body.append(a); a.click(); a.remove(); };
      if (urls.length > 2) {
        const z = el("button", "primary", `Download all as ZIP (${urls.length} files)`); z.type = "button";
        z.addEventListener("click", () => click(`/api/jobs/${jobId}/zip`, "CrespoBeautify_reports.zip")); dl.append(z);
      } else {
        const both = el("button", "primary", urls.length > 1 ? "Download both files" : "Download file"); both.type = "button";
        both.addEventListener("click", () => urls.forEach(([n, u], i) => setTimeout(() => click(u, n), i * 700)));
        dl.append(both);
        urls.forEach(([n, u]) => { const a = el("a", "btn", n); a.href = u; a.title = "Download this file"; dl.append(a); });
      }
      dl.hidden = false;
    }
    $("#again").hidden = false;
    if (snap.review_status && snap.review_status !== "off") pollReview(jobId);
  }

  // ---------------------------------------------------------------- AI review (one pair at a time)
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
