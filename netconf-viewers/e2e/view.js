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

  /* ---------------- service paths (laid out like the Service-LDP-E2E dashboard) */
  const VEND = {cisco: "Cisco", nokia: "Nokia"};
  const SVC_HEAD = {"bridge-domain": "Bridge domain", vpls: "VPLS", epipe: "Epipe", p2p: "XConnect", vprn: "VPRN (L3VPN)", service: "Service"};

  function stage(kind, head, icon, small, name, details, k, dashed) {
    const click = has(k) ? ` data-e2e-obj="${esc(k)}" title="Click for full details"` : "";
    return `<div class="e2e-stage s-${kind}${dashed ? " dashed" : ""}${click ? " click" : ""}"${click}>
      <div class="sh">${esc(head)}</div>
      <div class="sb"><div class="si">${icon}</div><div class="ss">${esc(small || "")}</div><div class="sn">${name}</div>
      ${details && details.length ? `<div class="sd">${details.filter(Boolean).map(d => `<div>${d}</div>`).join("")}</div>` : ""}</div></div>`;
  }
  const conn = label => `<div class="e2e-conn"><div class="ln"></div><div>${esc(label || "")}</div></div>`;
  const kv = (l, v) => v === undefined || v === null || v === "" ? "" : `${esc(l)}: <b>${esc(v)}</b>`;

  /* The far end shown in the headline: one whose CE was found, a cross-vendor one first (as the dashboard does). */
  function headlineLeg(rec) {
    const withCe = rec.legs.filter(l => l.remote && (l.remote.acs || []).some(a => a.ce));
    const other = withCe.find(l => l.farEnd.vendor && l.farEnd.vendor !== rec.vendor);
    return other || withCe[0] || rec.legs.find(l => l.remote) || rec.legs[0] || null;
  }
  function remoteCe(leg) {
    const ac = leg && leg.remote && (leg.remote.acs || []).find(a => a.ce);
    return ac ? ac.ce : null;
  }
  function ceStatus(leg) {
    const fe = leg.farEnd;
    if (remoteCe(leg)) return "ce";
    if (fe.status === "unreachable" || fe.status === "no-address") return "unreachable";
    if (fe.status === "not-collected") return "missing";
    if (fe.status === "no-service") return "noservice";
    if (fe.status === "self") return "self";
    return "nolldp";
  }

  function chainHTML(rec, model) {
    const acs = rec.acs || [], ac = acs[0], ce = ac && ac.ce, l = headlineLeg(rec);
    const tr = l ? l.pw.transport || {} : {};
    const t = l ? l.pw.tldp : null, rce = remoteCe(l), fe = l ? l.farEnd : null;
    const vendor = VEND[model.vendor] || model.vendor || "";
    let h = stage("ce", "Local CE", "▣", "Customer A", ce ? esc(ce.name) : '<span class="muted">not seen by LLDP</span>',
                  ce ? [kv("Port", ce.port), kv("Chassis", ce.chassis), ce.mgmt ? kv("Mgmt", ce.mgmt) : ""] : [], null, !ce);
    h += conn("Access");
    h += stage("ac", ac && ac.interface ? "Routed interface" : "AC", "⏚", "Attachment circuit",
               ac ? `<span class="mono">${esc(ac.id)}</span>` : '<span class="muted">none</span>',
               ac ? [pill(ac.oper), kv("Total ACs", acs.length), ac.description ? esc(ac.description) : ""] : [kv("Total ACs", 0)],
               ac && ac.portKey, !ac);
    h += conn(rec.type === "bridge-domain" ? "BD" : "Service");
    h += stage("pe", "Local PE", "◆", vendor, ol(model.peKey, esc(model.node)), [esc(model.name), kv("Group", rec.group), kv("Type", rec.type)], null);
    h += conn("");
    h += stage("svc", SVC_HEAD[rec.type] || rec.type, "●", rec.type === "bridge-domain" ? "VPLS" : rec.type.toUpperCase(),
               esc(rec.vfi || rec.name), [kv(rec.vpnId != null ? "VPN-ID" : "Service id", rec.vpnId != null ? rec.vpnId : rec.id),
               rec.vfi ? kv("VFI", rec.vfi) : "", pill(rec.oper)], rec.objKey);
    h += conn(rec.signaling || "");
    h += stage("sig", rec.signaling || "Signaling", "◉", rec.signaling || "", esc(rec.rd || rec.vplsId || (l ? l.pw.vcId : "") || "—"),
               [kv("RD", rec.rd), rec.vplsId && rec.vplsId !== rec.rd ? kv("VPLS-ID", rec.vplsId) : "",
                t ? `T-LDP: <b>${esc(t.state || "?")}</b>${t.uptime ? " · " + esc(t.uptime) : ""}` : ""], null);
    h += conn("MPLS");
    const coreName = tr.lsp ? ol(tr.lsp.key, esc(tr.lsp.name)) : (tr.routeKey ? ol(tr.routeKey, esc((tr.name || "").split(" via ")[0])) : esc(tr.type || "—"));
    h += stage("core", "MPLS core", "☁", "Transport", coreName,
               [esc(tr.type || ""), tr.label ? kv("Label", tr.label) : "", tr.lsp ? `LSP ${pill(tr.lsp.oper)}` : "",
                (tr.paths || [])[0] ? kv("Next hop", (tr.paths[0].nextHopName || tr.paths[0].nextHop)) : "",
                t ? `T-LDP: <b>${esc(t.state || "?")}</b>${t.uptime ? " · " + esc(t.uptime) : ""}` : ""], null, true);
    h += conn("");
    h += stage("rpe", "Remote PE", "◆", fe && fe.vendor ? (VEND[fe.vendor] || fe.vendor) : "Far end",
               fe ? ol(fe.peKey, esc(fe.ip || "?")) : '<span class="muted">none</span>',
               fe ? [fe.name && fe.name !== fe.ip ? esc(fe.name) : "", rce ? "CE discovered" : pill(fe.status),
                     fe.matchedBy ? `<span class="muted">${esc(fe.matchedBy)}</span>` : ""] : [], null, !fe || fe.status !== "matched");
    h += conn("Access");
    h += stage("ce", "Remote CE", "▣", "Customer B", rce ? esc(rce.name) : '<span class="muted">not discovered</span>',
               rce ? [kv("Port", rce.port), kv("Chassis", rce.chassis)] : [fe && fe.status === "not-collected" ? "Trace far ends to find it" : "LLDP not available"],
               null, !rce);
    return `<div class="e2e-stages">${h}</div>`;
  }

  function peerRowsHTML(rec, model) {
    if (!rec.legs.length) return '<p class="muted">No pseudowires: this service does not leave the PE through a pseudowire.</p>';
    const rows = rec.legs.map(l => {
      const fe = l.farEnd, t = l.pw.tldp, cs = ceStatus(l), ce = remoteCe(l), tr = l.pw.transport || {};
      const svcCell = rec.type === "bridge-domain" || rec.type === "vpls"
        ? `<div class="pt">${rec.vfi ? "VFI: " + esc(rec.vfi) : esc(rec.name)}</div><div>${rec.vpnId != null ? "VPN-ID: " + esc(rec.vpnId) : "Service " + esc(rec.id)}</div>${rec.vplsId ? `<div class="pc">VPLS-ID: ${esc(rec.vplsId)}</div>` : ""}`
        : `<div class="pt">${esc(l.pw.kind)} ${esc(l.pw.id)}</div><div>VC-ID: ${esc(l.pw.vcId)}</div>${tr.sdpKey ? `<div>${ol(tr.sdpKey, "SDP " + esc(l.pw.sdpId))}</div>` : ""}`;
      const tldpCell = `<div class="pt">${t && /targeted|AToM/i.test((t.clients || []).join(" ")) ? "T-LDP" : (rec.signaling || "PW").replace(/^BGP-AD \+ /, "")}</div>
        <div>${t && t.uptime ? esc(t.uptime) : "—"}</div><div>${t ? pill(/oper/i.test(t.state) ? "up" : t.state || "unknown") : pill(l.pw.oper)}</div>`;
      const peCell = `<div class="pt">${fe.vendor ? (fe.vendor === "nokia" ? "◆ NOKIA" : "◆ CISCO") : "◇ UNKNOWN"}</div>
        <div class="pn">${ol(fe.peKey, esc(fe.ip || "?"))}</div>${fe.name && fe.name !== fe.ip ? `<div>${esc(fe.name)}</div>` : ""}<div>${pill(l.pw.oper)}</div>`;
      const ceCell = cs === "ce" ? `<div class="pt">▣ Remote CE</div><div class="pn">${esc(ce.name)}</div><div>${esc(ce.port || "")}</div>${l.remote && l.remote.acs ? `<div class="muted">${esc(((l.remote.acs || []).find(a => a.ce) || {}).id || "")}</div>` : ""}`
        : cs === "unreachable" ? `<div class="pt">⚠ PE unreachable</div><div>${esc(fe.error || "NETCONF / ODL error")}</div>`
        : cs === "missing" ? `<div class="pt">? Remote CE</div><div>far end not collected</div><div class="muted">Trace far ends or Collect far ends</div>`
        : cs === "noservice" ? `<div class="pt">? Service not found</div><div>on the far-end PE</div>`
        : cs === "self" ? `<div class="pt">same PE</div>`
        : `<div class="pt">? Remote CE</div><div>Not discovered</div><div class="muted">No LLDP on PE</div>`;
      const back = l.remotePw && l.remotePw.transport ? transportHTML(l.remotePw.transport, `Return path from ${fe.name || fe.ip}`) : "";
      return `<div class="e2e-prow b-${cs}">
          <div class="e2e-pcell">${svcCell}</div><span class="e2e-arrow">→</span>
          <div class="e2e-pcell">${tldpCell}</div><span class="e2e-arrow">→</span>
          <div class="e2e-pcell v-${fe.vendor || "x"}">${peCell}</div><span class="e2e-arrow">→</span>
          <div class="e2e-pcell c-${cs}">${ceCell}</div>
          <details class="e2e-tr"><summary>Transport path and connected ports</summary>
            ${transportHTML(tr, "Outbound from this PE")}${walkHTML(l.walk)}${back}</details>
        </div>`;
    }).join("");
    return `<h4 style="margin:14px 0 8px">All ${rec.legs.length} ${rec.type === "bridge-domain" || rec.type === "vpls" ? "VPLS peer" : "pseudowire"} paths${rec.tracedAt ? ` <span class="muted small">· live trace ${esc(rec.tracedAt.replace("T", " "))}</span>` : ""}</h4>
      <div class="e2e-prows">${rows}</div>`;
  }

  function accessListHTML(rec) {
    if ((rec.acs || []).length < 2) return "";
    return `<details class="e2e-tr" style="margin-top:8px"><summary>All ${rec.acs.length} access circuits</summary>
      <div class="e2e-path">${accessColumn(rec.acs).join("")}</div></details>`;
  }

  function headerHTML(rec, model) {
    const remoteCes = rec.legs.filter(l => remoteCe(l)).length, localCes = (rec.ces || []).length;
    const vendor = VEND[model.vendor] || model.vendor || "";
    const canTrace = /^https?:$/.test(location.protocol) && rec.legs.length;
    return `<div class="e2e-hdr"><div><div class="e2e-title">◆ ${esc(vendor)} E2E path · ${ol(rec.objKey, esc(rec.id))} ${pill(rec.status)}</div>
        <div class="muted">${esc(model.node)} → ${rec.legs.length} peer(s) | ${esc((SVC_HEAD[rec.type] || rec.type))}${rec.name && rec.name !== rec.id ? " · " + esc(rec.name) : ""}</div>
        <div class="e2e-badges"><span class="bd b-v">${esc(vendor)}</span><span class="bd b-t">${esc(SVC_HEAD[rec.type] || rec.type)}</span>
          ${rec.signaling ? `<span class="bd b-s">${esc(rec.signaling)}</span>` : ""}<span class="bd b-p">${rec.legs.length} peers</span>
          <span class="bd b-c">${localCes} local / ${remoteCes} remote CE(s) found</span></div></div>
      <div class="e2e-traceb">${canTrace
        ? `<button class="btn primary" data-e2e-trace="${esc(rec.key)}" title="Ask each far-end PE about this service now (Nokia: service sap and LLDP; Cisco: LLDP and L2VPN config), as the E2E dashboard does">Trace far ends live</button><div class="small muted" data-e2e-tracemsg></div>`
        : (rec.legs.length ? '<div class="small muted">Open this report from the viewer (Device report tab) to trace far ends live.</div>' : "")}</div></div>`;
  }

  function pathsHTML(rec, model) {
    if (model) CUR = model;
    return chainHTML(rec, model) + accessListHTML(rec) + peerRowsHTML(rec, model);
  }
  function legsHTML(rec, model) {
    if (model) CUR = model;
    return peerRowsHTML(rec, model);
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
        <div class="e2e-detail" id="e2e-detail">${sel ? `<div class="card e2e-svc">${headerHTML(sel, model)}
          ${sel.description ? `<p class="muted">${esc(sel.description)}</p>` : ""}${issuesHTML(sel)}${pathsHTML(sel, model)}</div>` : ""}</div>`;
    }
    async function trace(key, btn) {
      const msg = wrap.querySelector("[data-e2e-tracemsg]");
      const t0 = Date.now();
      btn.disabled = true;
      const tick = setInterval(() => { if (msg) msg.textContent = `Asking each far-end PE through ODL... ${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
      try {
        const r = await fetch("/api/e2e-trace", {method: "POST", headers: {"Content-Type": "application/json"},
                                                  body: JSON.stringify({node: model.node, service: key})});
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        const i = model.services.findIndex(s => s.key === key);
        if (i >= 0 && j.service) model.services[i] = j.service;
        Object.assign(model.objects, j.objects || {});
        if (j.counts) model.counts = j.counts;
        if (j.farEnds) model.farEnds = j.farEnds;
        clearInterval(tick);
        draw();
        const peers = Object.values((j.trace || {}).peers || {});
        const m2 = wrap.querySelector("[data-e2e-tracemsg]");
        if (m2) m2.textContent = `Traced ${peers.length} far end(s): ${peers.filter(p => p.status === "ce_found").length} with CE, ` +
          `${peers.filter(p => p.status === "unreachable").length} unreachable, ${peers.filter(p => p.status === "no-service").length} without the service.`;
      } catch (err) {
        clearInterval(tick);
        if (msg) msg.textContent = "Trace failed: " + err.message;
        btn.disabled = false;
      }
    }
    wrap.addEventListener("click", e => {
      if (e.target.closest("[data-e2e-obj]")) return;
      const tb = e.target.closest("[data-e2e-trace]");
      if (tb) { trace(tb.dataset.e2eTrace, tb); return; }
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
