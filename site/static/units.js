// Feet/meters and 12/24-hour time. Pages are written in feet and 12-hour time; this rewrites the
// text on screen (including anything other scripts add later) and remembers the choice per device.
(() => {
  const read = () => { try { return JSON.parse(localStorage.getItem("tc-units")) || {}; } catch (e) { return {}; } };
  let prefs = Object.assign({ h: "ft", t: "12" }, read());
  const key = () => prefs.h + prefs.t;
  const orig = new WeakMap(); // text node -> original text
  const done = new WeakMap(); // text node -> prefs key it was converted with
  const SKIP = new Set(["SCRIPT", "STYLE", "TEMPLATE", "TEXTAREA", "INPUT", "NOSCRIPT"]);
  const FT = /(-?\d+(?:\.\d+)?) ft\b/g;
  const CLOCK = /\b(\d{1,2})(?::(\d{2}))? (AM|PM)\b/g;
  window.tcUnits = () => prefs;

  const convert = (s) => {
    if (prefs.h === "m") s = s.replace(FT, (_, v) => `${(parseFloat(v) * 0.3048).toFixed(2)} m`.replace("-0.00", "0.00"));
    if (prefs.t === "24") s = s.replace(CLOCK, (_, h, m, ap) => {
      const hh = (+h % 12) + (ap === "PM" ? 12 : 0);
      return `${String(hh).padStart(2, "0")}:${m || "00"}`;
    });
    return s;
  };
  const fix = (n) => {
    if (done.get(n) === key()) return;
    if (!orig.has(n)) orig.set(n, n.nodeValue);
    const before = orig.get(n);
    const after = convert(before);
    done.set(n, key());
    if (n.nodeValue !== after) n.nodeValue = after;
  };
  const walk = (root) => {
    if (root.nodeType === 3) { if (!SKIP.has(root.parentNode && root.parentNode.nodeName)) fix(root); return; }
    if (root.nodeType !== 1 || SKIP.has(root.nodeName)) return;
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (SKIP.has(n.parentNode.nodeName) || !/\d/.test(orig.get(n) || n.nodeValue) ? 2 : 1),
    });
    for (let n; (n = it.nextNode());) fix(n);
  };
  const applyAll = () => walk(document.body);

  // New or changed text from other scripts: remember the new original, then convert.
  const obs = new MutationObserver((muts) => {
    obs.disconnect();
    for (const m of muts) {
      if (m.type === "characterData") {
        const n = m.target;
        if (done.has(n) && n.nodeValue !== convert(orig.get(n))) { orig.set(n, n.nodeValue); done.delete(n); }
        walk(n);
      } else m.addedNodes.forEach((n) => { if (n.nodeType === 3) { orig.set(n, n.nodeValue); done.delete(n); } walk(n); });
    }
    watch();
  });
  const watch = () => obs.observe(document.body, { childList: true, subtree: true, characterData: true });

  const box = document.getElementById("units");
  const paint = () => box && box.querySelectorAll("button").forEach((b) =>
    b.setAttribute("aria-pressed", b.dataset.u === prefs.h || b.dataset.u === prefs.t));
  if (box) {
    box.hidden = false;
    box.addEventListener("click", (e) => {
      const u = e.target.closest("button") && e.target.closest("button").dataset.u;
      if (!u) return;
      if (u === "ft" || u === "m") prefs.h = u; else prefs.t = u;
      try { localStorage.setItem("tc-units", JSON.stringify(prefs)); } catch (err) { /* private mode: this visit only */ }
      paint();
      obs.disconnect();
      applyAll();
      watch();
    });
    paint();
  }
  const start = () => { if (key() !== "ft12") applyAll(); watch(); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
