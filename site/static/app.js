// Works on every page: saved spots for offline use, the install button, an offline notice, and the
// (the printable pocket card is in pocket.js). The service worker (sw.js) does the actual offline caching.
(() => {
  const base = document.querySelector('link[rel="icon"]').getAttribute("href").replace(/static\/favicon\.svg$/, "");
  if ("serviceWorker" in navigator) navigator.serviceWorker.register(base + "sw.js").catch(() => {});
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const getSaved = () => { try { return JSON.parse(localStorage.getItem("tc-saved")) || []; } catch (e) { return []; } };
  const setSaved = (list) => { try { localStorage.setItem("tc-saved", JSON.stringify(list)); } catch (e) { /* storage blocked */ } };

  // Saved spots: the "Saved" link in the header, and the list on the home, saved and offline pages.
  const listBox = document.getElementById("saved-list");
  const paintList = () => {
    const list = getSaved();
    document.querySelectorAll("[data-nav-saved]").forEach((a) => {
      a.hidden = !list.length;
      a.querySelector("[data-saved-count]").textContent = list.length ? ` ${list.length}` : "";
    });
    const wrap = document.getElementById("saved");
    if (wrap) wrap.hidden = !list.length;
    if (!listBox) return;
    listBox.innerHTML = list.length ? list.map((s) => `<div class="saved-item"><a href="${esc(s.path)}"><b>${esc(s.name)}</b>` +
      `<small>Added ${new Date(s.at).toLocaleDateString([], { month: "short", day: "numeric" })} · works offline</small></a>` +
      `<button type="button" class="rm" data-rm="${esc(s.path)}" aria-label="Remove ${esc(s.name)}">×</button></div>`).join("")
      : `<p>No favorites yet. Open any beach or harbor and tap <b>Favorite</b>.</p>`;
  };
  paintList();
  const unsave = async (path) => {
    try { await (await caches.open("tc-saved")).delete(path); } catch (e) { /* no Cache API */ }
    setSaved(getSaved().filter((s) => s.path !== path));
    paintList();
  };
  if (listBox) listBox.addEventListener("click", (e) => { const b = e.target.closest("[data-rm]"); if (b) unsave(b.dataset.rm); });

  // Station pages: Save this spot / Add to home screen / Pocket card.
  const row = document.getElementById("acts-row");
  if (row) {
    row.hidden = false;
    const saveBtn = row.querySelector("[data-save]");
    const name = document.querySelector("h1").textContent.replace(/ tide chart$/, "");
    const path = location.pathname;
    const paintSave = () => {
      const on = getSaved().some((s) => s.path === path);
      saveBtn.setAttribute("aria-pressed", on);
      saveBtn.querySelector("b").textContent = on ? "Favorited" : "Favorite";
      saveBtn.querySelector("small").innerHTML = on ? `In <u>Favorites</u> at the top, and works offline. Tap to remove.`
        : "Keeps it on this device. Works with no signal.";
    };
    paintSave();
    saveBtn.addEventListener("click", async () => {
      const on = getSaved().some((s) => s.path === path);
      if (on) { await unsave(path); paintSave(); return; }
      try { await (await caches.open("tc-saved")).add(path); } catch (e) { /* the browser's own cache still helps */ }
      setSaved([{ path, name, at: Date.now() }, ...getSaved()].slice(0, 30));
      paintSave();
      paintList();
      toast(`<b>Added to your favorites.</b> It's one tap away under <a href="${base}favorites/">★ Favorites</a> at the top of every page, and opens even with no signal.`, 7000);
    });
  }

  // "Add to home screen": shown only where it can work. Chrome, Edge and Android offer a real install
  // prompt; iPhone and iPad need Share → Add to Home Screen, so they get the steps. Hidden once installed.
  let deferred = null;
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const installBtns = () => document.querySelectorAll("[data-install]");
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    if (!standalone) installBtns().forEach((b) => (b.hidden = false));
  });
  window.addEventListener("appinstalled", () => installBtns().forEach((b) => (b.hidden = true)));
  if (ios && !standalone) installBtns().forEach((b) => (b.hidden = false));
  installBtns().forEach((b) => b.addEventListener("click", async () => {
    if (deferred) { deferred.prompt(); await deferred.userChoice; deferred = null; b.hidden = true; return; }
    toast(`<b>Add to your home screen:</b> tap the Share button <svg class="ico" viewBox="0 0 24 24" aria-label="Share"><path d="M12 3v12M8 7l4-4 4 4"/><path d="M6 11H5v10h14V11h-1"/></svg> at the bottom of Safari, ` +
      `scroll down and tap <b>Add to Home Screen</b>. Tide Chart USA then opens like an app.`, 12000);
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

  function toast(html, ms = 4500) {
    document.querySelectorAll(".toast").forEach((t) => t.remove());
    const t = document.createElement("div");
    t.className = "toast";
    t.innerHTML = `<span>${html}</span><button type="button" aria-label="Close">×</button>`;
    t.querySelector("button").addEventListener("click", () => t.remove());
    document.body.appendChild(t);
    setTimeout(() => t.remove(), ms);
  }

})();
