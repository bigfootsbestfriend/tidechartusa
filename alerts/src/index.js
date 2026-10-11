// Shorebite email signups (Cloudflare Worker + D1 + Resend).
//
//   POST /subscribe     form {email, station, weekly, warn, lows, website (honeypot)}: emails a confirm link,
//                       then redirects to <site>/alerts/#check
//   POST /confirm       JSON {t}: saves the subscription. Returns {state, station}.
//   POST /unsubscribe   JSON {t} from <site>/alerts/?unsub=..., or the one-click List-Unsubscribe POST (?t=...)
//   GET  /admin/subs    (Bearer ADMIN_TOKEN) every subscription, for send.py
//   POST /admin/sent    (Bearer ADMIN_TOKEN) JSON [[email, alertId], ...] warnings that were emailed
//   GET  /community?station=ID   recent conditions reports + accuracy votes + favorite count
//   POST /report        JSON {station, chips[], note}: a visitor's conditions report (emailed to the owner)
//   POST /vote          JSON {station, up}: "Was this accurate?"
//   POST /fav           JSON {station, on}: favorite count up or down
//   GET  /admin/remove?t=...      signed link in the owner's email: deletes a report
//
// Links in emails go to the site's own /alerts/ page, which POSTs the token here, so link scanners
// that open URLs can't confirm or unsubscribe anyone.

const EMAIL = /^[^\s@<>()",;:]{1,64}@[^\s@<>()",;:]{1,190}\.[a-z]{2,}$/i;
const STATION = /^[0-9A-Z]{5,10}$/;
const TOKEN_DAYS = 7;

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    try {
      if (req.method === "OPTIONS") return cors(req, env, new Response(null, { status: 204 }));
      if (url.pathname === "/subscribe" && req.method === "POST") return await subscribe(req, env);
      if (url.pathname === "/confirm" && req.method === "POST") return cors(req, env, await confirm(req, env));
      if (url.pathname === "/unsubscribe" && req.method === "POST") return cors(req, env, await unsubscribe(req, env, url));
      if (url.pathname === "/community" && req.method === "GET") return cors(req, env, await community(env, url));
      if (url.pathname === "/report" && req.method === "POST") return cors(req, env, await report(req, env));
      if (url.pathname === "/vote" && req.method === "POST") return cors(req, env, await vote(req, env));
      if (url.pathname === "/fav" && req.method === "POST") return cors(req, env, await fav(req, env));
      if (url.pathname === "/admin/remove" && req.method === "GET") return await removeReport(env, url);
      if (url.pathname.startsWith("/admin/")) return await admin(req, env, url);
      return new Response("Not found", { status: 404 });
    } catch (err) {
      console.error(err.stack || err);
      return url.pathname === "/subscribe" ? back(env, "error") : json({ state: "error" }, 500);
    }
  },
};

const json = (o, status = 200) => Response.json(o, { status });
const back = (env, state) => Response.redirect(`${env.SITE}/alerts/#${state}`, 303);

function cors(req, env, res) {
  if (req.headers.get("origin") === env.SITE) {
    res.headers.set("access-control-allow-origin", env.SITE);
    res.headers.set("access-control-allow-methods", "GET, POST, OPTIONS");
    res.headers.set("access-control-allow-headers", "content-type");
    res.headers.set("vary", "origin");
  }
  return res;
}

async function subscribe(req, env) {
  const form = await req.formData();
  if (form.get("website")) return back(env, "check"); // bots fill the hidden field
  const email = String(form.get("email") || "").trim().toLowerCase();
  const station = String(form.get("station") || "").trim().toUpperCase();
  const name = String(form.get("name") || "").slice(0, 120);
  if (!EMAIL.test(email) || !STATION.test(station)) return back(env, "invalid");
  const prefs = ["weekly", "warn", "lows"].map((k) => (form.get(k) ? 1 : 0)).join("");
  if (prefs === "000") return back(env, "nothing");
  const token = await sign(env, `c|${email}|${station}|${prefs}|${Date.now()}`);
  const link = `${env.SITE}/alerts/?confirm=${encodeURIComponent(token)}`;
  const where = name ? ` for ${esc(name)}` : "";
  await send(env, {
    from: env.FROM,
    to: [email],
    subject: "Confirm your tide emails",
    html: `<div style="font-family:system-ui,sans-serif;font-size:16px;line-height:1.5;max-width:520px">
<p>Thanks for signing up for tide emails${where} from Shorebite.</p>
<p><a href="${link}" style="display:inline-block;background:#0b5c7a;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:700">Confirm my email</a></p>
<p style="color:#666;font-size:14px">The link works for ${TOKEN_DAYS} days. If you didn't sign up, ignore this email and you won't hear from us.</p>
</div>`,
    text: `Thanks for signing up for tide emails${name ? " for " + name : ""} from Shorebite.\n\nConfirm here: ${link}\n\nIf you didn't sign up, ignore this email.`,
  });
  return back(env, "check");
}

async function confirm(req, env) {
  const body = await req.json().catch(() => ({}));
  const p = await verify(env, String(body.t || ""));
  if (!p || p[0] !== "c") return json({ state: "invalid" }, 400);
  const [, email, station, prefs, ts] = p;
  if (Date.now() - Number(ts) > TOKEN_DAYS * 864e5) return json({ state: "expired" }, 400);
  const [weekly, warn, lows] = prefs.split("").map(Number);
  await env.DB.prepare(
    `INSERT INTO subs (email, station, weekly, warn, lows) VALUES (?1, ?2, ?3, ?4, ?5)
     ON CONFLICT (email, station) DO UPDATE SET weekly = ?3, warn = ?4, lows = ?5`,
  ).bind(email, station, weekly, warn, lows).run();
  return json({ state: "confirmed", station });
}

async function unsubscribe(req, env, url) {
  // One-click unsubscribe (RFC 8058) posts to the URL in the List-Unsubscribe header, token in the query.
  let t = url.searchParams.get("t");
  if (!t) t = String((await req.json().catch(() => ({}))).t || "");
  const p = await verify(env, t);
  if (!p || p[0] !== "u") return json({ state: "invalid" }, 400);
  const [, email, station] = p;
  if (station === "*") await env.DB.prepare("DELETE FROM subs WHERE email = ?1").bind(email).run();
  else await env.DB.prepare("DELETE FROM subs WHERE email = ?1 AND station = ?2").bind(email, station).run();
  return json({ state: "unsubscribed", station });
}

// ---------- community: reports, votes, favorite counts ----------

const CHIPS = ["clear", "murky", "calm", "choppy", "rough", "windy", "crowded", "quiet", "fish-biting", "slow-fishing",
  "great-tidepools", "higher-than-predicted", "lower-than-predicted", "seaweed", "jellyfish"];

// Salted, daily-rotating hash of the visitor's IP: lets us rate-limit without storing who anyone is.
async function who(req, env, extra = "") {
  const ip = req.headers.get("cf-connecting-ip") || "";
  const day = new Date().toISOString().slice(0, 10);
  const h = await crypto.subtle.digest("SHA-256", enc.encode(`${env.TOKEN_SECRET}|${ip}|${day}|${extra}`));
  return b64(h).slice(0, 22);
}

async function community(env, url) {
  const station = String(url.searchParams.get("station") || "").toUpperCase();
  if (!STATION.test(station)) return json({ error: "station" }, 400);
  const reports = (await env.DB.prepare(
    "SELECT id, at, chips, note FROM reports WHERE station = ?1 AND at > datetime('now', '-30 days') ORDER BY at DESC LIMIT 12",
  ).bind(station).all()).results;
  const c = await env.DB.prepare("SELECT up, down, favs FROM counts WHERE station = ?1").bind(station).first();
  const res = json({ reports, up: c ? c.up : 0, down: c ? c.down : 0, favs: c ? c.favs : 0 });
  res.headers.set("cache-control", "public, max-age=60");
  return res;
}

async function report(req, env) {
  const b = await req.json().catch(() => ({}));
  const station = String(b.station || "").toUpperCase();
  if (!STATION.test(station)) return json({ state: "invalid" }, 400);
  const chips = (Array.isArray(b.chips) ? b.chips : []).filter((c) => CHIPS.includes(c)).slice(0, 6);
  let note = String(b.note || "").replace(/\s+/g, " ").trim().slice(0, 280);
  // No links or contact details: those are almost always spam.
  if (/https?:|www\.|\.(com|net|org|io|ru|cn)\b|@\w|\d{3}[\s.-]\d{3}[\s.-]\d{4}/i.test(note)) return json({ state: "nolinks" }, 400);
  if (!chips.length && note.length < 3) return json({ state: "empty" }, 400);
  const w = await who(req, env);
  const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM reports WHERE who = ?1 AND at > datetime('now', '-1 hour')").bind(w).first();
  if (recent && recent.n >= 3) return json({ state: "slow" }, 429);
  const r = await env.DB.prepare("INSERT INTO reports (station, chips, note, who) VALUES (?1, ?2, ?3, ?4) RETURNING id")
    .bind(station, chips.join(","), note, w).first();
  // Tell the owner, with a one-click delete link, so spam doesn't sit on the site.
  if (env.OWNER_EMAIL && env.RESEND_API_KEY) {
    const del = `${new URL(req.url).origin}/admin/remove?t=${encodeURIComponent(await sign(env, `r|${r.id}`))}`;
    await send(env, { from: env.FROM, to: [env.OWNER_EMAIL], subject: `New conditions report: station ${station}`,
      html: `<p><b>${esc(chips.join(", ") || "(no tags)")}</b></p><p>${esc(note) || "(no note)"}</p>` +
        `<p><a href="${env.SITE}/embed/${station}/">Station</a> · <a href="${del}">Delete this report</a></p>` }).catch(() => {});
  }
  return json({ state: "ok" });
}

async function removeReport(env, url) {
  const p = await verify(env, String(url.searchParams.get("t") || ""));
  if (!p || p[0] !== "r") return new Response("That link didn't work.", { status: 400 });
  await env.DB.prepare("DELETE FROM reports WHERE id = ?1").bind(Number(p[1])).run();
  return new Response("Report deleted.", { headers: { "content-type": "text/plain; charset=utf-8" } });
}

async function vote(req, env) {
  const b = await req.json().catch(() => ({}));
  const station = String(b.station || "").toUpperCase();
  if (!STATION.test(station)) return json({ state: "invalid" }, 400);
  const key = await who(req, env, `v|${station}`);
  const fresh = await env.DB.prepare("INSERT OR IGNORE INTO seen (key) VALUES (?1)").bind(key).run();
  if (fresh.meta.changes) {
    const col = b.up ? "up" : "down";
    await env.DB.prepare(`INSERT INTO counts (station, ${col}) VALUES (?1, 1) ON CONFLICT (station) DO UPDATE SET ${col} = ${col} + 1`).bind(station).run();
  }
  await env.DB.prepare("DELETE FROM seen WHERE at < datetime('now', '-2 days')").run();
  return json({ state: "ok" });
}

async function fav(req, env) {
  const b = await req.json().catch(() => ({}));
  const station = String(b.station || "").toUpperCase();
  if (!STATION.test(station)) return json({ state: "invalid" }, 400);
  const key = await who(req, env, `f|${station}|${b.on ? 1 : 0}`);
  const fresh = await env.DB.prepare("INSERT OR IGNORE INTO seen (key) VALUES (?1)").bind(key).run();
  if (fresh.meta.changes) {
    if (b.on) await env.DB.prepare("INSERT INTO counts (station, favs) VALUES (?1, 1) ON CONFLICT (station) DO UPDATE SET favs = favs + 1").bind(station).run();
    else await env.DB.prepare("UPDATE counts SET favs = MAX(0, favs - 1) WHERE station = ?1").bind(station).run();
  }
  return json({ state: "ok" });
}

async function admin(req, env, url) {
  if (!env.ADMIN_TOKEN || req.headers.get("authorization") !== `Bearer ${env.ADMIN_TOKEN}`)
    return new Response("Forbidden", { status: 403 });
  if (url.pathname === "/admin/subs" && req.method === "GET") {
    const subs = (await env.DB.prepare("SELECT email, station, weekly, warn, lows FROM subs").all()).results;
    const since = new Date(Date.now() - 14 * 864e5).toISOString().slice(0, 19).replace("T", " ");
    const sent = (await env.DB.prepare("SELECT email, alert FROM sent WHERE at > ?1").bind(since).all()).results;
    // Unsubscribe tokens are signed here so send.py never needs TOKEN_SECRET.
    for (const s of subs) {
      s.unsub = await sign(env, `u|${s.email}|${s.station}`);
      s.unsub_all = await sign(env, `u|${s.email}|*`);
    }
    return json({ subs, sent });
  }
  if (url.pathname === "/admin/sent" && req.method === "POST") {
    const rows = await req.json();
    const stmt = env.DB.prepare("INSERT OR IGNORE INTO sent (email, alert) VALUES (?1, ?2)");
    if (rows.length) await env.DB.batch(rows.map(([e, a]) => stmt.bind(e, a)));
    await env.DB.prepare("DELETE FROM sent WHERE at < datetime('now', '-30 days')").run();
    return json({ ok: rows.length });
  }
  return new Response("Not found", { status: 404 });
}

async function send(env, body) {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`resend: ${res.status} ${await res.text()}`);
}

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const enc = new TextEncoder();
const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64 = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
const hmacKey = (env) =>
  crypto.subtle.importKey("raw", enc.encode(env.TOKEN_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);

async function sign(env, payload) {
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(env), enc.encode(payload));
  return b64(enc.encode(payload)) + "." + b64(sig);
}

// Returns the payload split on "|", or null.
async function verify(env, token) {
  const [p, s] = token.split(".");
  if (!p || !s) return null;
  try {
    const payload = unb64(p);
    const ok = await crypto.subtle.verify("HMAC", await hmacKey(env), unb64(s), payload);
    return ok ? new TextDecoder().decode(payload).split("|") : null;
  } catch {
    return null;
  }
}
