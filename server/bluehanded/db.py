"""SQLite storage (report 5.2.3).

Stores nodes, detected devices, raw and filtered readings, estimated positions,
alerts with proctor verification, the invigilator whitelist, settings, users and
exam sessions. One connection per thread, WAL mode for concurrent reads.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('proctor', 'admin')),
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    room TEXT,
    started_at REAL NOT NULL,
    ended_at REAL
);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    label TEXT,
    x REAL NOT NULL DEFAULT 0,
    y REAL NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_seen REAL,
    ip TEXT,
    wifi_rssi INTEGER,
    uptime_s INTEGER,
    firmware TEXT,
    online INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS whitelist (
    mac TEXT PRIMARY KEY,
    label TEXT,
    added_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    session_id INTEGER NOT NULL,
    mac TEXT NOT NULL,
    name TEXT,
    addr_type TEXT,
    is_audio INTEGER NOT NULL DEFAULT 0,
    audio_reason TEXT,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    x REAL, y REAL, error REAL, method TEXT,
    nearest_node TEXT, nearest_distance REAL,
    suspicious INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, mac)
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    node_id TEXT NOT NULL,
    mac TEXT NOT NULL,
    rssi INTEGER NOT NULL,
    filtered REAL NOT NULL,
    distance REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_mac ON readings (session_id, mac, ts);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings (ts);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    mac TEXT NOT NULL,
    x REAL NOT NULL, y REAL NOT NULL, error REAL, method TEXT
);
CREATE INDEX IF NOT EXISTS idx_positions ON positions (session_id, ts);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    mac TEXT NOT NULL,
    name TEXT,
    created_at REAL NOT NULL,
    reason TEXT,
    severity TEXT NOT NULL,
    x REAL, y REAL,
    nearest_node TEXT, nearest_distance REAL, rssi REAL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'confirmed', 'false_alarm')),
    verified_by TEXT,
    verified_at REAL,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts ON alerts (session_id, status);
CREATE TABLE IF NOT EXISTS calibration_points (
    id INTEGER PRIMARY KEY,
    created_at REAL NOT NULL,
    node_id TEXT NOT NULL,
    mac TEXT NOT NULL,
    distance REAL NOT NULL,
    mean_rssi REAL NOT NULL,
    samples INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self._local = threading.local()
        self.write_lock = threading.RLock()
        with self.write_lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    # --- helpers -----------------------------------------------------------
    def query(self, sql: str, params=()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        r = self.conn.execute(sql, params).fetchone()
        return dict(r) if r else None

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        with self.write_lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def executemany(self, sql: str, rows) -> None:
        with self.write_lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    # --- settings ----------------------------------------------------------
    def get_settings(self, defaults: dict) -> dict:
        out = dict(defaults)
        for r in self.query("SELECT key, value FROM settings"):
            if r["key"] in out:
                out[r["key"]] = json.loads(r["value"])
        return out

    def set_settings(self, values: dict) -> None:
        self.executemany(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, json.dumps(v)) for k, v in values.items()],
        )

    # --- sessions ----------------------------------------------------------
    def active_session(self) -> dict | None:
        return self.one("SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")

    def start_session(self, name: str, room: str | None = None) -> dict:
        now = time.time()
        with self.write_lock:
            self.conn.execute("UPDATE sessions SET ended_at = ? WHERE ended_at IS NULL", (now,))
            cur = self.conn.execute(
                "INSERT INTO sessions(name, room, started_at) VALUES (?, ?, ?)", (name, room, now)
            )
            self.conn.commit()
        return self.one("SELECT * FROM sessions WHERE id = ?", (cur.lastrowid,))

    def end_session(self, session_id: int) -> None:
        self.execute("UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
                     (time.time(), session_id))

    # --- data clearing (report 6.1.2 "Clear System Data", 7.1 retention) ----
    def clear_session_data(self, session_id: int | None = None) -> None:
        tables = ["readings", "positions", "alerts", "devices"]
        with self.write_lock:
            for t in tables:
                if session_id is None:
                    self.conn.execute(f"DELETE FROM {t}")
                else:
                    self.conn.execute(f"DELETE FROM {t} WHERE session_id = ?", (session_id,))
            if session_id is None:
                self.conn.execute("DELETE FROM sessions WHERE ended_at IS NOT NULL")
                self.conn.execute("DELETE FROM calibration_points")
            else:
                self.conn.execute("DELETE FROM sessions WHERE id = ? AND ended_at IS NOT NULL",
                                  (session_id,))
            self.conn.commit()
        with self.write_lock:
            self.conn.execute("VACUUM")

    def purge_older_than(self, days: float) -> int:
        cutoff = time.time() - days * 86400
        old = [r["id"] for r in self.query(
            "SELECT id FROM sessions WHERE ended_at IS NOT NULL AND ended_at < ?", (cutoff,))]
        for sid in old:
            self.clear_session_data(sid)
        return len(old)
