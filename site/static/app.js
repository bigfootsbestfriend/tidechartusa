// Works on every page: saved spots for offline use, the install button, an offline notice, and the
// printable pocket card on station pages. The service worker (sw.js) does the actual offline caching.
(() => {
  const base = document.querySelector('link[rel="icon"]').getAttribute("href").replace(/static\/favicon\.svg$/, "");
  if ("serviceWorker" in navigator) navigator.serviceWorker.register(base + "sw.js").catch(() => {});
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const getSaved = () => { try { return JSON.parse(localStorage.getItem("tc-saved")) || []; } catch (e) { return []; } };
  const setSaved = (list) => { try { localStorage.setItem("tc-saved", JSON.stringify(list)); } catch (e) { /* storage blocked */ } };

  // Saved spots list (home page and the offline page).
  const listBox = document.getElementById("saved-list");
  const paintList = () => {
    const list = getSaved();
    const wrap = document.getElementById("saved");
    if (wrap) wrap.hidden = !list.length;
    if (!listBox) return;
    listBox.innerHTML = list.length ? list.map((s) => `<a class="saved-item" href="${esc(s.path)}"><b>${esc(s.name)}</b>` +
      `<small>Saved ${new Date(s.at).toLocaleDateString([], { month: "short", day: "numeric" })}</small></a>`).join("")
      : "<p>No saved spots yet. On any station page, tap <b>Save offline</b>.</p>";
  };
  paintList();

  // Station pages: Save offline / Print pocket card / Install app.
  const row = document.getElementById("acts-row");
  if (row) {
    row.hidden = false;
    const saveBtn = row.querySelector("[data-save]");
    const name = document.querySelector("h1").textContent.replace(/ tide chart$/, "");
    const path = location.pathname;
    const paintSave = () => {
      const on = getSaved().some((s) => s.path === path);
      saveBtn.setAttribute("aria-pressed", on);
      saveBtn.querySelector("span").textContent = on ? "Saved offline" : "Save offline";
    };
    paintSave();
    saveBtn.addEventListener("click", async () => {
      let list = getSaved();
      const on = list.some((s) => s.path === path);
      try {
        const c = await caches.open("tc-saved");
        if (on) await c.delete(path); else await c.add(path);
      } catch (e) { /* no Cache API: the browser's own cache still helps */ }
      list = on ? list.filter((s) => s.path !== path) : [{ path, name, at: Date.now() }, ...list].slice(0, 30);
      setSaved(list);
      paintSave();
      if (!on) toast("Saved for offline. Want next week's tides too? Tap Email me at the top and we'll send them every Thursday.");
    });
    row.querySelector("[data-pocket]").addEventListener("click", pocket);
  }

  // Install prompt (Chrome/Android/desktop); iPhone users get a hint instead.
  let deferred = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    document.querySelectorAll("[data-install]").forEach((b) => (b.hidden = false));
  });
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  if (ios && !standalone) document.querySelectorAll("[data-install]").forEach((b) => (b.hidden = false));
  document.querySelectorAll("[data-install]").forEach((b) => b.addEventListener("click", async () => {
    if (deferred) { deferred.prompt(); await deferred.userChoice; deferred = null; b.hidden = true; }
    else toast("On iPhone: tap the Share button, then “Add to Home Screen”.");
  }));

  // Offline notice.
  const notice = () => {
    let n = document.getElementById("offline-note");
    if (navigator.onLine) { if (n) n.remove(); return; }
    if (n) return;
    n = document.createElement("div");
    n.id = "offline-note";
    n.className = "offline-note";
    n.textContent = "You're offline. Tide times are from the copy saved on this device; live weather and warnings need a connection.";
    document.querySelector("main").prepend(n);
  };
  addEventListener("online", notice);
  addEventListener("offline", notice);
  notice();

  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4500);
  }

  // Pocket card: the next 7 days on one small printable page, built from what's on screen
  // (so it follows the feet/meters and 12/24h choice).
  function pocket() {
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
    const rowFor = (sel, day) => document.querySelector(`${sel} tr[data-day="${day}"]`);
    const week = [...document.querySelectorAll("table.week:not(.currents):not(.fishing) tbody tr")].filter((r) => !r.hidden).slice(0, 7);
    const rows = week.map((r) => {
      const day = r.dataset.day;
      const tides = [...r.cells[1].querySelectorAll(".ev")].map((e) => esc(txt(e))).join("<br>") || esc(txt(r.cells[1]));
      const fish = rowFor("table.fishing", day);
      const cur = rowFor("table.currents", day);
      const slack = cur ? [...cur.querySelectorAll(".ev.slack")].map((e) => esc(txt(e).replace(/^Slack /, ""))).join(", ") : "";
      return `<tr><th>${esc(txt(r.cells[0]))}</th><td>${tides}</td><td>${esc(txt(r.cells[2]))}</td>` +
        `<td>${fish ? esc(txt(fish.cells[1])) : ""}</td>${document.querySelector("table.currents") ? `<td>${slack}</td>` : ""}</tr>`;
    }).join("");
    const tx = [...document.querySelectorAll(".radio-tx li")].slice(0, 2).map((li) => esc(txt(li))).join("<br>");
    const same = [...document.querySelectorAll(".radio .note b")].map(txt)[0];
    const card = document.createElement("div");
    card.id = "pocket";
    card.innerHTML = `<h1>${esc(txt(document.querySelector("h1")).replace(/ tide chart$/, ""))}</h1>
      <p class="pk-sub">${esc(txt(document.querySelector(".station .sub")))}</p>
      <table><thead><tr><th>Day</th><th>Tides</th><th>Sun</th><th>Fishing</th>${document.querySelector("table.currents") ? "<th>Slack water</th>" : ""}</tr></thead><tbody>${rows}</tbody></table>
      <div class="pk-radio"><b>Radio</b> · VHF 16 distress and calling · 22A Coast Guard · 9 boater calling` +
      (tx ? `<br><b>Weather radio</b> ${tx}` : "") + (same ? `<br><b>Alert radio county code</b> ${esc(same)}` : "") + `</div>
      <p class="pk-foot">tidechartusa.com · printed ${new Date().toLocaleDateString()} · NOAA predictions, not for navigation.</p>`;
    document.body.appendChild(card);
    document.body.classList.add("print-pocket");
    const done = () => { document.body.classList.remove("print-pocket"); card.remove(); removeEventListener("afterprint", done); };
    addEventListener("afterprint", done);
    window.print();
  }
})();
