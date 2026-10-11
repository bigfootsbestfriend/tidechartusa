-- Tide Chart USA email alerts. One row per (email, station).
CREATE TABLE IF NOT EXISTS subs (
  email TEXT NOT NULL,
  station TEXT NOT NULL,
  weekly INTEGER NOT NULL DEFAULT 1,   -- weekly tide email for the station
  warn INTEGER NOT NULL DEFAULT 1,     -- NWS marine/coastal warnings for its zone
  lows INTEGER NOT NULL DEFAULT 1,     -- weekend minus-tide heads-up
  created TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (email, station)
);
-- Warnings already emailed, so each alert goes out once per subscriber.
CREATE TABLE IF NOT EXISTS sent (
  email TEXT NOT NULL,
  alert TEXT NOT NULL,
  at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (email, alert)
);
-- Visitor conditions reports ("How was it out there?"), shown on station pages.
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  station TEXT NOT NULL,
  at TEXT NOT NULL DEFAULT (datetime('now')),
  chips TEXT NOT NULL DEFAULT '',   -- comma-separated from a fixed list
  note TEXT NOT NULL DEFAULT '',
  who TEXT NOT NULL                 -- salted hash of IP + day, only for rate limiting
);
CREATE INDEX IF NOT EXISTS reports_station ON reports (station, at);
-- One-tap counters per station: accuracy votes and favorites. Totals only, nothing about who.
CREATE TABLE IF NOT EXISTS counts (
  station TEXT PRIMARY KEY,
  up INTEGER NOT NULL DEFAULT 0,
  down INTEGER NOT NULL DEFAULT 0,
  favs INTEGER NOT NULL DEFAULT 0
);
-- Who already voted on a station today (salted hash), so one person can't stuff the counts.
CREATE TABLE IF NOT EXISTS seen (
  key TEXT PRIMARY KEY,
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
