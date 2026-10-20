// BeachWell web app: plain JavaScript modules, no build step.
// Talks to the backend API on the same origin (or window.BEACHWELL_API if set).

const API = window.BEACHWELL_API || "";
const view = document.getElementById("view");
const tabs = document.getElementById("tabs");
const who = document.getElementById("who");
const toastEl = document.getElementById("toast");
const crisisDialog = document.getElementById("crisis");

const state = { user: null, health: null, forecast: null, selected: 0, whatIf: { extra: {}, usePlan: false } };

// ------------------------------------------------------------------ helpers

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { return null; }
  return null;
}

function toast(msg) {
  toastEl.textContent = msg;
  toastEl.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (toastEl.hidden = true), 2600);
}

const fmtHour = (h) => {
  const hh = Math.floor(h), mm = Math.round((h - hh) * 60);
  const ampm = hh < 12 ? "am" : "pm", h12 = hh % 12 || 12;
  return mm ? `${h12}:${String(mm).padStart(2, "0")} ${ampm}` : `${h12} ${ampm}`;
};
// Campus time, whatever the viewer's device is set to.
const TZ = "America/Los_Angeles";
const fmtDay = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
const fmtDue = (iso) => new Date(iso).toLocaleString("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

const LEVELS = ["Light", "Moderate", "Heavy", "Overload"];
const LEVEL_COLOR = { Light: "var(--light)", Moderate: "var(--moderate)", Heavy: "var(--heavy)", Overload: "var(--overload)" };
const HEAVY = ["Heavy", "Overload"];

// A small colored pill naming the workload level.
const badge = (level) => `<span class="badge" data-level="${level}">${level}</span>`;

// ------------------------------------------------------------------ routing

const ROUTES = { forecast: renderForecast, plan: renderPlan, recharge: renderRecharge, checkin: renderCheckin, pace: renderPace, radar: renderRadar };

async function route() {
  const tab = (location.hash || "#forecast").slice(1);
  if (!state.user && tab !== "radar") return renderWelcome();
  tabs.hidden = !state.user;
  [...tabs.querySelectorAll("a")].forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  view.innerHTML = `<p class="loading">Loading…</p>`;
  try {
    await (ROUTES[tab] || renderForecast)();
  } catch (err) {
    view.innerHTML = `<div class="panel"><p class="error">${esc(err.message)}</p><p>Check that the backend is running, then reload the page.</p></div>`;
  }
  document.getElementById("main").focus({ preventScroll: true });
}

function renderWho() {
  if (!state.user) { who.innerHTML = ""; return; }
  who.innerHTML = `Signed in as <strong>${esc(state.user.name)}</strong><button type="button" id="switch">Switch student</button>`;
  document.getElementById("switch").onclick = () => {
    store("bw-user", null);
    state.user = null; state.forecast = null;
    tabs.hidden = true; renderWho();
    location.hash = "#welcome";
    renderWelcome();
  };
}

// ------------------------------------------------------------------ welcome / onboarding

function renderWelcome() {
  tabs.hidden = true;
  view.innerHTML = `
  <section class="welcome">
    <div>
      <h1>Know which weeks will overload you, before they do.</h1>
      <p class="lede">BeachWell reads your Canvas deadlines, gives every week a workload score, spreads the work out, and finds campus events that fit your free time.</p>
      <div class="preview" aria-hidden="true">
        ${[["Week 8", 92, "Overload"], ["Week 9", 45, "Heavy"], ["Week 10", 78, "Overload"], ["Week 11", 22, "Light"]].map(([wk, sc, lv]) => `
          <div class="prow"><span>${wk}</span><span class="ptrack"><i style="width:${sc}%;background:${LEVEL_COLOR[lv]}"></i></span><b>${sc}</b>${badge(lv)}</div>`).join("")}
      </div>
      <p>Want to look around first? Open the demo as Vy, a CECS student in week 8 of fall semester.</p>
      <div class="actions"><button class="btn" id="demo">Open the demo</button></div>
      <p class="small quiet" style="margin-top:18px">BeachWell plans and recommends. It does not diagnose or replace counseling.</p>
    </div>
    <form class="panel" id="setup">
      <h2>Get your own workload scores</h2>
      <div class="field"><label for="name">First name</label><input id="name" type="text" required maxlength="60" autocomplete="given-name"></div>
      <div class="field"><label for="interests">What helps you recharge?<span class="hint">For example: yoga, hiking, art, quiet places, meeting people. Also say what you'd rather avoid.</span></label>
        <textarea id="interests" maxlength="600"></textarea></div>
      <div class="field"><label for="cap">Hours you can usually study in a week: <span id="capv">25</span></label>
        <input id="cap" type="range" min="10" max="45" step="1" value="25"></div>
      <fieldset><legend>Your deadlines</legend>
        <label class="choice"><input type="radio" name="src" value="url" checked><span>Paste my Canvas Calendar Feed link<span class="hint">In Canvas: Calendar, then Calendar Feed. The link is used once and never stored.</span></span></label>
        <input id="feed" type="url" placeholder="https://csulb.instructure.com/feeds/calendars/user_….ics">
        <label class="choice" style="margin-top:10px"><input type="radio" name="src" value="file"><span>Upload an .ics file</span></label>
        <input id="file" type="file" accept=".ics,text/calendar">
        <label class="choice" style="margin-top:10px"><input type="radio" name="src" value="sample"><span>Use sample courses (CECS 458, CECS 429, MATH 380, ENGL 317, PHIL 352)</span></label>
      </fieldset>
      <fieldset><legend>Class times</legend>
        <p class="small quiet">Study blocks and events never land on top of a class.</p>
        <div id="classes"></div>
        <div class="actions" style="margin-top:6px"><button type="button" class="btn secondary" id="addclass">Add a class</button>
        <button type="button" class="btn secondary" id="sampleclasses">Use the sample schedule</button></div>
      </fieldset>
      <label class="choice"><input type="checkbox" id="radar" checked><span>Count me in the Campus Radar<span class="hint">Only anonymous totals for groups of 10 or more students are ever shown.</span></span></label>
      <p class="error" id="err" role="alert"></p>
      <div class="actions"><button class="btn" type="submit" id="go">Show my workload</button></div>
    </form>
  </section>`;
  const cap = document.getElementById("cap");
  cap.oninput = () => (document.getElementById("capv").textContent = cap.value);
  document.getElementById("demo").onclick = async () => {
    try {
      const d = await api("/api/demo");
      await signIn(d.id);
    } catch (e) { document.getElementById("err").textContent = e.message; }
  };
  let useSampleClasses = false;
  const classesEl = document.getElementById("classes");
  const addRow = () => {
    const row = document.createElement("div");
    row.className = "classrow";
    row.style.cssText = "display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:8px";
    row.innerHTML = `<input type="text" placeholder="Course" aria-label="Course" class="c-name">
      <input type="time" aria-label="Start time" class="c-start" value="10:00"><input type="time" aria-label="End time" class="c-end" value="11:15">
      <div style="grid-column:1/-1;display:flex;gap:10px;flex-wrap:wrap">${["Mon", "Tue", "Wed", "Thu", "Fri"].map((d, i) => `<label class="choice" style="margin:0"><input type="checkbox" value="${i}">${d}</label>`).join("")}</div>`;
    classesEl.append(row);
  };
  document.getElementById("addclass").onclick = addRow;
  document.getElementById("sampleclasses").onclick = () => {
    useSampleClasses = true;
    classesEl.innerHTML = `<p class="small">Sample schedule selected: 10 class meetings, Monday to Friday.</p>`;
  };
  document.getElementById("setup").onsubmit = async (ev) => {
    ev.preventDefault();
    const err = document.getElementById("err");
    const go = document.getElementById("go");
    err.textContent = "";
    go.disabled = true; go.textContent = "Reading your deadlines…";
    try {
      const src = document.querySelector("input[name=src]:checked").value;
      let ics = null;
      if (src === "file") {
        const f = document.getElementById("file").files[0];
        if (!f) throw new Error("Choose an .ics file first.");
        ics = await f.text();
      }
      if (src === "url" && !document.getElementById("feed").value.trim()) throw new Error("Paste your Canvas Calendar Feed link, or pick another option.");
      const user = await api("/api/users", { method: "POST", body: { name: document.getElementById("name").value, interests: document.getElementById("interests").value, weekly_capacity: Number(cap.value), radar_opt_in: document.getElementById("radar").checked } });
      if (user.safety && user.safety.level === "crisis") showCrisis(user.safety);
      if (src === "sample") await api(`/api/users/${user.id}/calendar/sample`, { method: "POST" });
      else await api(`/api/users/${user.id}/calendar`, { method: "POST", body: src === "url" ? { url: document.getElementById("feed").value.trim() } : { ics } });
      if (useSampleClasses) await api(`/api/users/${user.id}/classes`, { method: "PUT", body: { sample: true } });
      else {
        const rows = [...classesEl.querySelectorAll(".classrow")].flatMap((r) => {
          const toH = (v) => { const [h, m] = v.split(":").map(Number); return h + m / 60; };
          return [...r.querySelectorAll("input[type=checkbox]:checked")].map((cb) => ({ course: r.querySelector(".c-name").value || "Class", weekday: Number(cb.value), start_hour: toH(r.querySelector(".c-start").value), end_hour: toH(r.querySelector(".c-end").value) }));
        });
        if (rows.length) await api(`/api/users/${user.id}/classes`, { method: "PUT", body: rows });
      }
      await signIn(user.id);
    } catch (e) {
      err.textContent = e.message;
      go.disabled = false; go.textContent = "Show my workload";
    }
  };
}

async function signIn(id) {
  state.user = await api(`/api/users/${id}`);
  store("bw-user", String(id));
  state.forecast = null; state.selected = 0; state.whatIf = { extra: {}, usePlan: false };
  renderWho();
  if (location.hash === "#forecast") route(); else location.hash = "#forecast";
}

// ------------------------------------------------------------------ forecast

async function renderForecast() {
  const f = await api(`/api/users/${state.user.id}/forecast`);
  state.forecast = f; state.base = f; state.selected = 0; state.whatIf = { extra: {}, usePlan: false };
  const lastCheck = (state.user.checkins || []).at(-1);
  const checkedToday = lastCheck && lastCheck.day === f.today;
  const candidates = whatIfCandidates(f.weeks);
  view.innerHTML = `
    <section class="overview">
      <div class="scorecard" id="scorecard"></div>
      <div class="outlook">
        <div class="outlook-head"><h2>Workload score, next 7 weeks</h2><span class="small quiet">0 = free week, 100 = overload. Select a week for details.</span></div>
        <div class="bars" id="bars" role="list"></div>
        <div class="legend">${LEVELS.map((l) => `<span><i style="background:${LEVEL_COLOR[l]}"></i>${l}</span>`).join("")}</div>
      </div>
    </section>
    <div class="grid2">
      <div>
        <div class="panel" id="detail"></div>
      </div>
      <div>
        <div class="panel whatif">
          <h2>What if you started earlier?</h2>
          <p class="quiet small">Move a slider and watch the scores change. Nothing is saved.</p>
          <label class="switch"><input type="checkbox" id="useplan"> Follow my BeachWell study plan</label>
          ${candidates.length ? candidates.map((t) => `
            <div class="row">
              <label for="wi-${t.id}" style="margin:0">${esc(t.title)}<span class="hint">${esc(t.course)}, due ${fmtDue(t.due)}</span></label>
              <input type="range" id="wi-${t.id}" data-task="${t.id}" min="0" max="21" step="1" value="0" aria-describedby="wo-${t.id}">
              <output id="wo-${t.id}">On the usual schedule</output>
            </div>`).join("") : `<p>No big deadlines in heavy weeks right now.</p>`}
          <p id="wi-summary" class="small" style="margin-top:10px"></p>
        </div>
        ${f.pace.notes.length ? `<div class="panel"><h3>BeachWell learned your pace</h3><ul class="list">${f.pace.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul><p class="small quiet" style="margin-top:8px">Scores already use this. <a href="#pace">Log more hours</a> to sharpen them.</p></div>` : ""}
        ${checkedToday ? "" : `<div class="panel"><h3>How did you sleep?</h3><p class="small">A 20-second check-in makes this week's score more accurate.</p><a class="btn secondary" href="#checkin">Check in</a></div>`}
      </div>
    </div>`;
  drawForecast();
  document.getElementById("bars").onclick = (ev) => {
    const b = ev.target.closest(".wbar");
    if (!b) return;
    state.selected = Number(b.dataset.i);
    drawForecast(state.forecast !== state.base);
  };
  let timer;
  const onChange = () => {
    clearTimeout(timer);
    timer = setTimeout(runWhatIf, 220);
  };
  view.querySelectorAll("input[type=range][data-task]").forEach((r) => {
    r.oninput = () => {
      const v = Number(r.value);
      document.getElementById(`wo-${r.dataset.task}`).textContent = v ? `Start ${v} day${v > 1 ? "s" : ""} earlier` : "On the usual schedule";
      state.whatIf.extra[r.dataset.task] = v;
      onChange();
    };
  });
  document.getElementById("useplan").onchange = (e) => { state.whatIf.usePlan = e.target.checked; onChange(); };
}

function whatIfCandidates(weeks) {
  const seen = new Set();
  return weeks.filter((w) => HEAVY.includes(w.level)).slice(0, 4)
    .flatMap((w) => w.major_deadlines)
    .filter((t) => !seen.has(t.id) && seen.add(t.id))
    .filter((t) => (new Date(t.due) - new Date(state.forecast.today + "T00:00:00")) / 864e5 > 7)
    .slice(0, 4);
}

async function runWhatIf() {
  const f = await api(`/api/users/${state.user.id}/forecast`, { method: "POST", body: { extra_lead: state.whatIf.extra, use_plan: state.whatIf.usePlan } });
  state.forecast = f;
  drawForecast(true);
  const count = (fc) => fc.weeks.filter((w) => w.level === "Overload").length;
  const peak = (fc) => Math.round(Math.max(...fc.weeks.map((w) => w.score)));
  const before = count(state.base), after = count(f);
  const msg = after < before ? `Overload weeks drop from ${before} to ${after}.`
    : after > before ? `That adds an overload week: ${before} to ${after}.`
    : `Overload weeks stay at ${after}; your highest score goes from ${peak(state.base)} to ${peak(f)}.`;
  document.getElementById("wi-summary").textContent = msg;
}

function drawForecast(compare = false) {
  const f = state.forecast, w = f.weeks[state.selected];
  const isNow = state.selected === 0;
  const cap = (r) => r[0].toUpperCase() + r.slice(1);
  const card = document.getElementById("scorecard");
  card.dataset.level = w.level;
  card.innerHTML = `
    <p class="when">${isNow ? "This week" : `Week ${w.week}`}, ${esc(w.label)}</p>
    <div class="scoreline"><span class="score">${Math.round(w.score)}</span><span class="outof">/ 100</span></div>
    <p class="levelname">${w.level} workload</p>
    <div class="gauge" aria-hidden="true"><i style="width:${Math.min(100, w.score)}%"></i></div>
    <ul class="why">${w.reasons.map((r) => `<li>${esc(cap(r))}</li>`).join("")}</ul>
    <p class="meta">${Math.round(w.hours)} h of work · ${w.deadlines} deadline${w.deadlines === 1 ? "" : "s"}</p>`;
  document.getElementById("bars").innerHTML = f.weeks.map((wk, i) => {
    const base = state.base.weeks[i];
    const diff = Math.round(wk.score - base.score);
    const delta = compare && diff ? `<span class="delta ${diff > 0 ? "worse" : ""}">${diff > 0 ? "+" : ""}${diff}</span>` : `<span class="delta"></span>`;
    return `<button class="wbar" role="listitem" data-i="${i}" aria-pressed="${i === state.selected}" aria-label="Week ${wk.week}, ${wk.label}: score ${Math.round(wk.score)}, ${wk.level}">
      <span class="wname">Week ${wk.week}<span class="dates">${esc(wk.label)}</span></span>
      <span class="track">${compare && diff ? `<s style="width:${Math.min(100, base.score)}%"></s>` : ""}<i style="width:${Math.max(2, Math.min(100, wk.score))}%;background:${LEVEL_COLOR[wk.level]}"></i></span>
      <span class="num">${Math.round(wk.score)}</span>${badge(wk.level)}${delta}</button>`;
  }).join("");
  document.getElementById("detail").innerHTML = `
    <h2>Week ${w.week}: what's coming</h2>
    ${w.major_deadlines.length ? `<h3>Big deadlines</h3><ul class="list">${w.major_deadlines.map((t) => `<li><span>${esc(t.title)}<br><span class="small quiet">${esc(t.course)}</span></span><span class="small">${fmtDue(t.due)}</span></li>`).join("")}</ul>` : `<p>No big deadlines this week.</p>`}
    ${w.top_tasks.length ? `<h3 style="margin-top:16px">Where the hours go</h3><ul class="list">${w.top_tasks.map((t) => `<li><span>${esc(t.title)} <span class="small quiet">${esc(t.course)}</span></span><span>${t.hours.toFixed(1)} h</span></li>`).join("")}</ul>` : ""}
    <div class="actions"><a class="btn" href="#plan">See my study plan</a><a class="btn secondary" href="#recharge">Find a break</a></div>`;
}

// ------------------------------------------------------------------ plan

async function renderPlan() {
  const p = await api(`/api/users/${state.user.id}/plan`);
  const weeks = p.weeks;
  const byWeek = (w) => p.blocks.filter((b) => b.day >= w.start && b.day <= w.end);
  state.planWeek = state.planWeek ?? 0;
  view.innerHTML = `
    <h2>Your study plan</h2>
    <p class="quiet">Big assignments are split into blocks of 90 minutes or less, with a 15-minute break after each. Lunch and dinner stay free, and nothing lands on a class or after a due time.</p>
    <div class="panel">
      <h3>Your weeks with and without the plan</h3>
      <div class="compare">${weeks.map((w) => `<div><strong>Week ${w.week}</strong><span>${badge(w.before)}</span><span class="arrow" aria-hidden="true">↓</span><span>${badge(w.after)}</span><span class="small">${Math.round(w.hours_before)} h → ${Math.round(w.hours_after)} h</span></div>`).join("")}</div>
      <p class="small quiet">Hours shift into lighter weeks, so peaks get smaller. ${p.violations.length ? `<span class="error">${p.violations.length} scheduling problems found.</span>` : "Every block passed the scheduling rules."}</p>
    </div>
    <div class="grid2">
      <div class="panel agenda">
        <div class="actions" role="group" aria-label="Choose a week" id="weekpick" style="margin-top:0">${weeks.map((w, i) => `<button class="btn ${i === state.planWeek ? "" : "secondary"}" data-i="${i}">Week ${w.week}</button>`).join("")}</div>
        <div id="agenda"></div>
      </div>
      <div>
        <div class="panel"><h3>Small habits for heavy weeks</h3>${weeks.filter((w) => w.habits.length).map((w) => `<p class="small quiet" style="margin:12px 0 0">Week ${w.week}</p>${w.habits.map((h) => `<div class="tip"><span class="dot" style="background:${LEVEL_COLOR[w.before]}"></span><span>${esc(h.text)}</span></div>`).join("")}`).join("") || "<p>Your weeks look manageable. Keep your usual routine.</p>"}</div>
        ${p.unscheduled.length ? `<div class="panel"><h3>Didn't fit</h3><p class="small">These hours couldn't be placed before the due time within your daily limit of ${p.daily_cap} hours. Consider starting now, asking about an extension, or visiting office hours.</p><ul class="list">${p.unscheduled.map((u) => `<li><span>${esc(u.title)} <span class="small quiet">${esc(u.course)}</span></span><span>${u.hours_left} h</span></li>`).join("")}</ul></div>` : ""}
        <div class="panel"><h3>Put it in your calendar</h3><p class="small">Download the plan and import it into Google Calendar or Apple Calendar. Edit or delete any block there.</p><a class="btn" href="${API}/api/users/${state.user.id}/plan.ics" download>Download plan (.ics)</a></div>
      </div>
    </div>`;
  const drawAgenda = () => {
    const w = weeks[state.planWeek];
    const blocks = byWeek(w);
    const days = [...new Set(blocks.map((b) => b.day))];
    document.getElementById("agenda").innerHTML = `<h3>Week ${w.week}, ${esc(w.label)}</h3>` + (days.length ? days.map((d) => `<h3>${fmtDay(d)}</h3>${blocks.filter((b) => b.day === d).map((b) => `<div class="block"><span class="time">${fmtHour(b.start_hour)}–${fmtHour(b.end_hour)}</span><span>${esc(b.title)}</span><span class="tag">${esc(b.course)}</span></div>`).join("")}`).join("") : "<p>No study blocks planned this week.</p>");
    document.querySelectorAll("#weekpick button").forEach((b) => (b.className = `btn ${Number(b.dataset.i) === state.planWeek ? "" : "secondary"}`));
  };
  document.getElementById("weekpick").onclick = (e) => {
    const b = e.target.closest("button");
    if (b) { state.planWeek = Number(b.dataset.i); drawAgenda(); }
  };
  drawAgenda();
}

// ------------------------------------------------------------------ recharge

async function renderRecharge() {
  if (!state.forecast) state.forecast = await api(`/api/users/${state.user.id}/forecast`);
  const r = await api(`/api/users/${state.user.id}/events`);
  view.innerHTML = `
    <h2>Recharge on campus</h2>
    <p class="quiet">Picked for your heaviest weeks, matched to what you said helps you recharge, and placed in time you actually have free.</p>
    <p class="small"><span class="tag sample">Sample event data</span> Organizers and places are real CSULB programs; dates and times are placeholders for this prototype.</p>
    ${r.weeks.map((w) => `
      <div class="weekhead"><h2>Week ${w.week}, ${esc(w.label)}</h2>${badge(w.level)}</div>
      ${w.picks.length ? `<div class="picks">${w.picks.map((p) => `
        <article class="pick" style="border-left-color:${LEVEL_COLOR[w.level]}">
          <h3>${esc(p.title)}</h3>
          <p class="when" style="margin:0">${esc(p.when)}</p>
          <p class="where" style="margin:0 0 6px">${esc(p.location)}, ${esc(p.organizer)}</p>
          ${p.expected ? `<span class="tag warn">Expected, not posted yet</span>` : ""}
          <p class="why">${esc(p.reason)}</p>
          ${p.source_url ? `<a class="small" href="${esc(p.source_url)}" target="_blank" rel="noopener">About this program</a>` : ""}
        </article>`).join("")}</div>` : `<p>No events fit your free time this week. A 15-minute walk counts too.</p>`}`).join("")}`;
}

// ------------------------------------------------------------------ check-in

async function renderCheckin() {
  state.user = await api(`/api/users/${state.user.id}`);
  const history = state.user.checkins || [];
  let stress = 3, sleep = 7;
  view.innerHTML = `
    <div class="grid2" style="margin-top:0">
      <form class="panel" id="ci">
        <h2>Daily check-in</h2>
        <p class="quiet small">Two numbers, about 20 seconds. Your note is checked for safety and then discarded.</p>
        <div class="field"><label for="sleep">Hours slept last night</label>
          <div class="sleepval" id="sleepv">7 h</div>
          <input id="sleep" type="range" min="2" max="12" step="0.5" value="7" style="width:100%;accent-color:var(--ink)"></div>
        <div class="field"><span id="stresslabel" style="font-weight:700;display:block;margin-bottom:6px">Stress right now</span>
          <div class="stress" role="group" aria-labelledby="stresslabel">${["Calm", "Fine", "Busy", "Stressed", "Overwhelmed"].map((t, i) => `<button type="button" data-v="${i + 1}" aria-pressed="${i === 2}"><b>${i + 1}</b>${t}</button>`).join("")}</div></div>
        <div class="field"><label for="note">Anything on your mind? <span class="hint">Optional.</span></label><textarea id="note" maxlength="1000"></textarea></div>
        <div class="actions"><button class="btn" type="submit">Save check-in</button></div>
      </form>
      <div class="panel"><h2>Last two weeks</h2>${spark(history)}<p class="small quiet">Sleep below your own average, or high stress, raises this week's workload score.</p></div>
    </div>`;
  const s = document.getElementById("sleep");
  s.oninput = () => { sleep = Number(s.value); document.getElementById("sleepv").textContent = `${sleep} h`; };
  view.querySelector(".stress").onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    stress = Number(b.dataset.v);
    view.querySelectorAll(".stress button").forEach((x) => x.setAttribute("aria-pressed", x === b));
  };
  document.getElementById("ci").onsubmit = async (e) => {
    e.preventDefault();
    const res = await api(`/api/users/${state.user.id}/checkins`, { method: "POST", body: { sleep_hours: sleep, stress, note: document.getElementById("note").value } });
    document.getElementById("note").value = "";
    if (res.safety.level === "crisis") showCrisis(res.safety);
    else toast("Check-in saved. Your workload score is updated.");
    state.forecast = null;
    renderCheckin();
  };
}

function spark(history) {
  if (!history.length) return "<p>No check-ins yet.</p>";
  const W = 320, H = 120, n = history.length;
  const x = (i) => (n === 1 ? W / 2 : 16 + (i * (W - 32)) / (n - 1));
  const ys = (v) => H - 14 - ((v - 3) / 9) * (H - 28);
  const yt = (v) => H - 14 - ((v - 1) / 4) * (H - 28);
  const line = (fn, key) => history.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${fn(c[key]).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="Sleep and stress over the last ${n} check-ins">
    <path d="${line(ys, "sleep_hours")}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>
    <path d="${line(yt, "stress")}" fill="none" stroke="var(--heavy)" stroke-width="2.5" stroke-dasharray="5 4"/>
    ${history.map((c, i) => `<circle cx="${x(i)}" cy="${ys(c.sleep_hours)}" r="3" fill="var(--accent)"/>`).join("")}
  </svg><div class="legend"><span><i style="background:var(--accent)"></i> Sleep (hours)</span><span><i style="background:var(--heavy)"></i> Stress (1 to 5)</span><span>Latest: ${history.at(-1).sleep_hours} h, stress ${history.at(-1).stress}</span></div>`;
}

function showCrisis(r) {
  crisisDialog.innerHTML = `<h2 id="crisis-title">${esc(r.title)}</h2><p>${esc(r.message)}</p>
    ${r.contacts.map((c) => `<a class="contact" href="${esc(c.href)}"><b>${esc(c.action)}</b>${esc(c.name)}. ${esc(c.note)}.</a>`).join("")}
    <div class="actions"><button class="btn secondary" id="closecrisis">Close</button></div>`;
  crisisDialog.showModal();
  document.getElementById("closecrisis").onclick = () => crisisDialog.close();
}

// ------------------------------------------------------------------ pace

async function renderPace() {
  const [pace, tasks] = await Promise.all([api(`/api/users/${state.user.id}/pace`), api(`/api/users/${state.user.id}/tasks`)]);
  const today = (state.health?.today) || new Date().toISOString().slice(0, 10);
  const toLog = tasks.filter((t) => t.due.slice(0, 10) < today && !t.actual_hours).slice(-8).reverse();
  const upcoming = tasks.filter((t) => t.due.slice(0, 10) >= today && !t.done).slice(0, 10);
  const types = Object.entries(pace.by_type).sort((a, b) => b[1].logged - a[1].logged);
  view.innerHTML = `
    <h2>My pace</h2>
    <p class="quiet">Every time you log how long something really took, BeachWell adjusts future estimates for that kind of work.</p>
    <div class="grid2">
      <div class="panel">
        <h3>How you compare to the estimates</h3>
        ${types.length ? types.map(([k, v]) => {
          const pct = Math.max(-50, Math.min(50, Math.round((v.multiplier - 1) * 100)));
          const left = pct >= 0 ? 50 : 50 + pct, width = Math.abs(pct);
          return `<div class="mult"><span>${k[0].toUpperCase() + k.slice(1)}</span><span class="track" aria-hidden="true"><i style="left:${left}%;width:${width}%;background:${pct > 0 ? "var(--accent)" : "var(--light)"}"></i><span class="one"></span></span><span class="small">${v.multiplier}×</span></div>`;
        }).join("") + `<p class="small quiet" style="margin-top:8px">The line marks the estimate. Bars to the right mean you usually need more time. Based on ${pace.logged} logged tasks.</p>` : "<p>Log a few finished assignments to see your pace.</p>"}
        ${pace.notes.length ? `<ul class="list" style="margin-top:10px">${pace.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      </div>
      <div>
        <div class="panel"><h3>How long did these take?</h3>
          ${toLog.length ? toLog.map((t) => `<div class="logrow"><span>${esc(t.title)}<span class="hint">${esc(t.course)}</span></span><span class="small quiet est">Est. ${t.base_hours} h</span><input type="number" min="0.25" max="80" step="0.25" placeholder="hours" aria-label="Actual hours for ${esc(t.title)}" data-task="${t.id}" data-field="actual_hours"></div>`).join("") : "<p>Nothing waiting to be logged.</p>"}
        </div>
        <div class="panel"><h3>Fix an estimate</h3>
          ${upcoming.map((t) => `<div class="logrow"><span>${esc(t.title)}<span class="hint">${esc(t.course)}, ${fmtDue(t.due)}</span></span><span class="small quiet est">Now ${t.hours.toFixed(1)} h</span><input type="number" min="0.25" max="80" step="0.25" placeholder="${t.hours.toFixed(1)}" aria-label="Your estimate in hours for ${esc(t.title)}" data-task="${t.id}" data-field="user_hours"></div>`).join("")}
        </div>
      </div>
    </div>`;
  view.querySelectorAll("input[data-task]").forEach((inp) => {
    inp.onchange = async () => {
      if (!inp.value) return;
      try {
        await api(`/api/users/${state.user.id}/tasks/${inp.dataset.task}`, { method: "PATCH", body: { [inp.dataset.field]: Number(inp.value), ...(inp.dataset.field === "actual_hours" ? { done: true } : {}) } });
        toast(inp.dataset.field === "actual_hours" ? "Logged. Your pace is updated." : "Estimate saved.");
        state.forecast = null;
        renderPace();
      } catch (e) { toast(e.message); }
    };
  });
}

// ------------------------------------------------------------------ radar

async function renderRadar() {
  const r = await api("/api/radar");
  const shade = (v) => {
    // light grey -> deep red, through amber
    const stops = [[241, 239, 234], [233, 168, 92], [168, 45, 45]];
    const t = Math.max(0, Math.min(1, v)) * 2, i = Math.min(1, Math.floor(t)), f = t - i;
    const c = stops[i].map((a, k) => Math.round(a + (stops[i + 1][k] - a) * f));
    return `rgb(${c.join(",")})`;
  };
  const cell = (c) => `<td style="background:${shade(c.heavy)};color:${c.heavy > 0.6 ? "#FFFFFF" : "var(--ink)"}" class="${c.week === r.current_week ? "now" : ""}" title="Week ${c.week}: ${Math.round(c.heavy * 100)}% heavy or overload, ${Math.round(c.overload * 100)}% overload">${c.heavy >= 0.3 ? Math.round(c.heavy * 100) : ""}</td>`;
  view.innerHTML = `
    <h2>Campus Stress Radar</h2>
    <p class="quiet">For ASI, CAPS and instructors: when students across campus are heading into heavy weeks, built only from anonymous totals.</p>
    <p class="small"><span class="tag sample">Synthetic cohort</span> ${r.cohort} opted-in students. Groups smaller than ${r.min_group} are never shown${r.suppressed_groups ? ` (${r.suppressed_groups} hidden)` : ""}.</p>
    <div class="panel" style="overflow-x:auto">
      <h3>Share of students in a Heavy or Overload week, by week of term</h3>
      <table class="heat">
        <thead><tr><th></th>${r.weeks.map((w) => `<th scope="col" title="${esc(w.label)}">${w.week}</th>`).join("")}</tr></thead>
        <tbody>
          ${r.campus.length ? `<tr><th scope="row"><strong>All students</strong></th>${r.campus.map(cell).join("")}</tr>` : ""}
          ${r.heatmap.map((row) => `<tr><th scope="row">${esc(row.group)} <span class="quiet">(${row.n})</span></th>${row.cells.map(cell).join("")}</tr>`).join("")}
        </tbody>
      </table>
      <div class="legend"><span>0%</span><i style="background:${shade(0.15)}"></i><i style="background:${shade(0.5)}"></i><i style="background:${shade(0.85)}"></i><span>100%</span><span>Outlined: this week (${r.current_week})</span></div>
    </div>
    <div class="grid2">
      <div class="panel"><h3>Overload alerts for campus programs</h3>
        ${r.alerts.length ? r.alerts.map((a) => `<div class="alert"><strong>Week ${a.week}, ${esc(a.label)}</strong><br>${esc(a.text)}</div>`).join("") : "<p>No overload weeks ahead.</p>"}</div>
      <div class="panel"><h3>Deadline collisions for instructors</h3>
        ${r.collisions.length ? r.collisions.map((c) => `<div class="collision"><strong>${esc(c.course)}: ${esc(c.title)}</strong><br>${esc(c.text)}</div>`).join("") : "<p>No collisions found.</p>"}</div>
    </div>`;
}

// ------------------------------------------------------------------ boot

window.addEventListener("hashchange", route);
(async function boot() {
  try {
    state.health = await api("/api/health");
    document.getElementById("modeline").textContent = state.health.mode === "gemini"
      ? `AI: ${state.health.llm_model} and ${state.health.embedding_model}. Week ${state.health.week} of the semester.`
      : `AI is in offline mode (no Gemini key): estimates and matching use built-in rules. Week ${state.health.week} of the semester.`;
  } catch {
    document.getElementById("modeline").textContent = "Can't reach the BeachWell server. Start it with: uvicorn beachwell.app:app --port 8000";
  }
  const saved = store("bw-user");
  if (saved) {
    try { state.user = await api(`/api/users/${saved}`); } catch { store("bw-user", null); }
  }
  renderWho();
  route();
})();
