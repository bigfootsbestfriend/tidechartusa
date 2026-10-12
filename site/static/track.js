// Usage tracking for GA4: which parts of each page people actually use, so popular tools can move up and
// ignored ones can be cut. One small listener per event type; nothing personal is sent (no form contents).
//   area_view   a page section scrolled into view (once per page)  -> area
//   ui_click    a link, button, tab, chip or toggle was used        -> area, label, kind, dest
//   ui_change   a select, checkbox, radio or slider was changed      -> area, label, value
//   ui_search   something was typed into a search/filter box        -> area, label, value (the search text)
//   scroll_depth 25/50/75/100% of the page                          -> percent
//   ui_copy / ui_print
// Every event also carries page_type (first part of the path, "home" for /).
(() => {
  if (!window.gtag) return;
  const seg = location.pathname.replace(/^\/(tidechartusa\/)?/, "").split("/")[0];
  const page_type = seg || "home";
  const send = (name, p) => { try { window.gtag("event", name, { page_type, ...p }); } catch {} };
  const clip = (s, n = 60) => (s || "").replace(/\s+/g, " ").trim().slice(0, n);
  const SECTION = "[data-area], section, aside, nav, header, footer, form, details, table, dialog, figure";

  // The section an element belongs to: its data-area, id or first class (e.g. "fishing", "kt-tools", "footer").
  function areaOf(el) {
    const sec = el.closest(SECTION);
    let a = sec && (sec.dataset.area || sec.id || (sec.classList[0] && `${sec.tagName.toLowerCase()}.${sec.classList[0]}`) || sec.tagName.toLowerCase());
    if (!a || /^(section|div)$/.test(a)) {
      const withId = el.closest("[id]");
      const h = sec && sec.querySelector("h1, h2, h3");
      // nearest classed block (e.g. "kt-tools", "ltools") before falling back to an id or the section heading
      let blk = el.parentElement;
      while (blk && blk !== sec && !(blk.tagName === "DIV" && blk.classList.length)) blk = blk.parentElement;
      const cls = blk && blk !== sec && blk.classList[0];
      a = cls || (withId && withId.id) || (h && "“" + clip(h.textContent, 30) + "”") || a || "page";
    }
    return clip(a, 40);
  }
  const labelOf = (el) => clip(el.dataset.track || el.getAttribute("aria-label") || el.title || el.textContent ||
                               el.value || el.name || el.id || el.className);

  // Section views: lets us compare clicks per section with how many people actually saw it.
  const seen = new Set();
  const io = "IntersectionObserver" in window && new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      io.unobserve(e.target);
      const a = areaOf(e.target);
      if (!seen.has(a)) { seen.add(a); send("area_view", { area: a }); }
    }
  }, { threshold: 0.35 });
  const watch = () => io && document.querySelectorAll(SECTION).forEach((el) => {
    if (!el.dataset.twatch && (el.id || el.dataset.area || el.classList.length)) { el.dataset.twatch = 1; io.observe(el); }
  });
  watch();
  setTimeout(watch, 2500); // sections added by scripts after load

  // Clicks on anything interactive
  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("a, button, summary, [role=tab], [role=button], [data-track], label, input[type=checkbox], input[type=radio]");
    if (!el || el.matches("input") ) return; // checkboxes/radios are reported by "change"
    if (el.matches("label") && el.control && el.control.matches("input[type=checkbox], input[type=radio]")) return;
    let kind = el.tagName.toLowerCase(), dest;
    if (kind === "a" && el.href) {
      const u = new URL(el.href, location.href);
      if (u.protocol === "mailto:") { kind = "mailto"; dest = "email"; }
      else if (u.host === location.host) { kind = u.hash && u.pathname === location.pathname ? "jump" : "link"; dest = clip(u.pathname + u.hash, 90); }
      else { kind = "outbound"; dest = u.host; }
    } else if (kind === "summary") {
      kind = el.parentElement.open ? "collapse" : "expand";
    } else if (el.getAttribute("aria-pressed") || el.getAttribute("aria-selected") || el.matches("[role=tab]")) {
      kind = "toggle";
    }
    send("ui_click", { area: areaOf(el), label: labelOf(el), kind, dest });
  }, { capture: true, passive: true });

  // Selects, checkboxes, radios, sliders
  document.addEventListener("change", (ev) => {
    const el = ev.target;
    if (!el.matches("select, input[type=checkbox], input[type=radio], input[type=range]")) return;
    // A <label> wrapping the control would include the option texts: use only its own text
    const own = (l) => l && [...l.childNodes].filter((n) => n.nodeType === 3 || (n.nodeType === 1 && !n.matches("select, input, option"))).map((n) => n.textContent).join(" ");
    const label = clip(el.getAttribute("aria-label") || own(el.labels && el.labels[0]) || el.name || el.id);
    const value = el.matches("select") ? clip(el.options[el.selectedIndex]?.text, 40)
      : el.type === "checkbox" ? (el.checked ? "on" : "off") : clip(el.value, 40);
    send("ui_change", { area: areaOf(el), label, value });
  }, { capture: true, passive: true });

  // Search / filter boxes: the text once typing pauses. Never email, signup or free-text report fields.
  const timers = new WeakMap();
  document.addEventListener("input", (ev) => {
    const el = ev.target;
    if (!el.matches("input[type=search], input[type=text], input:not([type])") || el.closest("form[data-signup-form], [data-no-track]")
        || /mail|name|phone|note|comment|message/i.test(el.name + el.id + el.autocomplete)) return;
    clearTimeout(timers.get(el));
    timers.set(el, setTimeout(() => {
      const v = clip(el.value.toLowerCase(), 40);
      if (v.length >= 2 && v !== el.dataset.tlast) {
        el.dataset.tlast = v;
        send("ui_search", { area: areaOf(el), label: clip(el.getAttribute("aria-label") || el.placeholder || el.name, 40), value: v });
      }
    }, 1500));
  }, { capture: true, passive: true });

  // Scroll depth
  const marks = [25, 50, 75, 100], hit = new Set();
  addEventListener("scroll", () => {
    const h = document.documentElement.scrollHeight - innerHeight;
    if (h < 400) return;
    const pct = (scrollY / h) * 100;
    for (const m of marks) if (pct >= m - 2 && !hit.has(m)) { hit.add(m); send("scroll_depth", { percent: m }); }
  }, { passive: true });

  document.addEventListener("copy", (ev) => send("ui_copy", { area: areaOf(ev.target.nodeType === 1 ? ev.target : ev.target.parentElement || document.body) }));
  addEventListener("beforeprint", () => send("ui_print", {}));
})();
