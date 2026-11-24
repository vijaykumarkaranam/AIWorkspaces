/* End-to-end services tab, shared by the Nokia and Cisco reports.
   E2E.render(el, model)  draws the tab into el
   E2E.pathsHTML(rec)     the path diagrams of one service (used by the Nokia "Service trace" tab)
   Every value from a device is escaped before it is put into the page. */
const E2E = (() => {
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c]));
  const PILL = {up: "p-ok", down: "p-bad", "admin-down": "p-warn", degraded: "p-warn", partial: "p-info", local: "p-info",
                matched: "p-ok", "not-collected": "p-info", "no-service": "p-warn", "no-address": "p-warn", self: "p-info", unknown: "p-info"};
  const LABEL = {partial: "far end missing", local: "local only", "not-collected": "not collected", "no-service": "no matching service",
                 "no-address": "no far-end address", self: "same PE"};
  const pill = v => v ? `<span class="pill ${PILL[v] || "p-info"}">${esc(LABEL[v] || v)}</span>` : "";
  const SEVP = {critical: "p-bad", warning: "p-warn", info: "p-info"};
  const ORDER = ["down", "degraded", "partial", "admin-down", "up", "local"];

  function box(type, name, body, cls) {
    return `<div class="e2e-box ${cls || ""}"><div class="t">${esc(type)}</div><div class="n">${name}</div>${body || ""}</div>`;
  }
  const arrow = '<span class="e2e-arrow">→</span>';

  function ceBox(ce) {
    if (!ce) return box("CE", '<span class="muted">not seen by LLDP</span>', "", "miss");
    return box("CE", esc(ce.name), `<div class="mono muted">${esc(ce.port)}${ce.mgmt ? " · " + esc(ce.mgmt) : ""}</div>` +
      (ce.description ? `<div class="muted">${esc(String(ce.description).slice(0, 60))}</div>` : ""));
  }
  function acBox(ac) {
    const down = ac.oper === "down" || ac.oper === "admin-down";
    return box(ac.interface ? "Routed interface" : "Access circuit", `<span class="mono">${esc(ac.id)}</span>`,
      `<div>${pill(ac.oper)}${ac.portOper && ac.portOper !== "unknown" && ac.portOper !== ac.oper ? " port " + pill(ac.portOper) : ""}</div>` +
      (ac.flags ? `<div class="muted mono">${esc(ac.flags)}</div>` : "") +
      (ac.description ? `<div class="muted">${esc(ac.description)}</div>` : ""), down ? "bad" : "");
  }
  function accessColumn(acs, reverse) {
    if (!acs || !acs.length) return [box("Access", '<span class="muted">no access circuit</span>', "", "miss")];
    const rows = acs.map(a => `<div style="display:flex;align-items:center">${reverse ? acBox(a) + arrow + ceBox(a.ce) : ceBox(a.ce) + arrow + acBox(a)}</div>`);
    return [`<div class="e2e-stack">${rows.join("")}</div>`];
  }
  function pwLink(pw) {
    const st = pw.oper === "up" ? "" : (pw.oper === "unknown" ? "unknown" : "down");
    const tr = pw.transport || {};
    return `<div class="e2e-pw"><div><b>${esc(pw.kind)}</b> <span class="mono">${esc(pw.id)}</span></div><div class="ln ${st}"></div>
      <div>${pill(pw.oper)} ${tr.type ? esc(tr.type) : ""}</div>
      <div class="mono">${esc(tr.name || "")}</div>
      ${tr.sdpOper && tr.sdpOper !== "unknown" ? `<div>SDP ${pill(tr.sdpOper)}${tr.lspOper ? " LSP " + pill(tr.lspOper) : ""}</div>` : ""}
      ${pw.peerStatus ? `<div style="color:var(--bad)">far end: ${esc(pw.peerStatus)}</div>` : ""}</div>`;
  }

  function localBox(rec, model) {
    const pe = model ? `${esc(model.name)} <span class="muted mono">${esc(model.node)}</span>` : "";
    return box("Local PE · " + rec.type, `${pe ? pe + "<br>" : ""}${esc(rec.name)}`,
      `<div>${pill(rec.oper)} <span class="mono muted">${esc(rec.id)}</span></div>` +
      (rec.vplsId ? `<div class="muted">VPLS-ID ${esc(rec.vplsId)}</div>` : "") +
      (rec.routeTarget ? `<div class="muted">RT ${esc(rec.routeTarget)}</div>` : ""), "pe");
  }

  function pathsHTML(rec, model) {
    const h = `<h4 style="margin:10px 0 4px">Local side</h4><div class="e2e-path">${accessColumn(rec.acs).join("")}${arrow}${localBox(rec, model)}</div>`;
    return h + legsHTML(rec, model);
  }

  function legsHTML(rec, model) {
    if (!rec.legs.length) return '<p class="muted">No pseudowires: this service does not leave the PE through a pseudowire.</p>';
    const local = box("From", model ? esc(model.name) : "this PE", "", "pe");
    let h = `<h4 style="margin:10px 0 4px">Pseudowires and far ends (${rec.legs.length})</h4>`;
    for (const l of rec.legs) {
      const fe = l.farEnd, r = l.remote;
      const feBox = box("Far-end PE" + (fe.vendor ? " · " + fe.vendor : ""),
        `${esc(fe.name || fe.ip || "?")}${fe.node && fe.node !== fe.ip ? ` <span class="muted mono">${esc(fe.node)}</span>` : ""}`,
        `<div class="mono muted">${esc(fe.ip || "")}</div><div>${pill(fe.status)}</div>` +
        (fe.matchedBy ? `<div class="muted">matched by ${esc(fe.matchedBy)}</div>` : ""),
        fe.status === "matched" ? "pe" : "miss");
      let tail = "";
      if (r) {
        const rpw = l.remotePw;
        tail = arrow + box("Far-end service · " + r.type, esc(r.name),
          `<div>${pill(r.oper)} <span class="mono muted">${esc(r.id)}</span></div>` +
          (rpw ? `<div class="muted">PW <span class="mono">${esc(rpw.id)}</span> ${pill(rpw.oper)}</div>` : ""), r.oper === "down" ? "bad" : "") +
          arrow + accessColumn(r.acs, true).join("");
      }
      h += `<div class="e2e-path">${local}${pwLink(l.pw)}${feBox}${tail}</div>`;
    }
    return h;
  }

  function issuesHTML(rec) {
    if (!rec.issues.length) return '<p class="muted">No issues found.</p>';
    return `<ul class="e2e-issues">${rec.issues.map(i => `<li><span class="pill ${SEVP[i.sev]}">${esc(i.sev)}</span> ${esc(i.msg)}</li>`).join("")}</ul>`;
  }

  function render(el, model) {
    if (!model) { el.innerHTML = '<p class="muted">End-to-end data was not built for this device.</p>'; return; }
    if (model.error) { el.innerHTML = `<div class="card"><b>End-to-end services</b><p>${esc(model.error)}</p></div>`; return; }
    const st = {q: "", status: "", sel: null};
    const C = model.counts || {};
    const wrap = document.createElement("div");
    wrap.className = "e2e";
    el.innerHTML = "";
    el.appendChild(wrap);
    const missing = model.farEnds.filter(f => !f.collected);

    function kpi(label, val, status, sub) {
      return `<div class="card kpi e2e-kpi${st.status === status ? " on" : ""}" data-e2e-status="${esc(status)}"><div class="l">${esc(label)}</div><div class="v">${val ?? 0}</div>${sub ? `<div class="s muted">${esc(sub)}</div>` : ""}</div>`;
    }
    function rows() {
      const q = st.q.toLowerCase();
      return model.services.filter(s => (!st.status || s.status === st.status) &&
        (!q || [s.key, s.name, s.description, s.ces.join(" "), s.acs.map(a => a.id + " " + a.description).join(" "),
                s.legs.map(l => (l.farEnd.ip || "") + " " + (l.farEnd.name || "")).join(" ")].join(" ").toLowerCase().includes(q)))
        .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || String(a.key).localeCompare(String(b.key), undefined, {numeric: true}));
    }
    function draw() {
      const list = rows();
      const farTxt = missing.length
        ? `<div class="card" style="margin:8px 0"><b>${missing.length} of ${model.farEnds.length} far-end PEs have no saved data.</b>
           Press <b>Collect far ends</b> in the viewer, or run <code>python -m e2e.collect --node ${esc(model.node)}</code> in the netconf-viewers folder, then rebuild this report.
           <div class="small muted" style="margin-top:6px">${missing.slice(0, 40).map(f => `<span class="chip">${esc(f.ip)} · ${f.services} svc</span>`).join(" ")}${missing.length > 40 ? " …" : ""}</div></div>`
        : (model.farEnds.length ? `<p class="muted">All ${model.farEnds.length} far-end PEs have saved data.</p>` : "");
      const body = list.map(s => {
        const acUp = s.acs.filter(a => a.oper === "up").length;
        const matched = s.legs.filter(l => l.farEnd.status === "matched").length;
        const top = s.issues.find(i => i.sev !== "info") || s.issues[0];
        return `<tr data-e2e-key="${esc(s.key)}" class="${st.sel === s.key ? "sel" : ""}"><td>${pill(s.status)}</td>
          <td><b>${esc(s.type)} ${esc(s.id)}</b><div class="muted small">${esc(s.name)}</div></td>
          <td class="small">${s.ces.length ? esc(s.ces.slice(0, 3).join(", ")) + (s.ces.length > 3 ? ` <span class="muted">+${s.ces.length - 3}</span>` : "") : '<span class="muted">—</span>'}</td>
          <td class="num">${acUp}/${s.acs.length}</td>
          <td class="num">${matched}/${s.legs.length}</td>
          <td class="small">${top ? `<span class="pill ${SEVP[top.sev]}">${esc(top.sev)}</span> ${esc(top.msg)}` : '<span class="muted">—</span>'}</td></tr>`;
      }).join("");
      const sel = model.services.find(s => s.key === st.sel);
      wrap.innerHTML = `<p class="lead">Every service on ${esc(model.name)} (${esc(model.node)}) followed from the customer edge, through this PE and its pseudowires, to the far-end PE and its customer edge. Loopbacks: <span class="mono">${esc(model.loopbacks.join(", "))}</span>.</p>
        <div class="e2e-kpis">${kpi("Services", C.services, "")}${kpi("Up end to end", C.up, "up")}${kpi("Down", C.down, "down")}
        ${kpi("Degraded", C.degraded, "degraded")}${kpi("Far end missing", C.partial, "partial")}${kpi("Local only", C.local, "local")}
        ${kpi("Far-end PEs", model.farEnds.length, "", `${C.farEndsMissing || 0} without data`)}</div>
        ${farTxt}
        ${model.missing && model.missing.length ? `<p class="small muted">Queries not saved for this router (some details may be missing): ${model.missing.map(esc).join(", ")}</p>` : ""}
        <div class="e2e-bar"><input data-e2e-q placeholder="Filter by service, CE, circuit, far end" value="${esc(st.q)}">
          <select data-e2e-sel><option value="">All statuses</option>${ORDER.map(o => `<option value="${o}" ${st.status === o ? "selected" : ""}>${esc(LABEL[o] || o)}</option>`).join("")}</select>
          <span class="muted small">${list.length} of ${model.services.length} services · click a row for its path</span></div>
        <div class="tw"><table><thead><tr><th>Status</th><th>Service</th><th>CE</th><th class="num">ACs up</th><th class="num">Far ends found</th><th>Main issue</th></tr></thead><tbody>${body}</tbody></table></div>
        <div class="e2e-detail" id="e2e-detail">${sel ? `<div class="card"><h3 style="margin-top:0">${esc(sel.type)} ${esc(sel.id)} · ${esc(sel.name)} ${pill(sel.status)}</h3>
          ${sel.description ? `<p class="muted">${esc(sel.description)}</p>` : ""}${issuesHTML(sel)}${pathsHTML(sel, model)}</div>` : ""}</div>`;
    }
    wrap.addEventListener("click", e => {
      const k = e.target.closest("[data-e2e-status]");
      if (k) { st.status = st.status === k.dataset.e2eStatus ? "" : k.dataset.e2eStatus; draw(); return; }
      const tr = e.target.closest("tr[data-e2e-key]");
      if (tr) { st.sel = st.sel === tr.dataset.e2eKey ? null : tr.dataset.e2eKey; draw();
        const d = wrap.querySelector("#e2e-detail"); if (d && st.sel) d.scrollIntoView({behavior: "smooth", block: "start"}); }
    });
    wrap.addEventListener("input", e => {
      if (e.target.matches("[data-e2e-q]")) { st.q = e.target.value; const pos = e.target.selectionStart; draw();
        const i = wrap.querySelector("[data-e2e-q]"); i.focus(); i.setSelectionRange(pos, pos); }
    });
    wrap.addEventListener("change", e => { if (e.target.matches("[data-e2e-sel]")) { st.status = e.target.value; draw(); } });
    draw();
  }

  function recordFor(model, key) { return model && model.services ? model.services.find(s => s.key === key) : null; }
  return {render, pathsHTML, legsHTML, issuesHTML, recordFor, esc};
})();
