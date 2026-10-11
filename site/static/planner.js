// "Plan a trip": ranks the next two weeks at this station for an activity, from the page's own data
// (tide predictions, sunrise/sunset, solunar scores, nearby current predictions) plus the NWS wind
// forecast when it has loaded. Times are station-local, like the rest of the page.
(() => {
  const el = document.getElementById("tide-data");
  const card = document.getElementById("plan");
  if (!el || !card) return;
  const data = JSON.parse(el.textContent);
  const now = Date.now() / 1000;
  const all = Object.entries(data.days);
  const start = all.findIndex(([, d]) => now < d[1]);
  if (start < 0) return;
  const days = all.slice(start, start + 14);
  const ev = data.ev;
  const RATE = ["Poor", "Fair", "Good", "Very good", "Excellent"]; // same scale and badges as the fishing table

  const clockIn = (d0) => (t) => {
    let m = Math.round((t - d0) / 60);
    m = ((m % 1440) + 1440) % 1440;
    const h = Math.floor(m / 60), mm = String(m % 60).padStart(2, "0");
    return `${h % 12 || 12}:${mm} ${h < 12 ? "AM" : "PM"}`;
  };
  const ft = (v) => `${v.toFixed(1)} ft`;
  const height = (t) => {
    for (let i = 0; i + 1 < ev.length; i++) {
      const [ta, ha] = ev[i], [tb, hb] = ev[i + 1];
      if (ta <= t && t <= tb) return ha + (hb - ha) * (1 - Math.cos(Math.PI * (t - ta) / (tb - ta))) / 2;
    }
    return null;
  };
  const short = (label) => label.replace(/^(\w{3})\w*, (\w{3})\w* /, "$1, $2 ");
  const inDay = ([s0, s1]) => ev.filter(([t]) => s0 <= t && t < s1);
  const lowsAll = ev.filter((e) => e[2] === "L").map((e) => e[1]).sort((a, b) => a - b);
  const median = (a) => a.length ? a[Math.floor(a.length / 2)] : 0;

  // Daytime wind (max mph) by local date, from the NWS forecast live.js loaded.
  const wind = () => {
    const out = {};
    (window.tcWx || []).forEach((p) => {
      if (!p.isDaytime) return;
      const mph = Math.max(...(String(p.windSpeed).match(/\d+/g) || [0]).map(Number));
      out[p.startTime.slice(0, 10)] = [mph, `${p.windDirection} ${p.windSpeed}`];
    });
    return out;
  };

  const plans = {
    pool(iso, d) {
      const [s0, , rise, set] = d;
      const lows = inDay(d).filter(([t, , k]) => k === "L" && rise && t >= rise - 1800 && t <= set + 1800);
      if (!lows.length) return null;
      const [t, v] = lows.reduce((a, b) => (b[1] < a[1] ? b : a));
      const lo = lowsAll[0], mid = median(lowsAll);
      const q = mid > lo ? (v - lo) / (mid - lo) : 1;
      const r = q <= 0.15 ? 4 : q <= 0.35 ? 3 : q <= 0.6 ? 2 : q <= 1 ? 1 : 0;
      const c = clockIn(s0);
      return { r, sort: v, when: `${c(t - 3600)}–${c(t + 3600)}`,
        why: `Low tide ${ft(v)} at ${c(t)}${v < 0 ? " (a minus tide)" : ""}. Go an hour before; the water comes back fast.` };
    },
    walk(iso, d) {
      const [s0, s1, rise, set] = d;
      if (!rise) return null;
      const evs = inDay(d);
      if (!evs.length) return null;
      const mid = (Math.max(...evs.map((e) => e[1])) + Math.min(...evs.map((e) => e[1]))) / 2;
      let best = [0, 0, 0], run = null;
      for (let t = rise; t <= set; t += 600) {
        const v = height(t);
        if (v !== null && v < mid) { if (!run) run = t; if (t - run > best[0]) best = [t - run, run, t]; } else run = null;
      }
      const hrs = best[0] / 3600;
      if (hrs < 0.5) return null;
      const r = hrs >= 5 ? 4 : hrs >= 4 ? 3 : hrs >= 3 ? 2 : hrs >= 2 ? 1 : 0;
      const c = clockIn(s0);
      return { r, sort: -hrs, when: `${c(best[1])}–${c(best[2])}`,
        why: `${hrs.toFixed(1)} hours of daylight with the tide below half way, so there's the most beach to walk.` };
    },
    fish(iso, d) {
      const f = data.fish && data.fish[iso];
      if (!f) return null;
      const [s0, , rise, set] = d;
      const [score, majors] = f;
      const c = clockIn(s0);
      const light = (m) => rise && m + 3600 > rise - 3600 && m - 3600 < set + 3600;
      const pick = majors.find(light) || majors[0];
      const turn = pick && inDay(d).find(([t]) => Math.abs(t - pick) <= 3600);
      const r = score;
      return { r, sort: -score - (pick && light(pick) ? 0.5 : 0), when: pick ? `${c(pick - 3600)}–${c(pick + 3600)}` : "",
        why: (score >= 3 ? "Strong solunar day" : score === 2 ? "Average solunar day" : "Weak solunar day") +
          (pick ? `; major period ${light(pick) ? "in daylight" : "after dark"}` : "") +
          (turn ? `, with the ${turn[2] === "H" ? "high" : "low"} tide turning at ${c(turn[0])}.` : ".") };
    },
    kayak(iso, d) {
      const [s0, s1, rise, set] = d;
      if (!rise) return null;
      const c = clockIn(s0);
      if (data.cur) {
        const cev = data.cur.ev;
        let best = null;
        cev.forEach(([t, , k], i) => {
          if (k !== "S" || t < rise || t > set - 1800 || t < s0 || t >= s1) return;
          const near = [cev[i - 1], cev[i + 1]].filter((e) => e && e[2] !== "S").map((e) => Math.abs(e[1]));
          const peak = near.length ? Math.max(...near) : 0;
          if (!best || peak < best[1]) best = [t, peak];
        });
        if (!best) return null;
        const r = best[1] < 0.8 ? 4 : best[1] < 1.2 ? 3 : best[1] < 1.8 ? 2 : best[1] < 2.5 ? 1 : 0;
        return { r, sort: best[1], when: `${c(best[0] - 2700)}–${c(best[0] + 2700)}`,
          why: `Slack water at ${c(best[0])}, with currents peaking around ${best[1].toFixed(1)} knots either side (${data.cur.name}).` };
      }
      const evs = inDay(d);
      if (evs.length < 2) return null;
      const range = Math.max(...evs.map((e) => e[1])) - Math.min(...evs.map((e) => e[1]));
      const ranges = days.map(([, dd]) => { const x = inDay(dd).map((e) => e[1]); return x.length ? Math.max(...x) - Math.min(...x) : 0; })
        .sort((a, b) => a - b);
      const q = ranges.indexOf(ranges.find((x) => x >= range)) / Math.max(1, ranges.length - 1);
      const r = q <= 0.2 ? 4 : q <= 0.4 ? 3 : q <= 0.6 ? 2 : q <= 0.8 ? 1 : 0;
      const hi = evs.filter(([t, , k]) => k === "H" && t >= rise && t <= set)[0];
      return { r, sort: range, when: hi ? `${c(hi[0] - 3600)}–${c(hi[0] + 3600)}` : "",
        why: `A ${range < ranges[Math.floor(ranges.length / 2)] ? "small" : "big"} tide day (${ft(range)} range), so gentler tidal currents` +
          (hi ? `; launch around high tide at ${c(hi[0])} for the most water.` : ".") };
    },
  };

  const list = document.getElementById("plan-list");
  const note = document.getElementById("plan-note");
  let act = "pool", showAll = false;
  const render = () => {
    const w = wind();
    const rows = days.map(([iso, d], i) => {
      const p = plans[act](iso, d);
      if (!p) return null;
      const wd = w[iso];
      if (wd && (act === "kayak" || act === "fish" || act === "walk")) {
        if (wd[0] >= 20) { p.r = Math.max(0, p.r - 2); p.why += ` Windy: ${wd[1]} forecast.`; }
        else if (wd[0] >= 13 && act === "kayak") { p.r = Math.max(0, p.r - 1); p.why += ` Breezy: ${wd[1]} forecast.`; }
        else if (act === "kayak") p.why += ` Wind ${wd[1]}.`;
      }
      return { iso, d, i, ...p };
    }).filter(Boolean);
    const ranked = showAll ? rows : [...rows].sort((a, b) => b.r - a.r || a.sort - b.sort).slice(0, 5);
    list.innerHTML = ranked.map((p) => `<li><div class="pl-head"><b>${short(p.d[4])}</b>` +
      `<span class="rate r${p.r}">${RATE[p.r]}</span>${p.when ? `<span class="pl-when">${p.when}</span>` : ""}</div>` +
      `<p>${p.why}</p>${p.i < 7 ? `<button type="button" class="pl-see" data-i="${p.i}">See this day on the chart</button>` : ""}</li>`).join("") ||
      "<li><p>No good options in the next two weeks for this one here.</p></li>";
    note.innerHTML = (showAll ? "All days in date order. " : "The best days in the next two weeks. ") +
      `<button type="button" class="linkish" data-all>${showAll ? "Show the best 5" : "Show all 14 days"}</button>` +
      (act === "kayak" && !data.cur ? " No current station nearby, so this uses the size of the tide." : "") +
      " Always check the forecast and local conditions before you go.";
  };
  card.addEventListener("click", (e) => {
    const a = e.target.closest("[data-act]");
    if (a) {
      act = a.dataset.act;
      card.querySelectorAll("[data-act]").forEach((b) => b.setAttribute("aria-pressed", b === a));
      render();
    }
    if (e.target.closest("[data-all]")) { showAll = !showAll; render(); }
    const see = e.target.closest(".pl-see");
    if (see) {
      const b = document.querySelector(`#daypick button[data-i="${see.dataset.i}"]`);
      if (b) { b.click(); document.getElementById("today").scrollIntoView({ behavior: "smooth", block: "start" }); }
    }
  });
  window.addEventListener("tc:wx", render);
  card.hidden = false;
  render();
})();
