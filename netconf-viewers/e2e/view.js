/* End-to-end services tab, shared by the Nokia and Cisco reports.
   E2E.render(el, model)        draws the tab into el
   E2E.legsHTML(rec, model)     pseudowires, far ends and transport of one service (Nokia "Service trace" tab)
   Anything with data-e2e-obj="<key>" opens that object (SDP, LSP, RSVP session, interface, port, LAG,
   route, service, PE) in a side panel with its summary, related tables, links and every raw field.
   Every value from a device is escaped before it is put into the page. */
const E2E = (() => {
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c]));
  const PILL = {up: "p-ok", down: "p-bad", "admin-down": "p-warn", degraded: "p-warn", partial: "p-info", local: "p-info",
                matched: "p-ok", "not-collected": "p-info", "no-service": "p-warn", "no-address": "p-warn", self: "p-info",
                unknown: "p-info", ok: "p-ok", warning: "p-warn", alarm: "p-bad"};
  const LABEL = {partial: "far end missing", local: "local only", "not-collected": "not collected", "no-service": "no matching service",
                 "no-address": "no far-end address", self: "same PE"};
  const pill = v => v ? `<span class="pill ${PILL[v] || "p-info"}">${esc(LABEL[v] || v)}</span>` : "";
  const SEVP = {critical: "p-bad", warning: "p-warn", info: "p-info"};
  const ORDER = ["down", "degraded", "partial", "admin-down", "up", "local"];
  let CUR = null;          // the model whose objects the panel opens
  let STACK = [];          // panel history

  const has = k => k && CUR && CUR.objects && CUR.objects[k];
  /* A link to an object when the page has it; plain text otherwise. `html` must already be escaped. */
  const ol = (k, html) => has(k) ? `<a class="e2e-link" data-e2e-obj="${esc(k)}" title="Open details">${html}</a>` : html;

  function box(type, name, body, cls, k) {
    const click = has(k) ? ` data-e2e-obj="${esc(k)}" title="Click for full details"` : "";
    return `<div class="e2e-box ${cls || ""}${click ? " click" : ""}"${click}><div class="t">${esc(type)}</div><div class="n">${name}</div>${body || ""}</div>`;
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
      (ac.portKey ? `<div>port ${ol(ac.portKey, `<span class="mono">${esc(ac.port)}</span>`)} ${ac.portHealth && ac.portHealth !== "ok" ? pill(ac.portHealth) : ""}</div>` : "") +
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
    const lsp = tr.lsp;
    return `<div class="e2e-pw"><div><b>${esc(pw.kind)}</b> <span class="mono">${esc(pw.id)}</span></div><div class="ln ${st}"></div>
      <div>${pill(pw.oper)} ${esc(tr.type || "")}${tr.label ? ` · label <span class="mono">${esc(tr.label)}</span>` : ""}</div>
      ${pw.pwLabels ? `<div class="small">VC label <span class="mono">${esc(pw.pwLabels.local)} / ${esc(pw.pwLabels.remote)}</span> <span class="muted">local / remote</span></div>` : ""}
      ${tr.sdpKey ? `<div>${ol(tr.sdpKey, "SDP " + esc(pw.sdpId))} ${pill(tr.sdpOper)}</div>` : ""}
      ${lsp ? `<div>${ol(lsp.key, "LSP " + esc(lsp.name))} ${pill(lsp.oper)}</div>` : ""}
      ${tr.routeKey ? `<div>${ol(tr.routeKey, esc(tr.name))}</div>` : (!tr.sdpKey && !lsp && tr.name ? `<div class="mono">${esc(tr.name)}</div>` : "")}
      ${pw.peerStatus ? `<div style="color:var(--bad)">far end: ${esc(pw.peerStatus)}</div>` : ""}</div>`;
  }

  /* ---------------- transport detail */
  function portCell(p) {
    if (!p) return '<span class="muted">—</span>';
    const members = (p.members || []).map(m =>
      `<div class="small">${ol(m.key, `<span class="mono">${esc(m.id)}</span>`)} ${pill(m.oper)}${m.health !== "ok" ? " " + pill(m.health) : ""}
        ${m.neighbor ? `<span class="muted">→ ${esc(m.neighbor.name)} ${esc(m.neighbor.port)}</span>` : ""}
        ${m.rxPowerDbm != null ? `<span class="muted"> · Rx ${esc(m.rxPowerDbm)} dBm</span>` : ""}</div>`).join("");
    return `${ol(p.key, `<b class="mono">${esc(p.id)}</b>`)} ${pill(p.oper)} ${p.health && p.health !== "ok" ? pill(p.health) : ""}
      ${p.members ? `<div class="small muted">${p.membersUp} of ${p.members.length} members up</div>${members}` :
        (p.neighbor ? `<div class="small muted">→ ${esc(p.neighbor.name)} ${esc(p.neighbor.port)}</div>` : "") +
        (p.rxPowerDbm != null ? `<div class="small muted">Rx ${esc(p.rxPowerDbm)} dBm${p.optic ? " · " + esc(p.optic) : ""}</div>` : "")}`;
  }
  function transportHTML(tr, title) {
    if (!tr) return "";
    const lsp = tr.lsp;
    let h = `<div class="e2e-trhead"><b>${esc(title)}</b> · ${esc(tr.type || "transport")}`;
    if (tr.sdpKey) h += ` · ${ol(tr.sdpKey, esc(tr.name.split(" / ")[0]))} ${pill(tr.sdpOper)}`;
    if (lsp) h += ` · ${ol(lsp.key, "LSP <b>" + esc(lsp.name) + "</b>")} ${pill(lsp.oper)} metric ${esc(lsp.metric ?? "?")}` +
      ` · FRR ${lsp.frr ? (lsp.protectionInUse ? '<span class="pill p-warn">bypass in use</span>' : "available") : "off"}` +
      (lsp.pathState ? ` · path ${esc(lsp.pathState)}` : "") + (lsp.transitions != null ? ` · ${esc(lsp.transitions)} transitions` : "");
    if (tr.routeKey) h += ` · ${ol(tr.routeKey, esc(tr.name))}`;
    if (tr.label) h += ` · label <span class="mono">${esc(tr.label)}</span>`;
    h += "</div>";
    if (tr.paths && tr.paths.length) {
      h += `<div class="tw" style="max-height:none"><table><thead><tr><th>Path</th><th>Egress interface</th><th>Port / LAG and members</th><th>Next hop</th><th>Labels</th><th>Health</th></tr></thead><tbody>` +
        tr.paths.map(p => `<tr><td>${esc(p.role)}</td>
          <td>${p.interface ? ol(p.interfaceKey, `<span class="mono">${esc(p.interface)}</span>`) : "—"}${p.interfaceIp ? `<div class="small muted mono">${esc(p.interfaceIp)}</div>` : ""}
              ${p.portName && p.portName !== p.interface ? `<div class="small muted">on ${esc(p.portName)}</div>` : ""}</td>
          <td>${portCell(p.port)}</td>
          <td><b>${esc(p.nextHopName || "")}</b><div class="mono small">${esc(p.nextHop || "")}</div></td>
          <td class="mono">${esc((p.labels || []).join(" / ")) || "—"}</td>
          <td class="small">${p.port && p.port.why && p.port.why.length ? esc(p.port.why.join("; ")) : '<span class="muted">ok</span>'}</td></tr>`).join("") +
        "</tbody></table></div>";
    }
    if (tr.hops && tr.hops.length) {
      h += `<div class="small muted" style="margin:8px 0 2px">Hop-by-hop path${tr.hopSource ? " (" + esc(tr.hopSource) + ")" : ""}</div><div class="e2e-hops">` +
        tr.hops.map(x => `<span class="e2e-hop${x.local ? " local" : ""}">${x.name ? `<b>${esc(x.name)}</b> ` : ""}<span class="mono">${esc(x.ip)}</span></span>`).join('<span class="e2e-arrow">›</span>') + "</div>";
    }
    if (tr.note) h += `<p class="small muted">${esc(tr.note)}</p>`;
    if (tr.issues && tr.issues.length) h += issuesList(tr.issues);
    return `<div class="e2e-transport">${h}</div>`;
  }
  function walkHTML(walk) {
    if (!walk || walk.length < 2) return "";
    return `<div class="small muted" style="margin:10px 0 4px">Router by router (routers with saved data)</div><div class="e2e-path">` +
      walk.map(w => box(w.final ? "Far-end PE" : "Router", ol(w.peKey, esc(w.name)),
        `<div class="mono muted">${esc(w.node)}</div>` +
        (w.interface ? `<div>out ${ol(w.interfaceKey, `<span class="mono">${esc(w.interface)}</span>`)} ${w.port ? pill(w.port.health) : ""}</div>` : "") +
        (w.labels && w.labels.length ? `<div class="mono small">label ${esc(w.labels.join(" / "))}</div>` : "") +
        (w.routeKey ? `<div>${ol(w.routeKey, "route")}</div>` : "") + (w.note ? `<div class="muted">${esc(w.note)}</div>` : ""),
        w.final ? "pe" : "")).join(arrow) + "</div>";
  }

  /* ---------------- service paths */
  function localBox(rec, model) {
    const pe = model ? `${ol(model.peKey, esc(model.name))} <span class="muted mono">${esc(model.node)}</span>` : "";
    return box("Local PE · " + rec.type, `${pe ? pe + "<br>" : ""}${esc(rec.name)}`,
      `<div>${pill(rec.oper)} <span class="mono muted">${esc(rec.id)}</span></div>` +
      (rec.vplsId ? `<div class="muted">VPLS-ID ${esc(rec.vplsId)}</div>` : "") +
      (rec.routeTarget ? `<div class="muted">RT ${esc(rec.routeTarget)}</div>` : ""), "pe", rec.objKey);
  }
  function pathsHTML(rec, model) {
    if (model) CUR = model;
    const h = `<h4 style="margin:10px 0 4px">Local side</h4><div class="e2e-path">${accessColumn(rec.acs).join("")}${arrow}${localBox(rec, model)}</div>`;
    return h + legsHTML(rec, model);
  }
  function legsHTML(rec, model) {
    if (model) CUR = model;
    if (!rec.legs.length) return '<p class="muted">No pseudowires: this service does not leave the PE through a pseudowire.</p>';
    const local = box("From", model ? esc(model.name) : "this PE", "", "pe", model && model.peKey);
    let h = `<h4 style="margin:10px 0 4px">Pseudowires and far ends (${rec.legs.length})</h4>`;
    for (const l of rec.legs) {
      const fe = l.farEnd, r = l.remote;
      const feBox = box("Far-end PE" + (fe.vendor ? " · " + fe.vendor : ""),
        `${esc(fe.name || fe.ip || "?")}${fe.node && fe.node !== fe.ip ? ` <span class="muted mono">${esc(fe.node)}</span>` : ""}`,
        `<div class="mono muted">${esc(fe.ip || "")}</div><div>${pill(fe.status)}</div>` +
        (fe.matchedBy ? `<div class="muted">matched by ${esc(fe.matchedBy)}</div>` : ""),
        fe.status === "matched" ? "pe" : "miss", fe.peKey);
      let tail = "";
      if (r) {
        const rpw = l.remotePw;
        tail = arrow + box("Far-end service · " + r.type, esc(r.name),
          `<div>${pill(r.oper)} <span class="mono muted">${esc(r.id)}</span></div>` +
          (rpw ? `<div class="muted">PW <span class="mono">${esc(rpw.id)}</span> ${pill(rpw.oper)}</div>` : ""), r.oper === "down" ? "bad" : "", r.objKey) +
          arrow + accessColumn(r.acs, true).join("");
      }
      const back = l.remotePw && l.remotePw.transport ? transportHTML(l.remotePw.transport, `Return path from ${fe.name || fe.ip}`) : "";
      h += `<div class="e2e-path">${local}${pwLink(l.pw)}${feBox}${tail}</div>
        <details class="e2e-tr"${rec.legs.length <= 3 ? " open" : ""}><summary>Transport path and connected ports · ${esc(l.pw.id)} → ${esc(fe.name || fe.ip || "?")}</summary>
        ${transportHTML(l.pw.transport, "Outbound from this PE")}${walkHTML(l.walk)}${back}</details>`;
    }
    return h;
  }

  function issuesList(list) {
    return `<ul class="e2e-issues">${list.map(i => `<li><span class="pill ${SEVP[i.sev]}">${esc(i.sev)}</span> ${esc(i.msg)}</li>`).join("")}</ul>`;
  }
  function issuesHTML(rec) {
    return rec.issues.length ? issuesList(rec.issues) : '<p class="muted">No issues found.</p>';
  }

  /* ---------------- detail panel */
  function flat(o, p, out) {
    if (out.length > 5000) return out;
    if (o && typeof o === "object") {
      const entries = Array.isArray(o) ? o.map((v, i) => [i, v]) : Object.entries(o);
      if (!entries.length) out.push([p, Array.isArray(o) ? "[]" : "{}"]);
      for (const [k, v] of entries) flat(v, p ? (Array.isArray(o) ? `${p}[${k}]` : `${p}.${k}`) : String(k), out);
    } else out.push([p, o]);
    return out;
  }
  function cellHTML(c) {
    if (c && typeof c === "object" && "t" in c) return ol(c.k, esc(c.t));
    if (c === null || c === undefined || c === "") return '<span class="muted">—</span>';
    const s = String(c);
    return PILL[s] ? pill(s) : esc(s);
  }
  function panel() {
    let p = document.getElementById("e2e-panel");
    if (p) return p;
    p = document.createElement("aside");
    p.id = "e2e-panel";
    p.className = "e2e e2e-panel";
    p.innerHTML = `<div class="e2e-ph"><button class="btn" data-e2e-back title="Back">← Back</button><span class="e2e-pt"></span><button class="btn" data-e2e-close title="Close (Esc)">Close</button></div><div class="e2e-pb"></div>`;
    document.body.appendChild(p);
    p.addEventListener("click", e => {
      if (e.target.closest("[data-e2e-close]")) { p.classList.remove("on"); STACK = []; return; }
      if (e.target.closest("[data-e2e-back]")) { STACK.pop(); if (STACK.length) show(STACK[STACK.length - 1], false); else p.classList.remove("on"); }
    });
    p.addEventListener("input", e => {
      if (!e.target.matches("[data-e2e-rawq]")) return;
      const q = e.target.value.toLowerCase();
      p.querySelectorAll("tr[data-raw]").forEach(tr => { tr.style.display = !q || tr.dataset.raw.includes(q) ? "" : "none"; });
    });
    return p;
  }
  function show(k, push = true) {
    const o = has(k);
    if (!o) return;
    if (push) STACK.push(k);
    const p = panel();
    p.querySelector(".e2e-pt").innerHTML = `<span class="muted small">${esc(o.kind.toUpperCase())}</span>`;
    p.querySelector("[data-e2e-back]").style.visibility = STACK.length > 1 ? "visible" : "hidden";
    const raw = o.raw ? flat(o.raw, "", []) : [];
    p.querySelector(".e2e-pb").innerHTML =
      `<h2 style="margin:4px 0">${esc(o.title)} ${pill(o.status)}</h2>
       <div class="muted">${esc(o.subtitle || "")}${o.node ? ` · <span class="mono">${esc(o.node)}</span>` : ""}</div>
       <table class="e2e-kv"><tbody>${o.fields.map(([l, v]) => `<tr><th>${esc(l)}</th><td>${cellHTML(v)}</td></tr>`).join("")}</tbody></table>
       ${o.links && o.links.length ? `<div class="e2e-rel">${o.links.filter(x => has(x.key)).map(x => `<a class="chip link e2e-link" data-e2e-obj="${esc(x.key)}">${esc(x.label)}</a>`).join(" ")}</div>` : ""}
       ${o.tables.map(t => `<h3>${esc(t.title)} <span class="muted small">${t.rows.length}</span></h3><div class="tw" style="max-height:none"><table>
         <thead><tr>${t.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead>
         <tbody>${t.rows.map(r => `<tr>${r.map(c => `<td>${cellHTML(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`).join("")}
       ${raw.length ? `<details style="margin-top:14px"><summary><b>All fields</b> <span class="muted small">${raw.length}${raw.length > 5000 ? "+" : ""} values, as the router returned them</span></summary>
         <input data-e2e-rawq placeholder="Filter fields" style="margin:8px 0;width:100%">
         <div class="tw" style="max-height:60vh"><table><tbody>${raw.map(([k, v]) => `<tr data-raw="${esc((k + " " + v).toLowerCase())}"><td class="mono small">${esc(k)}</td><td class="mono small">${esc(v)}</td></tr>`).join("")}</tbody></table></div></details>` : ""}`;
    p.querySelector(".e2e-pb").scrollTop = 0;
    p.classList.add("on");
  }
  document.addEventListener("click", e => {
    const a = e.target.closest("[data-e2e-obj]");
    if (a) { e.preventDefault(); e.stopPropagation(); show(a.dataset.e2eObj); }
  }, true);
  document.addEventListener("keydown", e => {
    const p = document.getElementById("e2e-panel");
    if (e.key === "Escape" && p && p.classList.contains("on")) { p.classList.remove("on"); STACK = []; }
  });

  /* ---------------- the tab */
  function render(el, model) {
    if (!model) { el.innerHTML = '<p class="muted">End-to-end data was not built for this device.</p>'; return; }
    if (model.error) { el.innerHTML = `<div class="card"><b>End-to-end services</b><p>${esc(model.error)}</p></div>`; return; }
    CUR = model;
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
                s.legs.map(l => [l.farEnd.ip, l.farEnd.name, l.pw.transport && l.pw.transport.name].join(" ")).join(" ")].join(" ").toLowerCase().includes(q)))
        .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || String(a.key).localeCompare(String(b.key), undefined, {numeric: true}));
    }
    function draw() {
      CUR = model;
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
      wrap.innerHTML = `<p class="lead">Every service on ${ol(model.peKey, esc(model.name))} (${esc(model.node)}) followed from the customer edge, through this PE, its pseudowires and their transport (LSP or route, egress ports, hops), to the far-end PE and its customer edge. Underlined items open their full details. Loopbacks: <span class="mono">${esc(model.loopbacks.join(", "))}</span>.</p>
        <div class="e2e-kpis">${kpi("Services", C.services, "")}${kpi("Up end to end", C.up, "up")}${kpi("Down", C.down, "down")}
        ${kpi("Degraded", C.degraded, "degraded")}${kpi("Far end missing", C.partial, "partial")}${kpi("Local only", C.local, "local")}
        ${kpi("Far-end PEs", model.farEnds.length, "", `${C.farEndsMissing || 0} without data`)}</div>
        ${farTxt}
        ${model.missing && model.missing.length ? `<p class="small muted">Queries not saved for this router (some details may be missing): ${model.missing.map(esc).join(", ")}</p>` : ""}
        <div class="e2e-bar"><input data-e2e-q placeholder="Filter by service, CE, circuit, far end, LSP" value="${esc(st.q)}">
          <select data-e2e-sel><option value="">All statuses</option>${ORDER.map(o => `<option value="${o}" ${st.status === o ? "selected" : ""}>${esc(LABEL[o] || o)}</option>`).join("")}</select>
          <span class="muted small">${list.length} of ${model.services.length} services · click a row for its path</span></div>
        <div class="tw"><table><thead><tr><th>Status</th><th>Service</th><th>CE</th><th class="num">ACs up</th><th class="num">Far ends found</th><th>Main issue</th></tr></thead><tbody>${body}</tbody></table></div>
        <div class="e2e-detail" id="e2e-detail">${sel ? `<div class="card"><h3 style="margin-top:0">${ol(sel.objKey, `${esc(sel.type)} ${esc(sel.id)} · ${esc(sel.name)}`)} ${pill(sel.status)}</h3>
          ${sel.description ? `<p class="muted">${esc(sel.description)}</p>` : ""}${issuesHTML(sel)}${pathsHTML(sel, model)}</div>` : ""}</div>`;
    }
    wrap.addEventListener("click", e => {
      if (e.target.closest("[data-e2e-obj]")) return;
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
  return {render, pathsHTML, legsHTML, issuesHTML, recordFor, show, esc};
})();
