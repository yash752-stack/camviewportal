/* Shift insights: renders /api/exams/{code}/insights (exam_rules.py).
   Every number here is computed server-side; this file only draws. */
(function () {
  "use strict";
  const $ = s => document.querySelector(s);
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const fmt = n => (n == null ? "—" : Number(n).toLocaleString());
  const SC = ["#3B5877", "#B07A2A", "#7189A4", "#8A97A6"];
  const shc = s => SC[(+s - 1) % SC.length];
  const PC = {High: "#B6403A", Medium: "#3B5877", Low: "#B8C0CA"};
  const TYPE_C = {INM: "#5E6B7A", CD: "#7189A4", ZI: "#2F4760", MD: "#B6403A", CT: "#8F332E", NP: "#B07A2A",
                  CHT: "#C2410C", MPS: "#0E7490", TP: "#8A97A6", TO: "#B8C0CA", TT: "#6B5B95", FOP: "#A16207",
                  SHE: "#7C3AED", SOR: "#0891B2", SAS: "#D97706", FSD: "#DC2626", VD: "#0F766E", PB: "#BE185D", WC: "#4F46E5"};
  const tc = c => TYPE_C[c] || "#8A97A6";
  const STAGE = {pre: "Pre exam", during: "During exam", whole: "Whole day"};
  const isWH = x => x && x.sector === "warehouse";
  const stageTxt = x => isWH(x) ? "Warehouse · whole shift" : STAGE[x.stage];
  const whNote = () => D.has_warehouse ? " Warehouse (procurement centre) alerts have no exam window, so they are counted for the whole shift." : "";
  let D = null, DAYS = [], TAB = "stats", SUB = "breakdown", STG = "pre", MOD = null, UTYPE = null, HSH = null, CLK = "type";

  function sw(v) {
    if (v === null || v === undefined) return '<span class="sw nw">new</span>';
    const c = v > 0 ? "up" : v < 0 ? "dn" : "";
    return `<span class="sw ${c}">${v > 0 ? "+" : ""}${v}%</span>`;
  }
  function bar(v, mx, col) {
    return `<div class="bw"><div class="tk"><i style="width:${mx ? Math.max(1.5, 100 * v / mx) : 0}%;background:${col}"></i></div><span>${fmt(v)}</span></div>`;
  }
  function card(title, note, body, take) {
    return `<div class="card"><h2>${title}</h2>${note ? `<p class="note">${note}</p>` : ""}${body}${take ? `<div class="take">${take}</div>` : ""}</div>`;
  }
  function shLeg() { return `<div class="leg">${D.shifts.map(s => `<span><i style="background:${shc(s)}"></i>Shift ${s}</span>`).join("")}</div>`; }
  const S = () => D.shifts;

  async function load() {
    const q = DAYS.length ? `?days=${DAYS.join(",")}` : "";
    const r = await fetch(`/api/exams/${encodeURIComponent(EXAM)}/insights${q}`);
    D = await r.json();
    if (!MOD && D.analysis.length) MOD = (D.analysis.find(a => a.stage === STG) || D.analysis[0]).code;
    if (!UTYPE && D.unusual.length) UTYPE = D.unusual[0].code;
    if (!HSH) HSH = String(D.shifts[0]);
    await drawWindows();
    drawDetails();
    drawSummary();
    draw();
  }

  // ── exam windows: shown, checked, editable ────────────────────────────────
  async function drawWindows() {
    const r = await (await fetch(`/api/exams/${encodeURIComponent(EXAM)}/windows`)).json();
    const dates = [...new Set(r.windows.map(w => w.date))];
    const srcTxt = {configured: "confirmed by operator", inm: "inferred from Invigilator Not Moving", density: "guessed from alert density"};
    let h = "";
    if (dates.length > 1) {
      h += `<div class="daychips">${dates.map(d => `<button data-d="${d}" class="${DAYS.includes(d) ? "on" : ""}">${d}</button>`).join("")}<button data-d="" class="${DAYS.length ? "" : "on"}">All days</button></div>`;
    }
    r.windows.forEach((w, i) => {
      const tw = r.trunk[i] || {};
      h += `<div class="wrow" style="--c:${shc(w.shift)}" data-i="${i}"><b>${dates.length > 1 ? w.date + " · " : ""}${w.name}</b>
        <span>Exam window <input type="time" class="ws" value="${w.start}"> to <input type="time" class="we" value="${w.end}"></span>
        <span class="src">${srcTxt[w.source] || w.source}</span>
        <span style="color:var(--ink-3);font-size:12px">Trunk windows: arrival ${tw.arrival ? tw.arrival.join("–") : "—"}, opening ${tw.opening ? tw.opening.join("–") : "—"}</span></div>`;
    });
    r.checks.forEach(c => {
      h += `<div class="check"><span>${esc(c.text)}</span><button class="btn" data-fix="${c.date}|${c.shift}|${c.suggested_start}">Use ${c.suggested_start}</button></div>`;
    });
    if (r.windows.length) h += `<div><button class="btn pri" id="wsave">Confirm exam windows</button> <span id="wmsg" style="font-size:12px;color:var(--ink-3)"></span></div>`;
    $("#windows").innerHTML = h;
    $("#windows").querySelectorAll(".daychips button").forEach(b => b.onclick = () => { DAYS = b.dataset.d ? [b.dataset.d] : []; load(); });
    $("#windows").querySelectorAll("[data-fix]").forEach(b => b.onclick = () => {
      const [d, s, t] = b.dataset.fix.split("|");
      const i = r.windows.findIndex(w => w.date === d && String(w.shift) === s);
      if (i >= 0) $(`.wrow[data-i="${i}"] .ws`).value = t;
      $("#wmsg").textContent = "Start changed — confirm to apply.";
    });
    const save = $("#wsave");
    if (save) save.onclick = async () => {
      const body = {windows: r.windows.map((w, i) => ({date: w.date, start: $(`.wrow[data-i="${i}"] .ws`).value, end: $(`.wrow[data-i="${i}"] .we`).value}))};
      $("#wmsg").textContent = "Saving and re-reading the exam…";
      const res = await fetch(`/api/exams/${encodeURIComponent(EXAM)}/windows`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      const j = await res.json();
      if (!j.ok) { $("#wmsg").textContent = j.error || "Could not save."; return; }
      load();
    };
  }

  // ── exam details and the per-shift table ──────────────────────────────────
  let EDIT = false;
  function drawDetails() {
    const E = D.exam || {}, dt = D.details || {}, T = D.summary_table || [];
    const nm = {exam_type: "Exam type", post: "Post", stage: "Stage", city: "City"};
    const date = E.date ? new Date(E.date + "T00:00").toLocaleDateString("en-GB", {day: "numeric", month: "short", year: "numeric"}) : "";
    const facts = [["Exam type", dt.exam_type], ["Post", dt.post], ["Stage", dt.stage], ["Exam date", date], ["City", E.city],
      ["Centres", D.centre_split && D.centre_split.warehouse ? `${D.centre_split.exam} exam · ${D.centre_split.warehouse} procurement` : D.centres],
      ["Cameras", E.cameras], ["Shifts", S().length]];
    const span = s => (D.summary.find(x => x.shift === s) || {}).shift_span || "";
    let h = `<div class="dfacts">${facts.map(([k, v]) => `<div><span>${k}</span><b>${v === undefined || v === "" || v === null ? "—" : esc(v)}</b></div>`).join("")}</div>`;
    h += `<table class="t dtab"><tr><th>Exam details${dt.stage || date ? `<div class="sub2">${esc([dt.stage, date].filter(Boolean).join(" · "))}</div>` : ""}</th>${S().map(s => `<th style="color:${shc(s)}">Shift ${s}<div class="sub2">${esc(span(s))}</div></th>`).join("")}${S().length > 1 ? `<th>Both shifts<div class="sub2">${S().length} shifts</div></th>` : ""}</tr>
      ${T.map(r => `<tr><td>${esc(r.label)}${r.source === "entered" && r.by_shift.every(v => v == null) ? ' <span class="hint">enter below</span>' : ""}</td>${r.by_shift.map(v => `<td class="n">${fmt(v)}</td>`).join("")}${S().length > 1 ? `<td class="n"><b>${fmt(r.both)}</b></td>` : ""}</tr>`).join("")}</table>`;
    const notes = [];
    if (!D.has_tickets) notes.push("This export has no Ticket ID column, so ticket counts are blank.");
    else notes.push("Tickets created are the distinct Ticket IDs in the export; resolved tickets come from the ticketing dashboard.");
    notes.push("Candidates, cameras scheduled and tickets resolved are entered by the operator.");
    h += `<p class="note">${notes.join(" ")} <button class="btn" id="dedit">${EDIT ? "Close" : "Edit exam details"}</button></p>`;
    if (EDIT) {
      const per = (k, lab) => `<tr><td>${lab}</td>${S().map(s => `<td><input type="number" min="0" data-k="${k}" data-s="${s}" value="${(dt[k] || {})[s] ?? ""}"></td>`).join("")}</tr>`;
      h += `<div class="dform"><div class="dtext">${Object.entries(nm).map(([k, l]) => `<label>${l}<input type="text" maxlength="120" data-t="${k}" value="${esc(dt[k] || "")}" placeholder="${k === "city" ? esc(E.city || "") : ""}"></label>`).join("")}</div>
        <table class="t"><tr><th></th>${S().map(s => `<th style="color:${shc(s)}">Shift ${s}</th>`).join("")}</tr>${per("candidates", "Candidates")}${per("cameras_scheduled", "Cameras scheduled")}${per("tickets_resolved", "Tickets resolved")}</table>
        <button class="btn pri" id="dsave">Save details</button> <span id="dmsg" style="font-size:12px;color:var(--ink-3)"></span></div>`;
    }
    $("#details").innerHTML = h;
    $("#dedit").onclick = () => { EDIT = !EDIT; drawDetails(); };
    const sv = $("#dsave");
    if (sv) sv.onclick = async () => {
      const body = {};
      $("#details").querySelectorAll("[data-t]").forEach(i => body[i.dataset.t] = i.value);
      $("#details").querySelectorAll("[data-k]").forEach(i => { (body[i.dataset.k] = body[i.dataset.k] || {})[i.dataset.s] = i.value; });
      $("#dmsg").textContent = "Saving…";
      const j = await (await fetch(`/api/exams/${encodeURIComponent(EXAM)}/details`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})).json();
      if (!j.ok) { $("#dmsg").textContent = j.error || "Could not save."; return; }
      EDIT = false; load();
    };
  }

  function drawSummary() {
    $("#summary").innerHTML = D.summary.map(s => {
      const p = D.priority.alerts[String(s.shift)] || {};
      const pt = (p.High || 0) + (p.Medium || 0) + (p.Low || 0) || 1;
      return `<div class="sh" style="--c:${shc(s.shift)}"><div class="t">Shift ${s.shift} · ${esc(s.shift_span)}</div>
        <div class="big"><b>${fmt(s.total)}</b><span>alerts · exam window ${esc(s.window)}</span></div>
        <div class="kv"><span>During the exam</span><b>${fmt(s.exam)}</b></div>
        ${s.warehouse ? `<div class="kv"><span>Warehouse (whole shift)</span><b>${fmt(s.warehouse)}</b></div>` : ""}
        <div class="kv"><span>Before the exam (setup)</span><b>${fmt(s.pre)}</b></div>
        ${s.post ? `<div class="kv"><span>After the exam</span><b>${fmt(s.post)}</b></div>` : ""}
        <div class="kv"><span>Busiest 30 minutes</span><b>${esc(s.peak_slot)} (${fmt(s.peak_n)})</b></div>
        <div class="kv"><span>Cameras alerting · centres</span><b>${fmt(s.cameras)} · ${fmt(s.centres)}</b></div>
        <div class="kv"><span>Priority of alerts</span><b>${["High", "Medium", "Low"].map(k => `${k} ${fmt(p[k] || 0)}`).join(" · ")}</b></div>
        <div class="pbar">${["High", "Medium", "Low"].map(k => `<i style="width:${100 * (p[k] || 0) / pt}%;background:${PC[k]}"></i>`).join("")}</div></div>`;
    }).join("");
  }

  // ── Alert Stats ───────────────────────────────────────────────────────────
  const SUBS = [["breakdown", "Alert breakdown", "Shift 1 against Shift 2, by alert type, centre, camera and priority"],
                ["timing", "Alert timing", "When alerts fire inside the exam windows"],
                ["unusual", "Unusual alert rate", "Centres, cameras and locations out of line"]];

  function stats() {
    let h = `<div class="sub">${SUBS.map(s => `<button data-s="${s[0]}" class="${SUB === s[0] ? "on" : ""}" style="--c:#3B5877">${s[1]}<small>${s[2]}</small></button>`).join("")}</div>`;
    if (SUB === "breakdown") h += breakdown();
    if (SUB === "timing") h += timing();
    if (SUB === "unusual") h += unusual();
    return h;
  }

  function breakdown() {
    const two = S().length > 1;
    const f = D.features, mxA = Math.max(1, ...f.flatMap(x => x.alerts)), mxC = Math.max(1, ...f.flatMap(x => x.cameras)), mxP = Math.max(1, ...f.flatMap(x => x.per_camera));
    let rows = f.map(x => `<tr><td>${esc(x.label)}<div style="font-size:11px;color:var(--ink-3)">${stageTxt(x)}</div></td>
      <td>${x.alerts.map((v, i) => bar(v, mxA, shc(S()[i]))).join("")}</td>
      <td>${x.cameras.map((v, i) => bar(v, mxC, shc(S()[i]))).join("")}</td>
      <td>${x.per_camera.map((v, i) => bar(v, mxP, shc(S()[i]))).join("")}</td>
      <td class="n">${two ? sw(x.swing) : "—"}</td></tr>`).join("");
    let h = card("Features and cameras: alert wise swing between shifts",
      "Exam alerts are counted in the exam windows, so a long setup in one shift does not distort the comparison." + whNote() + " Pre-exam models (trunk, furniture) are read in Alert Analysis.",
      shLeg() + `<table class="t"><tr><th>Alert type</th><th>Alerts</th><th>Cameras raising it</th><th>Alerts per camera</th><th class="n">Swing</th></tr>${rows}</table>`,
      takeFeatures());
    // centre swing
    const cs = D.centre_swing;
    const mxc = Math.max(1, ...cs.flatMap(c => c.alerts));
    h += card("Centre wise swing: change between Shift 1 and Shift 2", `Exam-window alerts per exam centre${D.has_warehouse ? ", and whole-shift alerts per procurement centre" : ""}. Showing ${cs.length} of ${D.centre_count} centres (top 10 or top 5%, whichever is more), busiest first.`,
      shLeg() + `<table class="t"><tr><th>Centre</th><th>Alerts by shift</th><th class="n">Swing</th></tr>${cs.map(c =>
        `<tr><td>${esc(c.name)}<div style="font-size:11px;color:var(--ink-3)">${isWH(c) ? "Procurement centre · " : ""}Code ${esc(c.code)}</div></td><td>${c.alerts.map((v, i) => bar(v, mxc, shc(S()[i]))).join("")}</td><td class="n">${two ? sw(c.swing) : "—"}</td></tr>`).join("")}</table>`);
    if (two) {
      const cw = D.camera_swing, mxw = Math.max(1, ...cw.flatMap(c => c.alerts));
      h += card("Camera wise swing: change between Shift 1 and Shift 2", `Cameras that alerted in both shifts (${D.camera_both}): exam cameras in the exam windows${D.has_warehouse ? ", warehouse cameras across the shift" : ""}. Biggest change first.`,
        shLeg() + (cw.length ? `<table class="t"><tr><th>Camera</th><th>Centre · location</th><th>Alerts by shift</th><th class="n">Swing</th></tr>${cw.map(c =>
          `<tr><td class="n" style="text-align:left">${esc(c.camera)}</td><td>${esc(c.centre)} · ${esc(c.zone)}</td><td>${c.alerts.map((v, i) => bar(v, mxw, shc(S()[i]))).join("")}</td><td class="n">${sw(c.swing)}</td></tr>`).join("")}</table>` : `<div class="empty">No camera alerted in both shifts.</div>`));
    }
    // priority
    const pr = D.priority, mxp = Math.max(1, ...pr.by_type.flatMap(r => r.by_shift.map(b => b[0] + b[1] + b[2])));
    const pbars = (b) => { const t = b[0] + b[1] + b[2]; return `<div class="bw"><div class="tk" style="display:flex;width:${Math.max(4, 100 * t / mxp)}%;flex:none;min-width:0">${["High", "Medium", "Low"].map((k, i) => `<i style="width:${t ? 100 * b[i] / t : 0}%;background:${PC[k]}"></i>`).join("")}</div><span style="min-width:150px;text-align:left">${b[0]} high · ${b[1]} med · ${b[2]} low</span></div>`; };
    h += card("Priority by camera: how often a camera raises each alert type",
      `Priority belongs to a camera and an alert type together: the number of times that camera raised that type in the shift. ${esc(pr.rule)}. Severity (what kind of alert) is unchanged; priority sits beside it. Bars count camera and alert-type pairs.`,
      `<div class="leg">${["High", "Medium", "Low"].map(k => `<span><i style="background:${PC[k]}"></i>${k}</span>`).join("")}</div>
       <table class="t"><tr><th>Alert type</th>${S().map(s => `<th style="color:${shc(s)}">Shift ${s}</th>`).join("")}</tr>${pr.by_type.map(r =>
        `<tr><td>${esc((D.features.find(f => f.code === r.code) || D.analysis.find(a => a.code === r.code) || {}).label || r.label)}</td>${r.by_shift.map(b => `<td>${pbars(b)}</td>`).join("")}</tr>`).join("")}</table>`,
      takePriority());
    return h;
  }
  function takeFeatures() {
    if (S().length < 2) return "";
    const f = D.features.filter(x => x.alerts[0] + x.alerts[1] >= 10);
    const up = f.filter(x => x.swing === null || x.swing >= 25).map(x => `${x.label} (${x.swing === null ? "new" : "+" + x.swing + "%"})`);
    const dn = f.filter(x => x.swing !== null && x.swing <= -25).map(x => `${x.label} (${x.swing}%)`);
    return `${up.length ? "Rose in Shift 2: " + up.join(", ") + ". " : ""}${dn.length ? "Fell: " + dn.join(", ") + ". " : ""}${!up.length && !dn.length ? "No alert type with 10+ alerts moved by more than 25%." : ""}`;
  }
  function takePriority() {
    let best = null;
    D.priority.by_type.forEach(r => r.by_shift.forEach((b, i) => { if (!best || b[0] > best.n) best = {n: b[0], label: r.label, s: S()[i]}; }));
    return best && best.n ? `Most persistent: ${esc(best.label)}, with ${best.n} camera(s) at High priority in Shift ${best.s}.` : "No camera reached High priority.";
  }

  function timing() {
    const types = [...new Set(D.clock.flatMap(c => Object.keys(c.by_type)))];
    const zones = [...new Set(D.clock.flatMap(c => Object.keys(c.by_zone)))];
    const keys = CLK === "type" ? types : zones;
    const ZC = {"Class Room": "#5E6B7A", "Control Room": "#7189A4", "Entry / Exit": "#2F4760", "Strong Room": "#B07A2A",
                "WH Entry / Exit": "#0F766E", "WH Storage Area": "#7C3AED", "WH Other Area": "#0891B2"};
    const col = k => CLK === "type" ? tc(k) : (ZC[k] || "#8A97A6");
    const lab = k => CLK === "type" ? ((D.analysis.find(a => a.code === k) || {}).label || k) : k;
    const W = Math.max(640, D.clock.length * 46), H = 260, pb = 46, pl = 30, mx = Math.max(1, ...D.clock.map(c => c.total));
    const bw = (W - pl) / Math.max(1, D.clock.length);
    let svg = "";
    [0, 0.5, 1].forEach(g => { const y = H - pb - g * (H - pb - 14); svg += `<line x1="${pl}" x2="${W}" y1="${y}" y2="${y}" stroke="#E6EAEE"/><text x="0" y="${y + 4}">${Math.round(g * mx)}</text>`; });
    D.clock.forEach((c, i) => {
      const x = pl + i * bw + bw * 0.12, w = bw * 0.76; let acc = 0;
      keys.forEach(k => { const v = (CLK === "type" ? c.by_type : c.by_zone)[k] || 0; if (!v) return; const hh = v / mx * (H - pb - 14); svg += `<rect x="${x}" y="${H - pb - acc - hh}" width="${w}" height="${hh}" fill="${col(k)}"><title>Shift ${c.shift} ${c.slot}: ${esc(lab(k))} ${v}</title></rect>`; acc += hh; });
      svg += `<text x="${x + w / 2}" y="${H - pb - acc - 4}" text-anchor="middle" style="font-weight:700;fill:#1E2A3D">${c.total}</text>`;
      svg += `<text x="${x + w / 2}" y="${H - pb + 14}" text-anchor="middle">${esc(c.slot.replace(" AM", "").replace(" PM", ""))}</text>`;
      svg += `<rect x="${x}" y="${H - pb + 22}" width="${w}" height="4" fill="${shc(c.shift)}"/>`;
    });
    let h = card("Clock time: alerts by actual time",
      "Alerts in each 30-minute slot of the exam windows, on real clock time; setup alerts before the exam are left out." + (D.has_warehouse ? " Warehouse alerts are placed in the same slots." : "") + " The strip under each bar is its shift.",
      `<div class="sub"><button data-clk="type" class="${CLK === "type" ? "on" : ""}">By alert type</button><button data-clk="zone" class="${CLK === "zone" ? "on" : ""}">By camera location</button></div>
       <div class="leg">${keys.map(k => `<span><i style="background:${col(k)}"></i>${esc(lab(k))}</span>`).join("")}</div>${shLeg()}
       <svg class="svgc" viewBox="0 0 ${W} ${H}" width="100%">${svg}</svg>`,
      D.summary.map(s => `Shift ${s.shift} peaks ${esc(s.peak_slot)} with ${s.peak_n} alerts.`).join(" "));
    h += todClocks();
    // per type over time
    h += card("Alerts over time: each alert type through the shift",
      "Counted alerts in each 30-minute slot, per shift, for the alert type's own scope (during-exam models inside the window; others across the shift).",
      `<table class="t"><tr><th>Alert type</th>${S().map(s => `<th style="color:${shc(s)}">Shift ${s}</th>`).join("")}</tr>${D.analysis.map(a =>
        `<tr><td>${esc(a.label)}</td>${S().map(s => `<td>${spark(a.slots[String(s)] || {}, shc(s))}</td>`).join("")}</tr>`).join("")}</table>`);
    return h;
  }
  // the manager's time-of-day clocks: one 12-hour face per shift, the exam
  // window as a shaded wedge, one line per 30-minute slot (shared scale)
  function todClocks() {
    const mins = t => { const [h, m] = t.split(":").map(Number); return h * 60 + m; };
    const f12 = m => { const h = Math.floor(m / 60) % 24, mm = m % 60; return `${h % 12 || 12}:${String(mm).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`; };
    const first = {};
    D.windows.forEach(w => { if (!first[w.shift] || w.date < first[w.shift].date) first[w.shift] = w; });
    const sh = Object.keys(first).map(Number).sort((a, b) => a - b);
    if (!sh.length || !D.clock.length) return "";
    const data = sh.map(s => {
      const w = first[s], st = mins(w.start), en = mins(w.end);
      const cs = D.clock.filter(c => c.shift === s && c.date === w.date);
      const slots = cs.map(c => ({m: mins(c.start), n: c.total, top: Object.entries(c.by_type).sort((a, b) => b[1] - a[1]).slice(0, 3)}));
      let pk = -1; slots.forEach((v, i) => { if (v.n && (pk < 0 || v.n > slots[pk].n)) pk = i; });
      return {s, st, en, slots, pk, setup: (D.summary.find(x => x.shift === s) || {}).pre || 0};
    });
    const mx = Math.max(1, ...data.flatMap(d => d.slots.map(v => v.n)));
    const pt = (m, r) => { const a = ((m % 720) / 720) * 2 * Math.PI - Math.PI / 2; return [150 + Math.cos(a) * r, 150 + Math.sin(a) * r]; };
    const lab = c => (D.analysis.find(a => a.code === c) || {}).label || c;
    const face = d => {
      const col = shc(d.s), ro = 116, ri = 38, span = Math.max(30, Math.min(d.en - d.st, 719)), big = span > 360 ? 1 : 0;
      const p1 = pt(d.st, ri), p2 = pt(d.st, ro), p3 = pt(d.st + span, ro), p4 = pt(d.st + span, ri);
      let g = `<path d="M${p1} L${p2} A${ro} ${ro} 0 ${big} 1 ${p3} L${p4} A${ri} ${ri} 0 ${big} 0 ${p1} Z" fill="${col}" fill-opacity="0.10"/>
        <circle cx="150" cy="150" r="${ro}" fill="none" stroke="#D5DAE0"/><circle cx="150" cy="150" r="${ri}" fill="none" stroke="#D5DAE0"/>`;
      const lo = d.st % 720;
      for (let n = 0; n < 12; n++) { const m = n * 60, on = (m >= lo && m <= lo + span) || (m + 720 >= lo && m + 720 <= lo + span), q = pt(m, ro + 15);
        g += `<text x="${q[0]}" y="${q[1] + 4}" text-anchor="middle" style="font-size:${on ? 15 : 13}px;font-weight:${on ? 700 : 400};fill:${on ? col : "#8B95A3"}">${n || 12}</text>`; }
      d.slots.forEach(v => { if (!v.n) return; const m = v.m + 15, a = pt(m, ri + 2), b = pt(m, ri + 2 + v.n / mx * (ro - ri - 4));
        g += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${col}" stroke-width="${d.slots.length > 12 ? 6 : 9}" stroke-linecap="round"><title>${f12(v.m)} to ${f12(v.m + 30)}: ${v.n} alerts</title></line>`; });
      if (d.pk >= 0) g += `<text x="150" y="147" text-anchor="middle" style="font-size:12px;font-weight:700;fill:#1E2A3D">Peak</text><text x="150" y="163" text-anchor="middle" style="font-size:12px;font-weight:700;fill:${col}">${f12(d.slots[d.pk].m)}</text>`;
      return `<svg viewBox="0 0 300 300" width="240" height="240" style="flex:none">${g}</svg>`;
    };
    const list = d => d.slots.map(v => `<div style="padding:5px 0;border-bottom:1px solid #E6EAEE;font-size:12.5px"><b style="color:${shc(d.s)}">${f12(v.m)} to ${f12(v.m + 30)}</b> <span style="color:var(--ink-3)">· ${fmt(v.n)} alerts</span>${v.top.length ? `<br><span style="font-size:11.5px;color:var(--ink-2)">${v.top.map(([c, n]) => `${esc(lab(c))} ${n}`).join(", ")}</span>` : ""}</div>`).join("");
    const body = data.map(d => `<h3 style="font-size:13px;color:${shc(d.s)};margin:10px 0 6px">Shift ${d.s} · exam window ${f12(d.st)} to ${f12(d.en)}</h3>
      <div style="display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap">${face(d)}<div style="flex:1;min-width:220px">${list(d)}</div></div>`).join("");
    const take = data.filter(d => d.pk >= 0).map(d => `Shift ${d.s} peaks in the slot starting <b>${f12(d.slots[d.pk].m)}</b> with ${d.slots[d.pk].n} alerts`).join(" and ")
      + ". Setup alerts before the exam are left out here: " + data.map(d => `${fmt(d.setup)} before Shift ${d.s}`).join(" and ") + ".";
    return card("Time of day: when alerts fire in each shift",
      "Alerts in each 30-minute slot of the exam windows" + (D.has_warehouse ? " (warehouse alerts placed in the same slots)" : "") + ", on each shift's own 12-hour clock. The shaded wedge is the exam window. Setup alerts before the exam are not included. Both clocks use the same scale, so line lengths can be compared."
      + (D.windows.length > sh.length ? " Each shift is drawn on its first day." : ""), body, take);
  }
  function spark(slots, col) {
    const ks = Object.keys(slots).map(Number).sort((a, b) => a - b);
    if (!ks.length) return `<span class="empty">none</span>`;
    const mx = Math.max(...ks.map(k => slots[k])), lo = ks[0], hi = ks[ks.length - 1], n = (hi - lo) / 30 + 1, w = Math.max(60, n * 10);
    let r = "";
    for (let m = lo, i = 0; m <= hi; m += 30, i++) { const v = slots[m] || 0; const hh = v / mx * 26; r += `<rect x="${i * 10}" y="${28 - hh}" width="8" height="${hh}" fill="${col}"><title>${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")} ${v}</title></rect>`; }
    const t = m => { const h = Math.floor(m / 60), ap = h < 12 ? "a" : "p"; return `${h % 12 || 12}${m % 60 ? ":30" : ""}${ap}`; };
    return `<svg viewBox="0 0 ${w} 30" width="${w}" height="30">${r}</svg> <span style="font-size:11px;color:var(--ink-3)">${t(lo)}–${t(hi + 30)} · peak ${mx}</span>`;
  }

  function unusual() {
    let h = "";
    // heat map
    const cols = D.heat.cols, rows = (D.heat.rows[HSH] || []);
    const k = rows.length;
    const mx = Math.max(1, ...rows.flatMap(r => r.vals));
    const shade = v => v ? `background:color-mix(in srgb,${shc(+HSH)} ${Math.round(12 + 80 * v / mx)}%,#fff);color:${v / mx > .55 ? "#fff" : "#1E2A3D"}` : "background:#F4F5F7;color:#B8C0CA";
    const zones = [...new Set(cols.map(c => c.zone))];
    h += card("Centre heatmap: camera location × alert type",
      `Exam-window alerts${D.has_warehouse ? " (warehouse alerts across the shift)" : ""}. Busiest ${k} of ${D.centre_count} centres in the chosen shift (top 10 or top 5%); darker means more, scaled within the shift.`,
      `<div class="sub">${S().map(s => `<button data-hsh="${s}" class="${HSH === String(s) ? "on" : ""}" style="--c:${shc(s)}">Shift ${s}</button>`).join("")}</div>
       <table class="hm"><tr><th></th>${zones.map(z => `<th colspan="${cols.filter(c => c.zone === z).length}" style="border-bottom:2px solid #D5DAE0">${esc(z)}</th>`).join("")}<th></th></tr>
       <tr><th></th>${cols.map(c => `<th>${esc(c.label)}</th>`).join("")}<th>Total</th></tr>
       ${rows.slice(0, k).map(r => `<tr><td class="lab" title="${esc(r.name)}">${esc(r.name)}</td>${r.vals.map(v => `<td style="${shade(v)}">${v || ""}</td>`).join("")}<td style="font-weight:700">${r.total}</td></tr>`).join("")}</table>`);
    // unusual centres per type
    const u = D.unusual.find(x => x.code === UTYPE) || D.unusual[0];
    if (u) {
      const mxu = Math.max(1, ...u.rows.flatMap(r => r.by_shift));
      const fl = u.rows.filter(r => r.flag);
      h += card("Unusual centres, by alert type",
        `A centre outside the mean ± 1 standard deviation for that alert type is flagged. Every centre in the exam counts, including those with none. ${esc(u.label)}: mean ${u.mean}, standard deviation ${u.sd} per centre.`,
        `<div class="sub">${D.unusual.map(x => `<button data-ut="${x.code}" class="${x.code === u.code ? "on" : ""}" style="--c:${tc(x.code)}">${esc(x.label)}</button>`).join("")}</div>${shLeg()}
         <table class="t"><tr><th>Centre</th><th>By shift</th><th class="n">Total</th></tr>${(fl.length ? fl : u.rows.slice(-10)).sort((a, b) => b.total - a.total).map(r =>
          `<tr><td>${esc(r.name)}${r.flag ? `<span class="flag ${r.flag}">${r.flag === "high" ? "above mean + 1 SD" : "below mean − 1 SD"}</span>` : ""}</td><td>${r.by_shift.map((v, i) => bar(v, mxu, shc(S()[i]))).join("")}</td><td class="n">${r.total}</td></tr>`).join("")}</table>`,
        fl.length ? `${fl.filter(r => r.flag === "high").length} centre(s) unusually high, ${fl.filter(r => r.flag === "low").length} unusually low.` : "No centre is outside one standard deviation.");
    }
    // totals by alert type, all centres together
    const an = D.analysis, mxt = Math.max(1, ...an.flatMap(a => a.counted));
    const cs2 = D.centre_split || {};
    h += card("Totals by alert type: all centres together",
      `Each alert type across all ${D.centres} centres${cs2.warehouse ? ` (${cs2.exam} exam centres and ${cs2.warehouse} procurement centres)` : ""}, counted in its own scope: how many alerts, how many centres raised it, and the change between shifts.`,
      shLeg() + `<table class="t"><tr><th>Alert type</th><th>Alerts</th><th class="n">Centres</th><th class="n">Swing</th></tr>${an.map(a =>
        `<tr><td>${esc(a.label)}<div style="font-size:11px;color:var(--ink-3)">${stageTxt(a)}</div></td><td>${a.counted.map((v, i) => bar(v, mxt, shc(S()[i]))).join("")}</td><td class="n">${a.centre_count}</td><td class="n">${S().length > 1 ? sw(a.counted[0] ? Math.round((a.counted[1] - a.counted[0]) / a.counted[0] * 100) : (a.counted[1] ? null : 0)) : "—"}</td></tr>`).join("")}</table>`);
    // top/bottom cameras and sub-locations
    [["top_cameras", "Top and bottom cameras: highest and lowest across all centres", r => `${esc(r.camera)} <span style="color:var(--ink-3)">${esc(r.centre)} · ${esc(r.zone)}</span>`],
     ["top_sublocations", "Top and bottom sub-locations", r => `${esc(r.centre)} <span style="color:var(--ink-3)">· ${esc(r.zone)}</span>`]].forEach(([key, title, nm]) => {
      let b = "";
      S().forEach(s => {
        const t = D[key][String(s)]; if (!t) return;
        const mxx = Math.max(1, ...t.high.map(r => r.alerts));
        b += `<h3 style="font-size:13px;color:${shc(s)};margin:10px 0 4px">Shift ${s} · top ${t.k} of ${t.n}${t.listed < t.k ? `, first ${t.listed} listed` : ""} (typical ${t.typical})</h3><div class="g2">
          <table class="t"><tr><th>Highest</th><th></th></tr>${t.high.map(r => `<tr><td>${nm(r)}</td><td>${bar(r.alerts, mxx, shc(s))}</td></tr>`).join("")}</table>
          <table class="t"><tr><th>Lowest</th><th></th></tr>${t.low.map(r => `<tr><td>${nm(r)}</td><td>${bar(r.alerts, mxx, "#B8C0CA")}</td></tr>`).join("")}</table></div>`;
      });
      h += card(title, "All alerts in the shift. The top 10 or top 5%, whichever is more, each way.", b);
    });
    // scorecard + quadrant + concentration
    const sc = D.scorecard, mxs = Math.max(1, ...sc.flatMap(r => r.alerts));
    h += card("Camera location scorecard", "Exam-window alerts and reach (centres that raised any) per camera location." + (D.has_warehouse ? " Warehouse cameras are not part of this location split." : ""),
      shLeg() + `<table class="t"><tr><th>Location</th><th>Alerts</th><th>Reach</th><th>Mostly</th></tr>${sc.map(r =>
        `<tr><td><b>${esc(r.zone)}</b></td><td>${r.alerts.map((v, i) => bar(v, mxs, shc(S()[i]))).join("")}</td><td>${r.reach.map((v, i) => `<div style="font-family:var(--mono);color:${shc(S()[i])}">${v} of ${r.centres}</div>`).join("")}</td><td>${esc(r.dominant)} ${r.dominant_share}%</td></tr>`).join("")}</table>`);
    let q = "";
    S().forEach(s => {
      const x = D.quadrant[String(s)]; if (!x) return;
      const box = (k, t, d, c) => `<div style="border:2px solid ${c};border-radius:10px;padding:8px 12px"><b>${t}</b><div style="font-size:12px;color:var(--ink-3)">${d}</div>${(x[k] || []).slice(0, 8).map(r => `<div style="display:flex;justify-content:space-between;border-top:1px solid #E6EAEE;padding:3px 0;font-size:12px"><span>${esc(r.name)}</span><span class="mono">${r.alerts} · ${r.types} types</span></div>`).join("") || '<div class="empty">None</div>'}${(x.counts && x.counts[k] > 8) ? `<div class="empty">+${x.counts[k] - 8} more</div>` : ""}</div>`;
      q += `<h3 style="font-size:13px;color:${shc(s)};margin:10px 0 6px">Shift ${s} · medians ${x.median_alerts} alerts, ${x.median_types} types</h3><div class="g2">
        ${box("busy_varied", "Busy and varied", "Many alerts, many types: review first", "#B6403A")}${box("busy_narrow", "Busy, one-note", "Many alerts, few types: likely one issue", "#B07A2A")}
        ${box("quiet_varied", "Wide but quiet", "Few alerts, many types", "#3B5877")}${box("quiet_narrow", "Quiet and narrow", "Few alerts, few types", "#B8C0CA")}</div>`;
    });
    h += card("Volume against variety", "Exam centres split by how many exam-window alerts they raise and how many alert types, against that shift's own medians.", q,
      S().map(s => { const c = D.concentration[String(s)]; return c ? `Shift ${s}: the top centre holds ${c.top1}% of exam-window alerts, the top three ${c.top3}%.` : ""; }).join(" "));
    return h;
  }

  // ── Alert Analysis ────────────────────────────────────────────────────────
  function analysis() {
    const byStage = st => D.analysis.filter(a => a.stage === st).sort((a, b) => (isWH(a) - isWH(b)));
    let h = `<div class="grp">${["pre", "during", "whole"].map(st => `<button data-stg="${st}" class="${STG === st ? "on" : ""}">${STAGE[st]} <span style="font-weight:400;opacity:.7">${byStage(st).reduce((q, a) => q + a.counted.reduce((x, y) => x + y, 0), 0)}</span></button>`).join("")}</div>`;
    const mods = byStage(STG);
    if (!mods.length) return h + `<div class="card empty">No alert types in this stage for this exam.</div>`;
    if (!mods.find(a => a.code === MOD)) MOD = mods[0].code;
    h += `<div class="sub">${mods.map(a => `<button data-mod="${a.code}" class="${a.code === MOD ? "on" : ""}" style="--c:${tc(a.code)}">${esc(a.label)}<small>${isWH(a) ? "Warehouse · " : ""}${a.counted.reduce((x, y) => x + y, 0)} counted${a.stage !== "pre" && a.off_hours.reduce((x, y) => x + y, 0) ? " · " + a.off_hours.reduce((x, y) => x + y, 0) + " outside exam" : ""}</small></button>`).join("")}</div>`;
    const a = D.analysis.find(x => x.code === MOD);
    const scope = a.stage === "during" && !isWH(a) ? "inside the exam window" : "across the whole shift";
    let body = `<div class="isum" style="margin:0 0 12px">${S().map((s, i) => `<div class="sh" style="--c:${shc(s)}"><div class="t">Shift ${s}</div><div class="big"><b>${fmt(a.counted[i])}</b><span>counted ${scope}</span></div>
      <div class="kv"><span>Before the exam</span><b>${fmt(a.pre[i])}</b></div>${a.stage === "pre" || isWH(a) ? "" : `<div class="kv"><span>Outside the exam window</span><b>${fmt(a.off_hours[i])}</b></div>`}</div>`).join("")}</div>`;
    body += `<table class="t"><tr><th>When it fires</th>${S().map(s => `<th style="color:${shc(s)}">Shift ${s}</th>`).join("")}</tr><tr><td>30-minute slots</td>${S().map(s => `<td>${spark(a.slots[String(s)] || {}, shc(s))}</td>`).join("")}</tr></table>`;
    const k = a.centres.length, mxc = Math.max(1, ...a.centres.flatMap(c => c.by_shift));
    body += `<div class="g2" style="margin-top:12px"><div><h3 style="font-size:13px;margin-bottom:4px">Which ${isWH(a) ? "procurement " : ""}centres (${k} of ${a.centre_count})</h3>${shLeg()}<table class="t">${a.centres.slice(0, k).map(c =>
      `<tr><td>${esc(c.name)}</td><td>${c.by_shift.map((v, i) => bar(v, mxc, shc(S()[i]))).join("")}</td></tr>`).join("") || '<tr><td class="empty">None</td></tr>'}</table></div>
      <div><h3 style="font-size:13px;margin-bottom:4px">Hot cameras</h3><table class="t">${a.hot.map(c => `<tr><td class="mono">${esc(c.camera)}</td><td>${esc(c.centre)} · ${esc(c.zone)}</td><td class="n">${c.alerts}</td></tr>`).join("") || '<tr><td class="empty">None</td></tr>'}</table></div></div>`;
    let h2 = card(esc(a.label), isWH(a) ? `Warehouse model, ${esc(a.severity)} severity. A procurement centre has no exam window, so it is counted ${scope}.`
      : `${STAGE[a.stage]} model, ${esc(a.severity)} severity. Counted ${scope}; alerts outside the exam window are shown separately, not dropped.`, body);
    if (a.code === "TP" || a.code === "TO") h2 += trunk(a.code);
    if (a.risk && a.risk.rules) {
      const rb = a.risk.rules.map(r => `<div class="rule"><b>${r.hits}</b> of ${a.risk.total} — ${esc(r.text)}${r.examples.length ? `<div class="ex">e.g. ${r.examples.map(esc).join(" · ")}</div>` : ""}</div>`).join("");
      const combos = Object.entries(a.risk.by_shift || {}).map(([s, arr]) => `<div style="margin-top:6px;font-size:12.5px"><b style="color:${shc(+s)}">Shift ${s}:</b> ${arr.map(c => `${c.with.length ? c.with.join(" + ") : "nothing else"} ${c.n}`).join(" · ")}</div>`).join("");
      h2 += card(`Risk overlap: ${esc(a.label)} with other alerts`, "Each line counts this alert type's alerts where the other alert fired at the same centre (or in the same room, i.e. the same camera) within the stated time.", rb + combos);
    }
    return h + h2;
  }
  function trunk(code) {
    const kind = code === "TP" ? "arrival" : "opening";
    const T = D.trunk[kind]; if (!D.trunk.boxes) return "";
    const cnt = T.counts, bad = T.exceptions, n = bad.length;
    return card(`Trunk ${kind} against the authorised window`,
      `Judged against the exam's authorised trunk windows, shown with the exam windows above (the same ones the compliance report uses). Where none were set they follow the exam start: arrival ${D.rules.trunk.arrival[0]} to ${D.rules.trunk.arrival[1]} minutes before, opening the last ${D.rules.trunk.opening[0]} minutes. Per shift and centre, the first ${code === "TP" ? "Trunk Placed" : "Trunk Opened at or after the arrival"} is judged.`,
      `<div class="leg">${["ok", "early", "late", "none"].map(s => `<span><span class="st ${s}">${{ok: "in window", early: "early", late: "late", none: "not on camera"}[s]}</span> ${cnt[s]}</span>`).join("")}</div>
       <table class="t"><p class="note">${T.exception_count} box(es) outside the window; the ${n} furthest out are listed.</p>
       <table class="t"><tr><th>Centre</th><th>Shift</th><th>Window</th><th>Seen at</th><th class="n">Off by</th></tr>${bad.map(r =>
        `<tr><td>${esc(r.centre_name || r.centre)}</td><td>${r.shift}</td><td class="mono">${r.window.join("–")}</td><td class="mono">${r.at}</td><td class="n"><span class="st ${r.status}">${r.gap} min ${r.status}</span></td></tr>`).join("") || '<tr><td class="empty" colspan="5">Every box seen was in its window.</td></tr>'}</table>`,
      cnt.early + cnt.late > (cnt.ok || 0) ? "Most boxes fall outside the window. Check the exam start above before treating these as breaches." : "");
  }

  // ── rules ────────────────────────────────────────────────────────────────
  function rules() {
    const R = D.rules;
    const m = R.models.slice().sort((a, b) => isWH(a) - isWH(b)).map(x => `<tr><td><b>${esc(x.label)}</b>${x.adopted ? ' <span class="flag low">adopted from data</span>' : ""}${x.variant_of ? `<div style="font-size:11px;color:var(--ink-3)">${esc(x.variant_of)} detector at a warehouse camera</div>` : ""}</td><td>${isWH(x) ? "Warehouse" : "Exam"}</td><td>${isWH(x) ? "Whole shift" : STAGE[x.stage]}</td><td>${esc(x.severity)}${x.escalation ? " · " + esc(x.escalation) : ""}</td><td style="font-size:12px;color:var(--ink-2)">${x.risk.map(esc).join("<br>") || "—"}</td></tr>`).join("");
    return card("How the portal reads an exam", "These rules drive every number on this page and in the validation check. They live in backend/app/exam_rules.py and config/modalities.json.",
      `<div class="rules"><dl>
        <dt>Exam window</dt><dd>Opens with the first sustained ${esc(R.window.anchor)} (Invigilator Not Moving) cluster and closes with its last alert, rounded out to ${R.window.round} minutes. INM alerts more than ${R.window.cluster_gap} minutes from the rest are noise; clusters more than ${R.window.split_gap} minutes apart are different shifts. An operator can confirm or edit the window above, and a confirmed window always wins.</dd>
        <dt>Shifts and phases</dt><dd>Shift 1 runs from the first alert of the day to the end of its exam window, Shift 2 from there to the end of its own window. Alerts before a shift's window are pre-exam (setup).</dd>
        <dt>Stages</dt><dd>Pre exam models count across the whole shift; during-exam models count only inside the exam window and anything outside it is shown as off-hours; whole-day models count across the whole shift. Shift-to-shift comparisons use exam-window alerts only.</dd>
        <dt>Warehouse</dt><dd>Procurement-centre cameras (a WH sub-location, or a PC-xx centre code) sit in the same charts. They have no exam window, so their alerts count for the whole shift. On a warehouse camera, Zone Intrusion reads as Perimeter Breach and Crowd Detection as Worker Crowding. They never set the exam window, and are left out of the exam-only views (location scorecard, volume against variety).</dd>
        <dt>Severity</dt><dd>What kind of alert it is, fixed per model (table below), raised by camera location where the model says so.</dd>
        <dt>Priority</dt><dd>How persistent the camera is: the number of times that camera raised that alert type in the shift. High at ${R.priority.high} or more, Medium at ${R.priority.medium} to ${R.priority.high - 1}, Low below ${R.priority.medium}.</dd>
        <dt>Trunk windows</dt><dd>When no timetable is configured: arrival ${R.trunk.arrival[0]} to ${R.trunk.arrival[1]} minutes before the exam starts, opening the last ${R.trunk.opening[0]} minutes. An opening stamped up to ${R.trunk.tolerance} minutes before the box's arrival is channel noise. If most boxes open well before the inferred start, the page suggests an earlier start.</dd>
        <dt>Unusual centres</dt><dd>Outside the mean ± ${R.outlier_sd} standard deviation of per-centre counts for the alert type.</dd>
        <dt>Lists</dt><dd>Top ${R.top.min} or top ${Math.round(R.top.share * 100)}%, whichever is larger.</dd>
        <dt>Swing</dt><dd>(Shift 2 − Shift 1) ÷ Shift 1; "new" when Shift 1 had none.</dd>
      </dl></div>
      <table class="t" style="margin-top:14px"><tr><th>Model</th><th>Site</th><th>Stage</th><th>Severity</th><th>Risk overlaps checked</th></tr>${m}</table>`);
  }

  function draw() {
    document.querySelectorAll("#maintabs button").forEach(b => b.classList.toggle("on", b.dataset.t === TAB));
    $("#view").innerHTML = TAB === "stats" ? stats() : TAB === "analysis" ? analysis() : rules();
    const on = (sel, fn) => $("#view").querySelectorAll(sel).forEach(b => b.onclick = () => { fn(b); draw(); });
    on("[data-s]", b => SUB = b.dataset.s);
    on("[data-stg]", b => { STG = b.dataset.stg; MOD = null; });
    on("[data-mod]", b => MOD = b.dataset.mod);
    on("[data-ut]", b => UTYPE = b.dataset.ut);
    on("[data-hsh]", b => HSH = b.dataset.hsh);
    on("[data-clk]", b => CLK = b.dataset.clk);
    try { history.replaceState(null, "", `#${TAB}`); } catch (e) {}
  }
  document.querySelectorAll("#maintabs button").forEach(b => b.onclick = () => { TAB = b.dataset.t; draw(); });
  const h0 = (location.hash || "").slice(1); if (["stats", "analysis", "rules"].includes(h0)) TAB = h0;
  load().catch(e => { $("#view").innerHTML = `<div class="card">Could not load the insights: ${esc(e.message)}</div>`; });
})();
