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
