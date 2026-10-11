// Station page: redraws today's chart in the visitor's browser with a "now" marker, says
// whether the tide is rising or falling, and hides table rows for days that have passed.
// Times are shown in the station's local time: each day carries its local-midnight epoch,
// so a time is (epoch - midnight) seconds into that day wherever the visitor is.
(() => {
  const el = document.getElementById("tide-data");
  if (!el) return;
  const data = JSON.parse(el.textContent);
  const ev = data.ev; // [epoch, feet, "H"|"L"]
  const days = Object.entries(data.days); // [iso, [start, end, sunrise, sunset, label]]
  const now = Date.now() / 1000;
  const today = days.find(([, d]) => d[0] <= now && now < d[1]);
  if (!today) return; // data is stale or not yet started: keep the server-rendered page

  const [key] = today;
  let t0, t1;
  const clock = (t) => {
    // Local clock time from the start of the station's day (handles any visitor time zone).
    let m = Math.round((t - t0) / 60);
    const dayM = 24 * 60;
    m = ((m % dayM) + dayM) % dayM;
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

  // Chart (same layout as the server-rendered SVG in site/build.py) for one day.
  const draw = ([iso, [s0, s1, rise, set, label]], isToday) => {
    t0 = s0; t1 = s1;
    const W = 640, H = 220, L = 34, B = 26, T = 22;
    const pts = [];
    for (let t = t0; t <= t1; t += 600) { const v = height(t); if (v !== null) pts.push([t, v]); }
    if (pts.length > 1) {
      let lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
      const span = hi - lo || 1; lo -= span * 0.12; hi += span * 0.15;
      const x = (t) => L + (t - t0) / (t1 - t0) * (W - L - 6);
      const y = (v) => T + (hi - v) / (hi - lo) * (H - T - B);
      const line = pts.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
      let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Tide height through the day">`;
      if (rise && set) { const a = x(Math.max(t0, rise)), b = x(Math.min(t1, set)); s += `<rect class="day" x="${a.toFixed(1)}" y="${T}" width="${Math.max(0, b - a).toFixed(1)}" height="${H - T - B}"/>`; }
      [[0, "12 AM"], [6, "6 AM"], [12, "12 PM"], [18, "6 PM"], [24, ""]].forEach(([hr, lab]) => {
        const tx = x(t0 + hr * 3600);
        s += `<line class="grid" x1="${tx.toFixed(1)}" x2="${tx.toFixed(1)}" y1="${T}" y2="${H - B}"/>`;
        if (lab) s += `<text class="ax" x="${(tx + 3).toFixed(1)}" y="${H - 8}">${lab}</text>`;
      });
      if (lo < 0 && hi > 0) s += `<line class="zero" x1="${L}" x2="${W - 6}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}"/>`;
      s += `<path class="area" d="M${x(pts[0][0]).toFixed(1)},${H - B} L${line.replace(/ /g, " L")} L${x(pts[pts.length - 1][0]).toFixed(1)},${H - B} Z"/><polyline class="line" points="${line}"/>`;
      ev.filter(([t]) => t0 <= t && t <= t1).forEach(([t, v, k]) => {
        const cx = x(t), cy = y(v), ty = k === "H" ? cy - 9 : cy + 17;
        const anchor = cx < 90 ? "start" : cx > W - 90 ? "end" : "middle";
        s += `<circle class="pt ${k}" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4"/><text class="lab" x="${cx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${anchor}">${clock(t)} · ${ft(v)}</text>`;
      });
      const nv = isToday ? height(now) : null;
      if (nv !== null) s += `<line class="nowline" x1="${x(now).toFixed(1)}" x2="${x(now).toFixed(1)}" y1="${T}" y2="${H - B}"/><circle class="nowpt" cx="${x(now).toFixed(1)}" cy="${y(nv).toFixed(1)}" r="5"/>`;
      s += `<text class="ax" x="2" y="${T + 4}">${ft(hi - span * 0.15)}</text></svg>`;
      document.getElementById("chart").innerHTML = s;
    }
    document.getElementById("today-title").textContent = isToday ? `Tides today, ${label}` : `Tides ${label}`;
    document.getElementById("tlist").innerHTML = ev.filter(([t]) => t0 <= t && t < t1)
      .map(([t, v, k]) => `<li class="${k}"><b>${k === "H" ? "High" : "Low"}</b> ${clock(t)} <span>${ft(v)}</span></li>`).join("");
    document.getElementById("now").hidden = !isToday;
    // Sun/moon, fishing and currents for the chosen day, copied from the tables further down.
    const row = (sel) => document.querySelector(`${sel} tr[data-day="${iso}"]`);
    const wk = row("table.week:not(.currents):not(.fishing)");
    const sun = document.getElementById("sunline");
    if (wk && sun) sun.innerHTML = `Sunrise / sunset ${wk.cells[2].innerHTML} · ${wk.cells[3].innerHTML}`;
    const extra = [];
    const fish = row("table.fishing");
    if (fish) extra.push(`<p><b>Fishing:</b> ${fish.cells[1].innerHTML} major ${fish.cells[2].textContent}</p>`);
    const cur = row("table.currents");
    if (cur) extra.push(`<div><b>Currents:</b><div class="evs">${cur.cells[1].innerHTML}</div></div>`);
    document.getElementById("dayextra").innerHTML = extra.join("");
  };

  const ti = days.indexOf(today);
  draw(today, true);
  const pick = document.getElementById("daypick");
  if (pick) {
    const week = days.slice(ti, ti + 7);
    pick.innerHTML = week.map(([iso, d], i) => `<button type="button" data-i="${i}" aria-pressed="${i === 0}">` +
      `${i === 0 ? "Today" : d[4].split(",")[0].slice(0, 3)}<small>${i === 0 ? "" : d[4].replace(/^\w+, \w+ /, "")}</small></button>`).join("");
    pick.hidden = false;
    pick.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      pick.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      draw(week[+b.dataset.i], b.dataset.i === "0");
    });
  }

  // Rising or falling, and the next turn of the tide (t0/t1 are today's at this point).
  const next = ev.find(([t]) => t > now);
  const nv = height(now);
  if (next && nv !== null) {
    const mins = Math.round((next[0] - now) / 60);
    const wait = mins >= 60 ? `${Math.floor(mins / 60)} h ${mins % 60} min` : `${mins} min`;
    const p = document.getElementById("now");
    p.innerHTML = `Now about <b>${ft(nv)}</b> and <b>${next[2] === "H" ? "rising" : "falling"}</b>. Next ${next[2] === "H" ? "high" : "low"} tide at ${clock(next[0])}${next[0] >= t1 ? " tomorrow" : ""} (${ft(next[1])}), in ${wait}.`;
    p.hidden = false;
  }

  // Drop days that have already passed from the week and month tables.
  document.querySelectorAll("tr[data-day]").forEach((tr) => { if (tr.dataset.day < key) tr.remove(); });
})();

// Tabs for the long tables (buttons built from each panel's data-tab and icon), and the sticky
// "jump to" row. Without JavaScript every panel shows and the jump links are plain anchors.
(() => {
  const showers = [];
  document.querySelectorAll("[data-tabs]").forEach((box) => {
    const panels = [...box.querySelectorAll(":scope > .tab")];
    if (panels.length < 2) return;
    const bar = document.createElement("div");
    bar.className = "tabbar";
    bar.setAttribute("role", "tablist");
    const show = (i) => panels.forEach((p, j) => {
      p.hidden = i !== j;
      bar.children[j].setAttribute("aria-selected", i === j);
    });
    panels.forEach((p, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "tab");
      const t = p.querySelector("template.tab-ico");
      if (t) b.appendChild(t.content.cloneNode(true));
      b.appendChild(document.createTextNode(p.dataset.tab));
      b.addEventListener("click", () => show(i));
      bar.appendChild(b);
    });
    box.prepend(bar);
    box.classList.add("on");
    show(0);
    showers.push((el) => {
      const i = panels.findIndex((p) => p.contains(el));
      if (i >= 0) show(i);
      return i >= 0;
    });
    // Printing always prints the month table.
    window.addEventListener("beforeprint", () => show(panels.findIndex((p) => p.id === "month-tab")));
  });

  // Make a target visible (open its tab or its collapsed box) and scroll to it.
  const reveal = (id, smooth) => {
    const el = id && document.getElementById(id);
    if (!el) return false;
    showers.forEach((f) => f(el));
    if (el.tagName === "DETAILS") el.open = true;
    const tabs = el.closest("[data-tabs]");
    (tabs && el.closest(".tab") ? tabs : el).scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    return true;
  };
  if (location.hash) reveal(location.hash.slice(1), false);
  window.addEventListener("hashchange", () => reveal(location.hash.slice(1), true));

  const nav = document.querySelector("nav.jump");
  if (!nav) return;
  const links = [...nav.querySelectorAll("a")];
  links.forEach((a) => a.addEventListener("click", (e) => {
    const id = a.getAttribute("href").slice(1);
    if (reveal(id, true)) { e.preventDefault(); history.replaceState(null, "", "#" + id); mark(a); }
  }));
  const mark = (a) => links.forEach((l) => l.classList.toggle("here", l === a));
  // Highlight the section on screen (tab sections count as the tab box).
  const spots = links.map((a) => {
    const el = document.getElementById(a.getAttribute("href").slice(1));
    return el && (el.closest(".tab") ? null : el);
  });
  const tabsBox = document.querySelector("[data-tabs]");
  addEventListener("scroll", () => {
    const y = nav.getBoundingClientRect().bottom + 20;
    let cur = null, best = -Infinity;
    links.forEach((a, i) => {
      const el = spots[i] || (tabsBox && tabsBox.querySelector(`.tab:not([hidden]) #${a.getAttribute("href").slice(1)}`) && tabsBox);
      const top = el ? el.getBoundingClientRect().top : Infinity;
      if (top <= y && top > best) { best = top; cur = a; }
    });
    if (cur && !cur.classList.contains("here")) { mark(cur); cur.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  }, { passive: true });
})();
