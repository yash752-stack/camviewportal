/* CamView Examination Workspace — one persistent surface.
   Lens (multi-select modalities + facets) -> Queue (spine) -> Inspector (workflow) -> Lightbox. */
const WS = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const fmt = n => (n == null ? "" : n.toLocaleString("en-IN"));
  const esc = s => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const TIERNAME = { r: "Critical", o: "High", y: "Elevated", g: "Low" };
  const TIERORDER = ["r", "o", "y", "g"];

  let EXAM = "", BOARD = null;
  let selected = [];                       // selected modality codes
  let selectedDays = null;                 // selected exam days (null = all days)
  const filter = { district: null, tier: null };
  let selCentre = null, centreAlerts = [], lbIndex = -1, palItems = [], palCur = 0;
  let viewMode = "map";

  // ---- workflow state (operator notes / status) persisted locally ----
  const wkey = c => `camview:${EXAM}:${c}`;
  const getWork = c => { try { return JSON.parse(localStorage.getItem(wkey(c))) || { status: "Open", notes: [] }; } catch { return { status: "Open", notes: [] }; } };
  const setWork = (c, w) => localStorage.setItem(wkey(c), JSON.stringify(w));

  async function init(exam, defaultMod) {
    EXAM = exam;
    const p = new URLSearchParams(location.search);
    selected = (p.get("m") || defaultMod).split(",").filter(Boolean);
    document.addEventListener("keydown", onKey);
    $("#cmdk").onclick = openPal;
    $("#palscrim").onclick = closePal;
    $("#palinput").addEventListener("input", palSearch);
    $("#lbClose").onclick = closeLightbox; $("#lbscrim").onclick = closeLightbox;
    $("#lbPrev").onclick = () => openLightbox(lbIndex - 1);
    $("#lbNext").onclick = () => openLightbox(lbIndex + 1);
    $("#edx").onclick = closeEdit; $("#edcancel").onclick = closeEdit; $("#edscrim").onclick = closeEdit;
    $("#edsave").onclick = applyEdit;
    $("#shpick").onclick = () => $("#appendxl").click();
    $("#appendxl").onchange = onAppendPick;
    $("#shpickev").onclick = () => $("#appendevf").click();
    $("#appendevf").onchange = onAppendEvPick;
    $("#appenddate").onchange = () => loadShiftsForDate($("#appenddate").value);
    $("#shx").onclick = closeAppend; $("#shcancel").onclick = closeAppend; $("#shscrim").onclick = closeAppend;
    $("#shadd").onclick = () => { addShiftRow({}); renumberShifts(); };
    $("#shsave").onclick = applyAppend;
    $("#curx").onclick = closeCur;
    $("#curscrim").onclick = closeCur;
    $("#curno").onclick = () => decide(false);
    $("#curyes").onclick = () => decide(true);
    $("#curgen").onclick = () => generateCur(curPicked);
    $("#curauto").onclick = () => generateCur(null);
    setView(p.get("view") || "map");
    await loadBoard();
    const c = p.get("centre");
    if (c) { await selectCentre(c); const a = p.get("alert"); if (a !== null) openLightbox(+a); }
    const dq = p.get("district"); if (dq) openDistrict(dq);
  }

  function daysParam() { return selectedDays ? `&days=${selectedDays.join(",")}` : ""; }

  async function loadBoard() {
    const r = await fetch(`/api/exams/${EXAM}/board?modality=${selected.join(",")}${daysParam()}`);
    BOARD = await r.json();
    filter.district = null; filter.tier = null;
    renderLens(); renderQueue();
    // an open inspector must follow the new model selection: re-fetch its alerts
    // (stats, list and the alerts-over-time chart) so it isn't stale, or close it
    // if the centre dropped out of the selected models entirely
    if (selCentre) {
      if (BOARD.centres.find(c => c.code === selCentre)) await selectCentre(selCentre);
      else closeInspector();
    }
    if (viewMode === "map") renderOverview();
    if (curDistrict) {
      if (BOARD.centres.some(c => (c.district || "—") === curDistrict)) renderDistrict();
      else closeDistrict();
    }
  }

  const _MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDay(d) { const p = d.split("-"); return `${+p[2]} ${_MON[+p[1] - 1]}`; }
  function kfmt(n) { return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : `${n}`; }

  // the exam's days, as chips inside the Examination card
  function daysMarkup() {
    const days = (BOARD && BOARD.days) || [];
    if (days.length <= 1) return "";
    const sel = new Set(BOARD.daysSelected || days.map(d => d.date));
    return `<div class="t-days">` + days.map(d => {
      const on = sel.has(d.date);
      return `<button class="daychip${on ? " on" : ""}" data-date="${d.date}" title="${d.count.toLocaleString()} alerts on ${fmtDay(d.date)}">` +
             `<span class="tick">✓</span>${fmtDay(d.date)}<span class="dn">${kfmt(d.count)}</span></button>`;
    }).join("") + `</div>`;
  }

  function toggleDay(date) {
    const all = (BOARD.days || []).map(d => d.date);
    let cur = selectedDays ? [...selectedDays] : [...all];
    cur = cur.includes(date) ? cur.filter(d => d !== date) : [...cur, date];
    if (!cur.length) return;                               // never allow zero days
    selectedDays = cur.length === all.length ? null : all.filter(d => cur.includes(d));
    loadBoard();
  }

  function setView(v) {
    viewMode = v;
    const vt = $("#vtog");
    if (vt) vt.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.v === v));
    const list = v === "list";
    $("#act").style.display = list ? "" : "none";
    $("#qhead").style.display = list ? "" : "none";
    $("#qlist").style.display = list ? "" : "none";
    $("#overview").classList.toggle("show", v === "map");
    document.querySelector(".queue").classList.toggle("list-mode", list);
    closeBriefing();
    if (v === "map" && BOARD) renderOverview();
  }

  const RANK = { r: 0, o: 1, y: 2, g: 3 };
  let popTimer = null;
  let lastDL = [];
  let pinned = false;   // a clicked district briefing stays open until closed

  // grouped, worst-first districts for the current filter
  function districtGroups() {
    const groups = {};
    visible().forEach(c => { (groups[c.district || "—"] ||= []).push(c); });
    return Object.entries(groups).map(([d, cs]) => {
      cs.sort((a, b) => RANK[a.tier] - RANK[b.tier] || b.alerts - a.alerts);
      const comp = { r: 0, o: 0, y: 0, g: 0 };
      cs.forEach(c => comp[c.tier]++);
      return { d, cs, comp, crit: comp.r, alerts: cs.reduce((s, c) => s + c.alerts, 0) };
    }).sort((a, b) => b.crit - a.crit || b.alerts - a.alerts);
  }

  async function renderOverview() {
    closeBriefing();
    const dl = districtGroups();
    lastDL = dl;
    $("#overview").innerHTML = `<div class="ovmap"><div style="color:var(--ink-4);font-size:12px">Loading map…</div></div>`;
    // map
    const svg = await (await fetch(`/api/exams/${EXAM}/map?modality=${selected.join(",")}`)).text();
    const mp = $("#overview .ovmap");
    if (mp) {
      const legend = `<div class="mapcard mc-legend"><span>fewer</span><span class="ramp"></span><span>more</span></div>`;
      mp.innerHTML = `${svg}${legend}`;
      // paint the legend from the ramp the renderer actually used
      const svgEl = mp.querySelector("svg"), rampEl = mp.querySelector(".mc-legend .ramp");
      const ramp = svgEl && svgEl.getAttribute("data-ramp");
      if (rampEl && ramp) rampEl.style.background = `linear-gradient(90deg, ${ramp})`;
      mp.querySelectorAll(".dpath").forEach(p => {
        const g = lastDL.find(x => x.d === p.dataset.d);
        p.onclick = ev => { if (g) pinBriefing(p, g, { x: ev.clientX, y: ev.clientY }); };
        p.onmouseenter = ev => { if (g) showPop(p, g, { x: ev.clientX, y: ev.clientY }); };
        p.onmouseleave = () => hidePopSoon();
      });
    }
  }

  const cssesc = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/"/g, '\\"');

  const TLAB = { r: "critical", o: "high", y: "elevated", g: "normal" };
  const cmet = c => (BOARD.isCount || !BOARD.single) ? fmt(c.alerts) : `${c.run || 0}m`;

  // ---------- district dashboard (lean: KPIs + ranked centres) ----------
  let curDistrict = null;
  function distDev(c) {
    const part = d => d === undefined ? null : (!d ? "—" : (d.dev === 0 ? "0" : `${d.dev > 0 ? "+" : "−"}${Math.abs(d.dev)}`));
    const segs = []; const a = part(c.arrDev), o = part(c.opnDev);
    if (a !== null) segs.push(`A ${a}`); if (o !== null) segs.push(`O ${o}`);
    return segs.join(" · ") || "—";
  }
  // SVG donut: segs = [[value, colour]], centre = total, sub = caption
  function donutSvg(segs, total, sub) {
    const cx = 78, cy = 78, r = 58, sw = 22, circ = 2 * Math.PI * r;
    let off = 0;
    const arcs = segs.filter(s => s[0] > 0).map(([v, col]) => {
      const len = circ * v / (total || 1);
      const el = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${col}" stroke-width="${sw}" stroke-dasharray="${len.toFixed(2)} ${(circ - len).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"/>`;
      off += len; return el;
    }).join("");
    return `<svg viewBox="0 0 156 156" class="dvdon">
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#1B1F27" stroke-width="${sw}"/>
      ${arcs}
      <text x="${cx}" y="${cy - 1}" text-anchor="middle" class="dvc">${fmt(total)}</text>
      <text x="${cx}" y="${cy + 18}" text-anchor="middle" class="dvcs">${esc(sub)}</text></svg>`;
  }
  function openDistrict(name) { curDistrict = name; renderDistrict(); $("#district").classList.add("show"); }
  function closeDistrict() { curDistrict = null; $("#district").classList.remove("show"); }
  function renderDistrict() {
    const name = curDistrict;
    const cs = BOARD.centres.filter(c => (c.district || "—") === name);
    if (!cs.length) { closeDistrict(); return; }
    const crit = cs.filter(c => c.tier === "r").length;
    const alerts = cs.reduce((s, c) => s + c.alerts, 0);
    const sev = { r: 0, o: 0, y: 0, g: 0 }; cs.forEach(c => sev[c.tier]++);
    const segbar = ["r", "o", "y", "g"].map(t => sev[t] ? `<i class="seg ${t}" style="width:${(100 * sev[t] / cs.length).toFixed(1)}%"></i>` : "").join("");
    const leg = ["r", "o", "y", "g"].filter(t => sev[t]).map(t => `<span class="lg"><i class="d ${t}"></i>${sev[t]} ${TLAB[t]}</span>`).join("");
    // alerts split by the centre's severity tier -> donut summary (volume view)
    const at = { r: 0, o: 0, y: 0, g: 0 }; cs.forEach(c => { at[c.tier] += c.alerts; });
    const donleg = ["r", "o", "y", "g"].filter(t => at[t]).map(t =>
      `<div class="dl"><span class="dd ${t}"></span><span class="dlv">${fmt(at[t])}</span><span class="dlm">${TLAB[t]}</span></div>`).join("");
    const isTrunk = cs.some(c => c.arrDev !== undefined || c.opnDev !== undefined);
    const metLbl = isTrunk ? "Deviation" : (BOARD.isCount ? "Alerts" : "Longest run");
    const rows = cs.map((c, i) => {
      const met = isTrunk ? distDev(c) : (BOARD.isCount ? fmt(c.alerts) : `${c.run || 0} min`);
      return `<button class="drow" data-code="${esc(c.code)}">
        <span class="rk">${i + 1}</span>
        <span class="cgrp"><span class="sd ${c.tier}"></span><span class="code">${esc(c.code)}</span><span class="dnm">${esc(c.name)}</span></span>
        <span class="met ${isTrunk ? "" : c.tier}">${met}</span>
        <span class="al">${fmt(c.alerts)}</span></button>`;
    }).join("");
    $("#district").innerHTML = `
      <div class="dv-h">
        <button class="dv-back" id="dvback"><svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>Back to map</button>
        <div class="dv-t"><div class="dvn">${esc(name)}</div>
          <div class="dvs">${esc(BOARD.label)} · ${cs.length} centres${crit ? ` · <b>${crit} critical</b>` : ""}</div></div>
      </div>
      <div class="dv-main">
        <div class="dv-body">
        <div class="dv-kpis">
          <div class="kc"><div class="v">${cs.length}</div><div class="l">Centres</div></div>
          <div class="kc"><div class="v ${crit ? "r" : ""}">${crit}</div><div class="l">Critical centres</div></div>
          <div class="kc"><div class="v">${fmt(alerts)}</div><div class="l">Alerts</div></div>
        </div>
        <div class="dv-sev"><div class="segbar">${segbar}</div><div class="seglg">${leg}</div></div>
        <div class="dv-list">
          <div class="dv-lh"><span class="rk">#</span><span>Centre</span><span class="met">${metLbl}</span><span class="al">Alerts</span></div>
          ${rows}
        </div>
        </div>
        <div class="dv-side">
          <div class="dv-maptitle">Alert summary · ${esc(name)}</div>
          <div class="dv-donfill">
            <div class="dv-donwrap">${donutSvg([[at.r, "#D85C63"], [at.o, "#DB8A50"], [at.y, "#D2B65A"], [at.g, "#5BAA7C"]], alerts, "alerts")}</div>
            <div class="dv-donleg">${donleg}</div>
          </div>
        </div>
      </div>`;
    $("#dvback").onclick = closeDistrict;
    $("#district").querySelectorAll(".drow").forEach(b => b.onclick = () => { const code = b.dataset.code; closeDistrict(); selectCentre(code); });
  }
  const sevBar = g => ["r", "o", "y", "g"].map(t => g.comp[t] ? `<i class="dot ${t}" style="width:${(100 * g.comp[t] / g.cs.length).toFixed(1)}%"></i>` : "").join("");
  const sevSum = g => ["r", "o", "y", "g"].filter(t => g.comp[t]).map(t => `${g.comp[t]} ${TLAB[t]}`).join(" · ");

  function placeCard(el, anchor, at, pw) {
    el.style.left = "0px"; el.style.top = "0px";   // measure at origin first
    if (at) {
      let left = at.x + 16, top = at.y + 16;
      if (left + pw > window.innerWidth - 8) left = at.x - pw - 16;
      top = Math.min(top, window.innerHeight - el.offsetHeight - 8);
      el.style.left = Math.max(8, left) + "px"; el.style.top = Math.max(8, top) + "px";
    } else {
      const r = anchor.getBoundingClientRect();
      let left = r.left - pw - 8;
      if (left < 8) left = Math.min(r.right + 8, window.innerWidth - pw - 8);
      el.style.left = left + "px"; el.style.top = Math.max(8, Math.min(r.top, window.innerHeight - el.offsetHeight - 8)) + "px";
    }
  }

  // HOVER -> lightweight centre tiles (transient)
  function showPop(anchor, g, at) {
    if (pinned) return;
    clearTimeout(popTimer);
    const rank = lastDL.indexOf(g) + 1;
    const sqs = g.cs.map(c => `<div class="gsq ${c.tier}${c.code === selCentre ? " sel" : ""}" data-code="${esc(c.code)}" title="${esc(c.code)} · ${esc(c.name)} — ${cmet(c)}"></div>`).join("");
    const pop = $("#dpop");
    pop.innerHTML = `<div class="ph"><span class="rk">${rank}</span><span class="nm">${esc(g.d)}</span><span class="av">${g.cs.length} centres</span></div>`
      + `<div class="pbar">${sevBar(g)}</div><div class="sqs">${sqs}</div>`;
    pop.classList.toggle("crit", !!g.crit);
    pop.classList.remove("show"); void pop.offsetWidth; pop.classList.add("show");
    placeCard(pop, anchor, at, 240);
    pop.querySelectorAll(".gsq").forEach(t => t.onclick = () => selectCentre(t.dataset.code));
    pop.onmouseenter = () => clearTimeout(popTimer);
    pop.onmouseleave = () => hidePopSoon();
  }
  function hidePopSoon() { if (pinned) return; popTimer = setTimeout(() => $("#dpop").classList.remove("show"), 140); }

  // CLICK -> full district briefing that stays pinned until closed
  function pinBriefing(anchor, g, at) {
    pinned = true; clearTimeout(popTimer);
    const rank = lastDL.indexOf(g) + 1;
    // every centre as a tile, coloured by severity, click to open
    const sqs = g.cs.map(c => `<div class="gsq ${c.tier}${c.code === selCentre ? " sel" : ""}" data-code="${esc(c.code)}" title="${esc(c.code)} · ${esc(c.name)} — ${cmet(c)}"></div>`).join("");
    const ma = {};
    g.cs.forEach(c => (c.mods || []).forEach(m => { (ma[m.code] ||= { label: m.label, alerts: 0 }).alerts += m.alerts; }));
    const mods = Object.values(ma).sort((a, b) => b.alerts - a.alerts).slice(0, 6);
    const mmax = mods.length ? mods[0].alerts : 1;
    const modHtml = mods.length > 1 ? `<div class="psec">By AI model</div><div class="pmods">` + mods.map(m =>
      `<div class="pmr"><span class="pml">${esc(m.label)}</span><span class="pmk"><i style="width:${(100 * m.alerts / mmax).toFixed(1)}%"></i></span><span class="pmv">${fmt(m.alerts)}</span></div>`).join("") + `</div>` : "";
    const pop = $("#dpop");
    pop.innerHTML = `<div class="ph"><span class="rk">${rank}</span><span class="nm">${esc(g.d)}</span><span class="av">${fmt(g.alerts)} alerts</span><button class="bx" title="Close">✕</button></div>`
      + `<div class="pbar">${sevBar(g)}</div><div class="psum">${sevSum(g)} · ${g.cs.length} centres</div>`
      + `<div class="psec">Centres</div><div class="sqs">${sqs}</div>${modHtml}`
      + `<button class="popen">Open district dashboard <span>&rarr;</span></button>`;
    pop.classList.toggle("crit", !!g.crit);
    pop.classList.add("pin");
    pop.classList.remove("show"); void pop.offsetWidth; pop.classList.add("show");
    placeCard(pop, anchor, at, 268);
    pop.querySelector(".bx").onclick = closeBriefing;
    pop.querySelector(".popen").onclick = () => { closeBriefing(); openDistrict(g.d); };
    pop.querySelectorAll(".gsq").forEach(t => t.onclick = () => selectCentre(t.dataset.code));
    pop.onmouseenter = pop.onmouseleave = null;
  }
  function closeBriefing() { pinned = false; const p = $("#dpop"); p.classList.remove("show", "pin"); }

  // ---------- append to exam: data + shift windows in one flow ----------
  let shSnapshot = "";
  let shConfiguredDates = [];
  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function updateDateHint(dateStr) {
    const el = $("#shdatehint");
    if (shConfiguredDates.includes(dateStr)) el.textContent = "this day has its own shift windows";
    else if (shConfiguredDates.length) el.textContent = "using the exam default — edit + Apply to give this day its own windows";
    else el.textContent = "applies to this day; defaults to today";
  }
  // The exam's days, as switchable chips. Every day an exam runs can have its
  // own number of shifts and its own windows — the API has always stored them
  // per date and returned configured_dates, but nothing rendered it, so the
  // only route to a second day was knowing to retype the date field. The days
  // are now visible, and adding one is a button rather than folklore.
  function renderDayStrip(current) {
    const box = $("#shdays");
    if (!box) return;
    const days = shConfiguredDates.slice().sort();
    if (current && !days.includes(current)) days.push(current);
    days.sort();
    box.innerHTML = "";
    days.forEach(d => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "shday" + (d === current ? " on" : "") +
                    (shConfiguredDates.includes(d) ? "" : " draft");
      b.textContent = prettyDay(d);
      b.title = shConfiguredDates.includes(d)
        ? d + " — has its own shift windows"
        : d + " — not saved yet";
      b.onclick = () => switchDay(d);
      box.appendChild(b);
    });
    const add = document.createElement("button");
    add.type = "button";
    add.className = "shday add";
    add.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>Add day';
    add.title = "Configure the shifts for another day of this exam";
    add.onclick = addAnotherDay;
    box.appendChild(add);
  }

  function prettyDay(d) {
    const [y, m, dd] = (d || "").split("-");
    const MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return (m && dd) ? `${+dd} ${MON[+m]}` : (d || "—");
  }

  async function switchDay(d) {
    // switching day discards unapplied edits, so say so rather than eat them
    if (collectShifts().json !== shSnapshot &&
        !confirm("This day's shift windows have unsaved changes. Switch anyway and lose them?")) return;
    $("#appenddate").value = d;
    await loadShiftsForDate(d);
  }

  async function addAnotherDay() {
    const days = shConfiguredDates.slice().sort();
    // default to the day after the last configured one — an exam's extra days
    // are almost always consecutive, and the picker stays editable either way
    let next = todayStr();
    if (days.length) {
      const t = new Date(days[days.length - 1] + "T00:00:00");
      t.setDate(t.getDate() + 1);
      next = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
    }
    if (collectShifts().json !== shSnapshot &&
        !confirm("This day's shift windows have unsaved changes. Add a new day anyway and lose them?")) return;
    $("#appenddate").value = next;
    await loadShiftsForDate(next);
    $("#appenddate").focus();
    $("#sherr").textContent = "";
    $("#shdatehint").textContent = "new day — set its windows, then Apply";
  }

  async function loadShiftsForDate(dateStr) {
    $("#shrows").innerHTML = '<div style="color:#6a737d;font-size:11px;padding:10px 2px">Loading…</div>';
    let shifts = [], cfg = [];
    try {
      const j = await (await fetch(`/api/exams/${EXAM}/shifts?date=${encodeURIComponent(dateStr || "")}`)).json();
      if (j.ok) { shifts = j.shifts || []; cfg = j.configured_dates || []; }
    } catch { /* leave empty */ }
    shConfiguredDates = cfg;
    $("#shrows").innerHTML = "";
    if (!shifts.length) addShiftRow({}); else shifts.forEach(addShiftRow);
    renumberShifts();
    updateDateHint(dateStr);
    renderDayStrip(dateStr);
    shSnapshot = collectShifts().json;   // remember loaded state so we only re-save on change
  }
  async function openAppend() {
    $("#sherr").textContent = "";
    $("#appendxl").value = ""; $("#appendev").value = ""; $("#appendevf").value = "";
    $("#shfname").textContent = "No file chosen"; $("#shfname").classList.remove("has");
    $("#shevname").textContent = "No evidence chosen"; $("#shevname").classList.remove("has");
    $("#appenddate").value = todayStr();
    $("#shscrim").classList.add("on"); $("#shmodal").classList.add("on");
    await loadShiftsForDate($("#appenddate").value);
  }
  function closeAppend() { $("#shscrim").classList.remove("on"); $("#shmodal").classList.remove("on"); }

  // ---------- edit examination: name / session / code ----------
  function openEdit() {
    $("#ederr").textContent = "";
    // prefill from the header (source of truth already on the page)
    $("#edname").value = ($(".cmd .ex .nm")?.textContent || "").trim();
    $("#edcode").value = ($(".cmd .ex .cd")?.textContent || EXAM).trim();
    // session isn't shown in the header; fetch current value from the board payload if present
    $("#edsession").value = (BOARD && BOARD.exam && BOARD.exam.session) ? BOARD.exam.session : "";
    $("#edscrim").classList.add("on"); $("#edmodal").classList.add("on");
    $("#edname").focus();
  }
  function closeEdit() { $("#edscrim").classList.remove("on"); $("#edmodal").classList.remove("on"); }

  async function applyEdit() {
    const name = $("#edname").value.trim();
    const session = $("#edsession").value.trim();
    const code = $("#edcode").value.trim();
    if (!name) { $("#ederr").textContent = "Name can't be empty."; return; }
    if (!code) { $("#ederr").textContent = "Code can't be empty."; return; }
    if (!/^[A-Za-z0-9 _-]{1,64}$/.test(code)) {
      $("#ederr").textContent = "Code may use letters, numbers, spaces, hyphens and underscores (max 64)."; return;
    }
    const btn = $("#edsave"); btn.disabled = true; btn.textContent = "Saving…"; $("#ederr").textContent = "";
    try {
      const r = await fetch(`/api/exams/${encodeURIComponent(EXAM)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, session, code }),
      });
      const j = await r.json();
      if (!j.ok) { $("#ederr").textContent = j.error || "Could not save changes."; return; }
      // code may have changed -> the workspace URL is keyed by code, so reload onto the new code
      if (j.code && j.code !== EXAM) { location.href = `/exam/${encodeURIComponent(j.code)}`; return; }
      // name/session only -> update the header in place and close
      const nm = $(".cmd .ex .nm"); if (nm) nm.textContent = j.name;
      if (BOARD && BOARD.exam) BOARD.exam.session = j.session;
      closeEdit();
    } catch (e) {
      $("#ederr").textContent = "Network error — please try again.";
    } finally {
      btn.disabled = false; btn.textContent = "Save changes";
    }
  }

  function onAppendPick(e) {
    const f = e.target.files && e.target.files[0];
    const el = $("#shfname");
    if (f) { el.textContent = f.name; el.classList.add("has"); }
    else { el.textContent = "No file chosen"; el.classList.remove("has"); }
  }
  function onAppendEvPick(e) {
    const n = (e.target.files || []).length, el = $("#shevname");
    if (n) { el.textContent = `${n.toLocaleString()} file${n === 1 ? "" : "s"} selected`; el.classList.add("has"); }
    else { el.textContent = "No evidence chosen"; el.classList.remove("has"); }
  }

  const _mins = t => { const m = /^([01]?\d|2[0-3]):[0-5]\d$/.test(t); return m ? (+t.split(":")[0] * 60 + +t.split(":")[1]) : 1e9; };
  // Shift number is derived, not typed: rank each row by arrival start time so the
  // earliest session shows as Shift 1, live, as the user edits the windows.
  function renumberShifts() {
    const rows = [...$("#shrows").querySelectorAll(".shrow")];
    const ranked = rows.map(r => ({ r, m: _mins(r.querySelector(".sh-a0").value.trim()) }))
      .sort((a, b) => a.m - b.m);
    ranked.forEach((o, i) => { const n = o.r.querySelector(".shnum"); if (n) n.textContent = `Shift ${i + 1}`; });
  }

  // read the shift rows -> {shifts, json, bad} ; bad = 1-based index of first invalid row.
  // Rows are ordered by arrival time; names are assigned server-side (earliest = Shift 1).
  function collectShifts() {
    const HHMM = /^([01]?\d|2[0-3]):[0-5]\d$/;
    const rows = [...$("#shrows").querySelectorAll(".shrow")];
    const shifts = []; let bad = 0;
    rows.forEach((r, i) => {
      const g = s => r.querySelector(s).value.trim();
      const arr = [g(".sh-a0"), g(".sh-a1")], opn = [g(".sh-o0"), g(".sh-o1")];
      if (!bad && ![...arr, ...opn].every(t => HHMM.test(t))) bad = i + 1;
      shifts.push({ arrival: arr, opening: opn });
    });
    shifts.sort((a, b) => _mins(a.arrival[0]) - _mins(b.arrival[0]));
    return { shifts, json: JSON.stringify(shifts), bad };
  }

  async function applyAppend() {
    const { shifts, json, bad } = collectShifts();
    if (bad) { $("#sherr").textContent = `Shift ${bad}: every time must be HH:MM (24-hour).`; return; }
    if (!shifts.length) { $("#sherr").textContent = "Keep at least one shift."; return; }
    const file = $("#appendxl").files[0];
    const evfiles = $("#appendevf").files;
    const evpath = $("#appendev").value.trim();
    const shiftsChanged = json !== shSnapshot;
    if (evfiles.length && !file) { $("#sherr").textContent = "Evidence needs its alert file too — choose the alert export."; return; }
    if (!file && !shiftsChanged) { $("#sherr").textContent = "Choose an alert file or change a shift window first."; return; }

    const date = $("#appenddate").value || null;
    $("#sherr").textContent = ""; const btn = $("#shsave"); btn.disabled = true; btn.textContent = "Applying…";
    const parts = [];
    try {
      if (shiftsChanged) {
        const r = await fetch(`/api/exams/${EXAM}/shifts`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ shifts, date }),
        });
        const j = await r.json();
        if (!j.ok) { $("#sherr").textContent = j.error || "Could not save shifts."; return; }
        parts.push(`${shifts.length} shift${shifts.length === 1 ? "" : "s"} saved for ${date || "the exam"}`);
      }
      if (file) {
        const fd = new FormData(); fd.append("excel", file);
        for (const f of evfiles) fd.append("evidence", f);
        if (evpath) fd.append("evidence_path", evpath);
        const r = await fetch(`/api/exams/${EXAM}/append`, { method: "POST", body: fd });
        const j = await r.json();
        if (!j.ok) { $("#sherr").textContent = j.error || "Could not merge that file."; return; }
        const dup = j.duplicates ? ` · ${j.duplicates.toLocaleString()} already present` : "";
        const nmc = (j.newModalities || []).length;
        const nm = nmc ? ` · ${nmc} new alarm type${nmc === 1 ? "" : "s"} adopted` : "";
        const ev = j.evidence ? ` · ${j.evidence.toLocaleString()} evidence linked` : "";
        parts.push(`merged ${file.name} — ${(j.added || 0).toLocaleString()} new alert${j.added === 1 ? "" : "s"}${dup}${nm}${ev} (total ${(j.total || 0).toLocaleString()})`);
      }
      closeAppend();
      toast(parts.join(" · ") + ".");
      await loadBoard();
    } catch (e) { $("#sherr").textContent = "Apply error: " + e; }
    finally { btn.disabled = false; btn.textContent = "Apply"; }
  }

  function addShiftRow(sh) {
    sh = sh || {};
    const a = (sh.arrival || ["", ""]), o = (sh.opening || ["", ""]);
    const row = document.createElement("div");
    row.className = "shrow";
    row.innerHTML =
      `<span class="shnum">Shift</span>` +
      `<div class="wpair"><input type="text" class="sh-a0" placeholder="06:45" value="${esc(a[0] || "")}"><span>–</span><input type="text" class="sh-a1" placeholder="07:45" value="${esc(a[1] || "")}"></div>` +
      `<div class="wpair"><input type="text" class="sh-o0" placeholder="08:05" value="${esc(o[0] || "")}"><span>–</span><input type="text" class="sh-o1" placeholder="08:40" value="${esc(o[1] || "")}"></div>` +
      `<button class="shdel" title="Remove shift">&times;</button>`;
    row.querySelector(".sh-a0").addEventListener("input", renumberShifts);
    row.querySelector(".shdel").onclick = () => { row.remove(); renumberShifts(); };
    $("#shrows").appendChild(row);
  }

  function toast(msg) {
    let t = $("#toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 5200);
  }

  // ---------- evidence curation (one-by-one review) ----------
  let curCands = [], curIdx = 0, curPicked = [], curOpen = false;
  function reportURL(photos) {
    const ph = (photos && photos.length) ? `&photos=${photos.join(",")}` : "";
    const dp = selectedDays ? `&days=${selectedDays.join(",")}` : "";
    return `/exam/${EXAM}/report/${selected.join(",")}?v=1${ph}${dp}`;
  }
  async function openReport() {
    const trunk = selected.every(c => c === "TP" || c === "TO");
    // combined event report has no evidence page -> nothing to curate
    if (selected.length > 1 && !trunk) { window.open(reportURL(), "_blank"); return; }
    let j;
    try { j = await (await fetch(`/api/exams/${EXAM}/evidence-candidates?modality=${selected.join(",")}`)).json(); }
    catch { window.open(reportURL(), "_blank"); return; }
    curCands = j.candidates || [];
    if (!curCands.length) { window.open(reportURL(), "_blank"); return; }   // no frames to pick
    curIdx = 0; curPicked = []; curOpen = true;
    $("#curlbl").textContent = " · " + (j.label || "");
    $("#curscrim").classList.add("on"); $("#cur").classList.add("on");
    renderCur();
  }
  function renderCur() {
    $("#curcount").textContent = curPicked.length; $("#curgenn").textContent = curPicked.length;
    if (curIdx >= curCands.length) {        // reviewed everything
      $("#curprog").textContent = `${curCands.length} / ${curCands.length}`;
      $("#curstage").innerHTML = `<div class="cur-done"><div class="cd-n">${curPicked.length}</div>frames selected for the report<div class="cd-s">Review complete — generate when ready</div></div>`;
      $("#curcap").innerHTML = "";
      $("#curno").disabled = $("#curyes").disabled = true;
      $("#curgen").classList.add("ready");
      return;
    }
    const c = curCands[curIdx];
    $("#curno").disabled = $("#curyes").disabled = false;
    $("#curgen").classList.remove("ready");
    $("#curprog").textContent = `${curIdx + 1} / ${curCands.length}`;
    $("#curstage").innerHTML = `<img src="/api/evidence/${EXAM}/${encodeURIComponent(c.alarm)}" alt="evidence">`;
    $("#curcap").innerHTML = `<div class="cc-n">${esc(c.centre)}</div><div class="cc-s"><span class="cc-cd">${esc(c.code)}</span> ${esc(c.district)} · ${esc(c.modality)} — ${esc(c.sub)}</div>`;
  }
  function decide(yes) {
    if (curIdx >= curCands.length) return;
    if (yes) curPicked.push(curCands[curIdx].alarm);
    curIdx++; renderCur();
  }
  function generateCur(photos) {     // photos=null -> auto-select; [] or list -> curated
    closeCur();
    window.open(reportURL(photos === null ? null : photos), "_blank");
  }
  function closeCur() { curOpen = false; $("#cur").classList.remove("on"); $("#curscrim").classList.remove("on"); }

  function showSilent(r) {
    const list = r.silent || [];
    let m = document.getElementById("silentModal");
    if (!m) { m = document.createElement("div"); m.id = "silentModal"; m.className = "silentmodal"; document.body.appendChild(m); }
    const body = list.length
      ? `<div class="sm-sub">In the official roster but produced no alert in this exam — a coverage gap to verify.</div>
         <div class="sm-list">${list.map((s, i) => `<div class="sm-row"><span class="sm-i">${i + 1}</span><span class="sm-c">${esc(s.code)}</span><span class="sm-n">${esc(s.name || "")}</span><span class="sm-d">${esc(s.district || "")}</span></div>`).join("")}</div>`
      : `<div class="sm-sub" style="padding:18px 18px 24px"><b style="color:#F0B86C">${r.silentN}</b> of ${r.total} centres in the total produced no alert at all. To identify which centres, upload the official centre list in the New Examination wizard's Centres step.</div>`;
    m.innerHTML = `<div class="sm-card"><div class="sm-h"><span>Silent centres · ${r.silentN}</span><button id="smx"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>${body}</div>`;
    m.classList.add("show");
    m.onclick = e => { if (e.target === m || e.target.closest("#smx")) m.classList.remove("show"); };
  }

  // ---------- the deck: five badge cards floating over the map ----------
  // Template is the role-badge from the design system, lanyard removed: slot,
  // colour band with name + code, monogram disc, body, footer rule.
  let rotIdx = 0, rotTimer = null;

  // top districts for the current selection, each with the modality it leads on
  function districtTop(n) {
    return districtGroups().slice(0, n).map(g => {
      const ma = {};
      g.cs.forEach(c => (c.mods || []).forEach(m => { (ma[m.code] ||= { label: m.label, alerts: 0 }).alerts += m.alerts; }));
      const top = Object.values(ma).sort((a, b) => b.alerts - a.alerts)[0];
      return { d: g.d, alerts: g.alerts, centres: g.cs.length, crit: g.crit, mod: top ? top.label : (BOARD.label || "—") };
    });
  }

  const totAlerts = () => BOARD.kpis.total;
  function critFoot() {
    const crit = BOARD.centres.filter(c => c.tier === "r").length;
    const r = BOARD.roster;
    const left = `<span class="t-f1${crit ? " cr" : ""}">${fmt(crit)} critical</span>`;
    const right = (r && r.silentN)
      ? `<button class="t-f2 lnk" id="silentStat" title="Roster centres with no alert">${fmt(r.silentN)} silent</button>`
      : `<span class="t-f2">${r ? `${fmt(r.reported)}/${fmt(r.total)} reported` : "all reporting"}</span>`;
    return left + right;
  }

  // Each control is an icon tile: glyph in the accent, name, live value, then
  // whatever the tile actually does. Same palette and radius as the badges were.
  const ICON = {
    mod: '<path d="M12 3 3 8l9 5 9-5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    view: '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/>',
    exam: '<path d="M4 20h4L18 10l-4-4L4 16z"/><path d="M13 5l4 4"/>',
    report: '<path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6"/><path d="M9 13h7M9 17h5"/>',
    total: '<path d="M3 20h18"/><path d="M6 20v-6M11 20V8M16 20v-9"/>',
    dist: '<path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.6"/>',
  };
  const tile = (o) => `<article class="tile${o.cls || ""}" style="--bc:${o.hue}" data-card="${o.key}">
      <div class="t-head">
        <span class="t-icon"><svg viewBox="0 0 24 24">${ICON[o.key]}</svg></span>
        <span class="t-id"><h3 class="t-name">${o.name}</h3><span class="t-code">${o.code}</span></span>
        <span class="t-val">${o.val || ""}</span>
      </div>
      <div class="t-body">${o.body}</div>
      <div class="t-foot">${o.foot}</div>
    </article>`;

  function renderLens() {
    const allOn = selected.length === BOARD.modalities.length;
    const mods = BOARD.modalities.map(m => {
      const on = selected.includes(m.code);
      return `<button class="mrow${on ? " on" : ""}" data-mod="${m.code}" title="${esc(m.label)}">
        <span class="box"><svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-11"/></svg></span>
        <span class="nm">${esc(m.label)}</span><span class="ct">${fmt(m.count)}</span></button>`;
    }).join("");

    const tops = districtTop(10);
    if (rotIdx >= tops.length) rotIdx = 0;
    const t = tops[rotIdx];
    const dots = tops.map((_, i) => `<i class="rdot${i === rotIdx ? " on" : ""}"></i>`).join("");

    $("#deck").innerHTML =
      tile({ key: "mod", hue: "#3B5BB5", name: "Modalities", code: "LENS", val: `${selected.length}/${BOARD.modalities.length}`,
              body: `<div class="t-scroll">${mods}</div>`,
              foot: `<span class="t-f1">${selected.length} of ${BOARD.modalities.length}</span><button class="t-act" id="lall">${allOn ? "Clear" : "All"}</button>` })
    + tile({ key: "view", hue: "#35696C", name: "View", code: "DISPLAY", val: viewMode === "map" ? "Map" : "List",
              body: `<div class="t-seg" id="vtog"><button data-v="list" class="${viewMode === "list" ? "on" : ""}">List</button><button data-v="map" class="${viewMode === "map" ? "on" : ""}">Map</button></div>`,
              foot: `<span class="t-f1">${fmt(visible().length)} centres</span><span class="t-f2">${viewMode === "map" ? "Choropleth" : "Queue"}</span>` })
    + tile({ key: "exam", hue: "#684E86", name: "Examination", code: esc(EXAM), val: `${(BOARD.days || []).length || 1}d`,
              body: `<div class="t-stack">
                  <button class="t-btn" id="editbtn"><svg viewBox="0 0 24 24"><path d="M4 20h4L18 10l-4-4L4 16z"/><path d="M13 5l4 4"/></svg>Edit details</button>
                  <button class="t-btn" id="appendbtn"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg><span id="addlbl">Append day</span></button></div>${daysMarkup()}`,
              foot: `<span class="t-f1">${(BOARD.days || []).length || 1} day${((BOARD.days || []).length || 1) > 1 ? "s" : ""}</span><span class="t-f2">${fmt(BOARD.kpis.total)} alerts</span>` })
    + tile({ key: "report", hue: "#A55242", cls: " is-action", name: "Report", code: "GENERATE",
              body: `<p class="t-desc">A print-ready compliance dossier for the current lens — evidence, rankings and per-centre findings.</p>`,
              foot: `<button class="t-cta" id="genreport"><span id="genlbl">Generate</span><span>&rarr;</span></button>` })
    + tile({ key: "total", hue: "#3E6F51", name: "Totals", code: "THIS LENS", val: fmt(BOARD.kpis.total),
              body: `<div class="t-tot">
                  <div class="tot-r"><span class="tot-v">${fmt(totAlerts())}</span><span class="tot-k">Alerts</span></div>
                  <div class="tot-r"><span class="tot-v">${fmt(BOARD.kpis.centres)}</span><span class="tot-k">Centres</span></div>
                  <div class="tot-r"><span class="tot-v">${fmt(BOARD.kpis.districts)}</span><span class="tot-k">Districts</span></div>
                </div>`,
              foot: critFoot() })
    + tile({ key: "dist", hue: "#8A6323", name: "Districts", code: "TOP 10", val: `${Math.min(10, districtGroups().length)}`,
              body: t ? `<div class="t-rot" data-d="${esc(t.d)}">
                  <div class="rot-n">${esc(t.d)}</div>
                  <div class="rot-k">tops in</div>
                  <div class="rot-m">${esc(t.mod)}</div>
                  <div class="rot-dots">${dots}</div></div>`
                : `<p class="t-desc">No districts in this selection.</p>`,
              foot: t ? `<span class="t-f1">${fmt(t.alerts)} alerts</span><span class="t-f2">${t.centres} centres</span>` : "" });

    $("#deck").querySelectorAll("[data-mod]").forEach(b => b.onclick = () => toggleMod(b.dataset.mod));
    $("#deck").querySelectorAll(".daychip").forEach(b => b.onclick = () => toggleDay(b.dataset.date));
    $("#lall").onclick = () => { selected = allOn ? [BOARD.modalities[0].code] : BOARD.modalities.map(m => m.code); loadBoard(); };
    $("#vtog").querySelectorAll("button").forEach(b => b.onclick = () => setView(b.dataset.v));
    $("#editbtn").onclick = openEdit;
    $("#appendbtn").onclick = openAppend;
    $("#genreport").onclick = openReport;
    const sc = $("#deck #silentStat");
    if (sc && BOARD.roster) sc.onclick = () => showSilent(BOARD.roster);
    const rot = $("#deck .t-rot");
    if (rot) rot.onclick = () => openDistrict(rot.dataset.d);

    clearInterval(rotTimer);
    if (tops.length > 1) rotTimer = setInterval(() => { rotIdx = (rotIdx + 1) % tops.length; paintRot(); }, 3600);
  }

  // repaint only the rotating face, so the other four cards never flicker
  function paintRot() {
    const tops = districtTop(10), t = tops[rotIdx];
    const card = $('#deck [data-card="dist"]');
    if (!card || !t) return;
    const body = card.querySelector(".t-rot"), foot = card.querySelector(".t-foot");
    if (!body) return;
    body.dataset.d = t.d;
    body.classList.remove("in"); void body.offsetWidth; body.classList.add("in");
    body.querySelector(".rot-n").textContent = t.d;
    body.querySelector(".rot-m").textContent = t.mod;
    body.querySelector(".rot-dots").innerHTML = tops.map((_, i) => `<i class="rdot${i === rotIdx ? " on" : ""}"></i>`).join("");
    foot.innerHTML = `<span class="t-f1">${fmt(t.alerts)} alerts</span><span class="t-f2">${t.centres} centres</span>`;
  }

  function toggleMod(code) {
    if (selected.includes(code)) { if (selected.length > 1) selected = selected.filter(c => c !== code); }
    else selected = [...selected, code];
    loadBoard();
  }
  function setDistrict(d) { filter.district = filter.district === d ? null : d; renderQueue(); renderLens(); }

  // ---------- queue (spine) ----------
  function visible() {
    return BOARD.centres.filter(c =>
      (!filter.district || c.district === filter.district) &&
      (!filter.tier || c.tier === filter.tier));
  }
  function renderQueue() {
    const single = BOARD.single, isCount = BOARD.isCount;
    $("#qmetlbl").textContent = (!single || isCount) ? "Alerts" : "Sustained";
    $("#genlbl").textContent = selected.length > 1 ? "Combined Report" : "Report";
    // activity strip
    const tl = BOARD.timeline;
    $("#act").innerHTML = tl.series.map(v => `<div class="b${v === tl.max ? " pk" : ""}" style="height:${(100 * v / tl.max).toFixed(1)}%"></div>`).join("");
    // pills
    const pills = [];
    if (filter.tier) pills.push(`<span class="pill">${TIERNAME[filter.tier]}<i data-x="tier">×</i></span>`);
    if (filter.district) pills.push(`<span class="pill">${esc(filter.district)}<i data-x="district">×</i></span>`);
    // rows
    const rows = visible();
    $("#qlist").innerHTML = rows.slice(0, 500).map((c, i) => {
      const met = (!single || isCount) ? fmt(c.alerts) : `${c.run || 0} min`;
      const tail = single ? `<span class="chev">›</span>` : `<span class="modn">${c.mods.length}×</span>`;
      return `<div class="qrow${c.code === selCentre ? " sel" : ""}" data-code="${esc(c.code)}">
        <span class="sd dot ${c.tier}"></span>
        <span class="c1"><span class="code">${esc(c.code)}</span><span class="nm">${esc(c.name)}</span></span>
        <span class="dist">${esc(c.district)}</span>
        <span class="met ${c.tier}">${met}</span>
        ${tail}</div>`;
    }).join("");
    $("#qlist").querySelectorAll(".qrow").forEach(r => r.onclick = () => selectCentre(r.dataset.code));
    renderStatus();
  }

  function renderStatus() {
    const rows = visible();
    const shown = rows.reduce((s, c) => s + c.alerts, 0);
    const f = [filter.tier ? TIERNAME[filter.tier] : null, filter.district].filter(Boolean).join(" · ") || "none";
    $("#status").innerHTML = `<span><b>${selected.length}</b> lens${selected.length > 1 ? "es" : ""}</span>
      <span>filter: <b>${esc(f)}</b></span><span><b>${fmt(rows.length)}</b> centres · <b>${fmt(shown)}</b> alerts</span>
      <span class="sp">⌘K search · ↑↓ navigate · Esc close</span>`;
  }

  // ---------- inspector (workflow) ----------
  async function selectCentre(code) {
    selCentre = code;
    $("#wsbody").classList.add("inspect");
    document.querySelectorAll(".qrow").forEach(r => r.classList.toggle("sel", r.dataset.code === code));
    document.querySelectorAll(".gsq").forEach(t => t.classList.toggle("sel", t.dataset.code === code));
    const r = await fetch(`/api/exams/${EXAM}/alerts?modality=${selected.join(",")}&centre=${encodeURIComponent(code)}&limit=600&sort=ts&dir=-1`);
    centreAlerts = (await r.json()).alerts;
    renderInspector();
  }
  function closeInspector() { selCentre = null; $("#wsbody").classList.remove("inspect"); document.querySelectorAll(".qrow.sel").forEach(r => r.classList.remove("sel")); }

  function centreTimeChart(alerts) {
    const mins = alerts.map(a => { const t = (a.ts || "").slice(-8).split(":"); return (+t[0]) * 60 + (+t[1]); }).filter(x => !isNaN(x));
    if (!mins.length) return `<div class="ctempty">No timed alerts.</div>`;
    const step = 5;
    let lo = Math.floor(Math.min(...mins) / step) * step, hi = Math.ceil(Math.max(...mins) / step) * step;
    if (hi === lo) hi = lo + step;
    const nb = (hi - lo) / step + 1, bins = new Array(nb).fill(0);
    mins.forEach(x => { bins[Math.min(nb - 1, Math.floor((x - lo) / step))]++; });
    const W = 340, H = 70, pad = 5, vmax = Math.max(...bins, 1);
    const X = i => pad + (nb > 1 ? i / (nb - 1) : 0.5) * (W - 2 * pad);
    const Y = v => (H - 14) - v / vmax * (H - 14 - pad);
    const pts = bins.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
    let ticks = "";
    for (let t = Math.ceil(lo / 30) * 30; t <= hi; t += 30) {
      const x = pad + (t - lo) / (hi - lo) * (W - 2 * pad);
      ticks += `<text x="${x.toFixed(1)}" y="${H - 3}" text-anchor="middle" font-size="7.5" fill="#646B78">${String((t / 60) | 0).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}</text>`;
    }
    const bw = (W - 2 * pad) / nb;
    const bars = bins.map((v, i) => {
      if (v <= 0) return "";
      const y = Y(v);
      return `<rect x="${(pad + i * bw + 0.7).toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(bw - 1.4, 0.8).toFixed(1)}" height="${((H - 14) - y).toFixed(1)}" fill="#4f9be0"/>`;
    }).join("");
    return `<svg class="ctchart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="display:block;width:100%;height:64px;margin:3px 0 11px">
      ${bars}
      <line x1="${pad}" y1="${H - 14}" x2="${W - pad}" y2="${H - 14}" stroke="#262B34" stroke-width="0.5"/>${ticks}</svg>`;
  }

  // trunk deviation KPI cell: signed minutes off the authorised window
  function devCell(label, d) {
    if (d === undefined) return "";
    if (!d) return `<div class="s"><div class="v">—</div><div class="k">${label} · none</div></div>`;
    const cls = d.cls === "in" ? "g" : (d.cls === "late" ? "r" : "o");
    const txt = d.dev === 0 ? "On time" : `${d.dev > 0 ? "+" : "−"}${Math.abs(d.dev)} min`;
    const sub = d.cls === "in" ? "in window" : (d.cls === "late" ? "late" : "early");
    return `<div class="s" title="Window ${esc(d.window)} · actual ${esc(d.actual)}"><div class="v ${cls}">${txt}</div><div class="k">${label} · ${sub}</div></div>`;
  }
  // the severity-driver KPI differs by modality: sustained -> longest run (min);
  // count -> alert count; sustained_count (zone entry) -> number of entries.
  function severityCell(c) {
    const code = BOARD.single ? (selected[0] || "") : "";
    if (BOARD.mode === "count") {
      const lbl = { MD: "Phone alerts", CT: "Tampering alerts" }[code] || "Alerts";
      return `<div class="s"><div class="v ${c.tier}">${fmt(c.alerts)}</div><div class="k">${lbl}</div></div>`;
    }
    if (BOARD.mode === "sustained_count") {
      const lbl = code === "ZI" ? "Zone entries" : "Detections";
      return `<div class="s"><div class="v ${c.tier}">${fmt(c.detections)}</div><div class="k">${lbl}</div></div>`;
    }
    return `<div class="s"><div class="v ${c.tier}">${c.run || 0} min</div><div class="k">Longest run</div></div>`;
  }
  // each modality's own metric, in its own terms (for the multi-modality breakdown)
  function modMetric(m) {
    const a = `${fmt(m.alerts)} alert${m.alerts === 1 ? "" : "s"}`;
    if (m.mode === "sustained") return `${a} · ${m.run || 0} min`;
    if (m.mode === "sustained_count") return `${fmt(m.detections)} entr${m.detections === 1 ? "y" : "ies"}`;
    if (m.mode === "compliance") return `${fmt(m.alerts)} sighting${m.alerts === 1 ? "" : "s"}`;
    return a;  // count
  }
  function statCells(c) {
    const alerts = `<div class="s"><div class="v">${fmt(c.alerts)}</div><div class="k">Alerts</div></div>`;
    const detections = `<div class="s"><div class="v">${fmt(c.detections)}</div><div class="k">Detections</div></div>`;
    // multiple modalities: their metrics aren't comparable, so don't blend them —
    // show neutral totals up top and break each out separately below
    if (!BOARD.single) {
      const nmods = (c.mods || []).length;
      return alerts + detections +
        `<div class="s"><div class="v">${nmods}<span style="font-size:13px;color:var(--ink-4);font-weight:400;margin-left:1px">/ ${selected.length}</span></div><div class="k">Modalities here</div></div>`;
    }
    const trunk = (c.arrDev !== undefined || c.opnDev !== undefined);
    if (!trunk) return alerts + detections + severityCell(c);
    // single trunk: arrival + opening deviations
    const both = (c.arrDev !== undefined && c.opnDev !== undefined);
    return alerts
      + (both ? "" : `<div class="s"><div class="v">${fmt(c.detections)}</div><div class="k">Sightings</div></div>`)
      + devCell("Arrival", c.arrDev) + devCell("Opening", c.opnDev);
  }

  function renderInspector() {
    const c = BOARD.centres.find(x => x.code === selCentre); if (!c) return;
    const w = getWork(c.code);
    // every SELECTED modality, in order — 'nil' where this centre had no alert for it
    const modByCode = {}; c.mods.forEach(m => { modByCode[m.code] = m; });
    const labelOf = code => ((BOARD.modalities || []).find(x => x.code === code) || {}).label || code;
    const breakdown = (!BOARD.single ? selected : []).map(code => {
      const m = modByCode[code];
      return m
        ? `<div class="modbk"><span class="dot ${m.tier}"></span><span class="ml">${esc(m.label || m.code)}</span><span class="ct">${modMetric(m)}</span></div>`
        : `<div class="modbk"><span class="dot" style="background:#3a4250"></span><span class="ml" style="color:var(--ink-4)">${esc(labelOf(code))}</span><span class="ct" style="color:var(--ink-4)">nil</span></div>`;
    }).join("");
    const alerts = centreAlerts.map((a, i) =>
      `<button class="ialert${a.hasImage ? " has" : ""}" data-i="${i}"><span class="node ${c.tier}"></span><span class="tm">${esc((a.ts || "").slice(-8))}</span>
        <span class="zn">${esc(a.zone || a.camera)}</span>
        <span class="ev ${a.hasImage ? "" : "no"}">${a.hasImage ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/></svg>view' : "—"}</span></button>`).join("");
    $("#inspector").innerHTML = `
      <div class="insp-h">
        <div><div class="code">${esc(c.code)}</div><div class="nm">${esc(c.name)}</div>
          <div class="sub">${esc(c.district)} · ${c.tier === "r" ? "Critical" : TIERNAME[c.tier]} priority</div></div>
        <div style="display:flex;gap:6px;align-items:center">
          <a class="ireport" href="/exam/${EXAM}/report/centre/${encodeURIComponent(c.code)}?m=${selected.join(",")}" target="_blank" title="Generate centre report"><svg viewBox="0 0 24 24"><path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6"/></svg></a>
          <button class="x" id="ix"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
        </div>
      </div>
      <div class="insp-stat">${statCells(c)}</div>
      ${breakdown ? `<div class="isec"><div class="ih">By modality<span>${selected.length}</span></div>${breakdown}</div>` : ""}
      <div class="isec"><div class="ih">Alerts<span>${centreAlerts.length}</span></div><div class="ialerts">${alerts}</div></div>
      <div class="iwork">
        <div class="lab">Alerts over time</div>
        ${centreTimeChart(centreAlerts)}
        <div class="lab">Investigation</div>
        <div class="statusrow">
          ${["Open", "Reviewing", "Closed"].map(s => `<button data-st="${s}" class="${w.status === s ? "on" : ""}">${s}</button>`).join("")}
        </div>
      </div>`;
    $("#ix").onclick = closeInspector;
    $("#inspector").querySelectorAll(".ialert").forEach(b => b.onclick = () => openLightbox(+b.dataset.i));
    $("#inspector").querySelectorAll("[data-st]").forEach(b => b.onclick = () => { const ww = getWork(c.code); ww.status = b.dataset.st; setWork(c.code, ww); renderInspector(); });
  }

  // ---------- evidence lightbox ----------
  function openLightbox(i) {
    if (i < 0 || i >= centreAlerts.length) return;
    lbIndex = i; const a = centreAlerts[i];
    const src = `/api/evidence/${EXAM}/${encodeURIComponent(a.id)}`;
    $("#lbstage").innerHTML = a.hasImage ? `<img src="${src}" alt="evidence">` : `<div class="noimg">No evidence frame on file for this alert</div>`;
    $("#lbt").textContent = `${a.centre}`;
    $("#lbmeta").innerHTML = [
      ["Centre", `${a.centreCode} · ${a.centre}`], ["District", a.district], ["Camera", a.camera],
      ["Zone", a.zone], ["Timestamp", a.ts], ["Alarm ID", a.id], ["Evidence ID", a.evid],
    ].map(([l, v]) => `<div class="mrow"><span class="ml">${esc(l)}</span><span class="mv">${esc(String(v || "—"))}</span></div>`).join("");
    $("#lbOpen").href = src; $("#lbDl").href = src; $("#lbDl").download = (a.evid || "evidence") + ".jpg";
    $("#lbPrev").disabled = i <= 0; $("#lbNext").disabled = i >= centreAlerts.length - 1;
    $("#lb").classList.add("on"); $("#lbscrim").classList.add("on");
  }
  function closeLightbox() { $("#lb").classList.remove("on"); $("#lbscrim").classList.remove("on"); lbIndex = -1; }

  // ---------- command palette ----------
  function openPal() { $("#pal").classList.add("on"); $("#palscrim").classList.add("on"); const ip = $("#palinput"); ip.value = ""; palSearch(); ip.focus(); }
  function closePal() { $("#pal").classList.remove("on"); $("#palscrim").classList.remove("on"); }
  function palSearch() {
    const q = $("#palinput").value.toLowerCase().trim(); palCur = 0;
    let items = [];
    const cen = BOARD.centres.filter(c => !q || (c.code + " " + c.name + " " + c.district).toLowerCase().includes(q)).slice(0, 10)
      .map(c => ({ tag: "centre", lab: `${c.code} · ${c.name}`, sub: c.district, act: () => { closePal(); selectCentre(c.code); } }));
    const dis = BOARD.districts.filter(([n]) => !q || n.toLowerCase().includes(q)).slice(0, 4)
      .map(([n, v]) => ({ tag: "district", lab: n, sub: `${fmt(v)} alerts`, act: () => { closePal(); setDistrict(n); } }));
    items = q ? [...cen, ...dis] : [...dis, ...cen];
    palItems = items;
    $("#palres").innerHTML = items.map((it, i) =>
      `<div class="r${i === palCur ? " cur" : ""}" data-i="${i}"><span class="tag">${it.tag}</span><span class="lab">${esc(it.lab)}</span><span class="sub">${esc(it.sub)}</span></div>`).join("");
    $("#palres").querySelectorAll(".r").forEach(r => r.onclick = () => palItems[+r.dataset.i].act());
  }

  // ---------- keyboard ----------
  function onKey(e) {
    if (curOpen) {
      if (e.key === "Escape") closeCur();
      else if (e.key === "ArrowRight" || e.key.toLowerCase() === "y") { e.preventDefault(); decide(true); }
      else if (e.key === "ArrowLeft" || e.key.toLowerCase() === "n") { e.preventDefault(); decide(false); }
      else if (e.key === "Enter") { e.preventDefault(); generateCur(curPicked); }
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#pal").classList.contains("on") ? closePal() : openPal(); return; }
    if ($("#pal").classList.contains("on")) {
      if (e.key === "Escape") closePal();
      else if (e.key === "ArrowDown") { e.preventDefault(); palCur = Math.min(palCur + 1, palItems.length - 1); hlPal(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); palCur = Math.max(palCur - 1, 0); hlPal(); }
      else if (e.key === "Enter" && palItems[palCur]) palItems[palCur].act();
      return;
    }
    if ($("#lb").classList.contains("on")) {
      if (e.key === "Escape") closeLightbox();
      else if (e.key === "ArrowLeft") openLightbox(lbIndex - 1);
      else if (e.key === "ArrowRight") openLightbox(lbIndex + 1);
      return;
    }
    if (e.key === "Escape" && pinned) { closeBriefing(); return; }
    if (e.key === "Escape" && selCentre) closeInspector();
  }
  function hlPal() { $("#palres").querySelectorAll(".r").forEach((r, i) => r.classList.toggle("cur", i === palCur)); }


  return { init };
})();
