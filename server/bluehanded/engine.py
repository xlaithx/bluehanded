"""The localization and detection engine (report Chapter 4 and flow chart 6.2.1 Raspberry Pi).

For every scan message from an ESP32 node it:
  1. parses the payload (node id, MAC, RSSI, advert hints),
  2. smooths each (device, node) RSSI stream with a 1D Kalman filter,
  3. converts filtered RSSI to distance with the calibrated path loss model,
  4. stores raw + filtered readings in SQLite.

Once per second (tick) it:
  5. estimates the (x, y) position of every active device by multilateration,
  6. classifies devices as suspicious (proximity + persistence + profile, minus whitelist),
  7. raises an alert the first time a device becomes suspicious,
  8. pushes the live state to the dashboard through the `emit` callback.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable

from . import profiles
from .db import Database
from .localization import Anchor, locate
from .rssi import Kalman1D, PathLossModel, proximity_band

log = logging.getLogger(__name__)

Emit = Callable[[str, object], None]

POSITION_ALPHA = 0.3  # weight of a new position fix in the smoothed position
NEAR_MAJORITY = 0.6
FLOOR_MARGIN_DB = 3  # readings within this many dB of node_min_rssi are not used for positioning
COVERAGE_SLACK = 1.25  # allowed overshoot of the nearest-node distance for "inside the hall"  # fraction of the last ticks in which the device must be near


def norm_mac(mac: str) -> str:
    return mac.strip().lower().replace("-", ":")


@dataclass
class LinkState:
    """State for one (device, node) pair."""

    kalman: Kalman1D
    raw: int = 0
    filtered: float = 0.0
    distance: float = 0.0
    last_ts: float = 0.0
    history: deque = field(default_factory=lambda: deque(maxlen=120))  # (ts, raw, filtered)


@dataclass
class DeviceState:
    mac: str
    first_seen: float
    last_seen: float
    name: str | None = None
    addr_type: str | None = None
    is_audio: bool = False
    audio_reason: str = ""
    links: dict[str, LinkState] = field(default_factory=dict)
    cycles: dict[str, deque] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=64)))
    position: dict | None = None
    suspicious: bool = False
    reasons: list[str] = field(default_factory=list)
    persistence: int = 0
    smooth: tuple[float, float] | None = None
    near_hist: deque = field(default_factory=lambda: deque(maxlen=10))


class Engine:
    def __init__(self, db: Database, config: dict, emit: Emit | None = None):
        self.db = db
        self.config = config
        self.emit: Emit = emit or (lambda event, data: None)
        self.lock = threading.RLock()
        self.devices: dict[str, DeviceState] = {}
        self.nodes: dict[str, dict] = {}
        self.whitelist: dict[str, str] = {}
        self.alerted: set[str] = set()  # MACs that already have an alert this session
        self.settings: dict = {}
        self.session: dict = {}
        self.on_settings_changed: Callable[[dict], None] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_position_log: dict[str, float] = {}
        self.reload()

    # ------------------------------------------------------------------ setup
    def reload(self) -> None:
        with self.lock:
            self.settings = self.db.get_settings(self.config["settings"])
            for n in self.config.get("nodes", []):
                self.db.execute(
                    "INSERT OR IGNORE INTO nodes(id, label, x, y) VALUES (?, ?, ?, ?)",
                    (n["id"], n.get("label", n["id"]), float(n["x"]), float(n["y"])),
                )
            self.nodes = {n["id"]: n for n in self.db.query("SELECT * FROM nodes")}
            self.whitelist = {r["mac"]: r["label"] for r in self.db.query("SELECT * FROM whitelist")}
            self.session = self.db.active_session() or self.db.start_session(
                time.strftime("Exam %Y-%m-%d %H:%M"), self.config["room"]["name"])
            self.alerted = {r["mac"] for r in self.db.query(
                "SELECT DISTINCT mac FROM alerts WHERE session_id = ?", (self.session["id"],))}

    @property
    def model(self) -> PathLossModel:
        return PathLossModel(self.settings["rssi_at_1m"], self.settings["path_loss_n"])

    def update_settings(self, values: dict) -> dict:
        with self.lock:
            clean = {}
            for k, v in values.items():
                if k not in self.config["settings"]:
                    continue
                default = self.config["settings"][k]
                if isinstance(default, bool):
                    clean[k] = v in (True, "true", "on", "1", 1)
                elif isinstance(default, int):
                    clean[k] = int(float(v))
                else:
                    clean[k] = float(v)
            self.db.set_settings(clean)
            self.settings.update(clean)
            # Kalman parameters apply to all existing filters.
            for d in self.devices.values():
                for link in d.links.values():
                    link.kalman.q = self.settings["kalman_q"]
                    link.kalman.r = self.settings["kalman_r"]
        if self.on_settings_changed:
            self.on_settings_changed(self.settings)
        return self.settings

    def new_session(self, name: str) -> dict:
        with self.lock:
            self.session = self.db.start_session(name, self.config["room"]["name"])
            self.devices.clear()
            self.alerted.clear()
        self.emit("snapshot", self.snapshot())
        return self.session

    # --------------------------------------------------------------- ingest
    def handle_status(self, node_id: str, payload: dict) -> None:
        """Heartbeat / LWT message from a node."""
        now = time.time()
        online = payload.get("status", "online") != "offline"
        with self.lock:
            self._ensure_node(node_id)
            self.db.execute(
                "UPDATE nodes SET online=?, last_seen=?, ip=COALESCE(?, ip), wifi_rssi=COALESCE(?, wifi_rssi), "
                "uptime_s=COALESCE(?, uptime_s), firmware=COALESCE(?, firmware) WHERE id=?",
                (int(online), now if online else self.nodes[node_id].get("last_seen"),
                 payload.get("ip"), payload.get("wifi_rssi"), payload.get("uptime"),
                 payload.get("fw"), node_id),
            )
            self.nodes[node_id] = self.db.one("SELECT * FROM nodes WHERE id=?", (node_id,))
        self.emit("nodes", self.node_list())

    def _ensure_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            # Unknown node: register it at (0,0) disabled so the admin can place it.
            log.warning("New node %s registered; set its position in Admin > Nodes", node_id)
            self.db.execute("INSERT OR IGNORE INTO nodes(id, label, x, y, enabled) VALUES (?, ?, 0, 0, 0)",
                            (node_id, node_id))
            self.nodes[node_id] = self.db.one("SELECT * FROM nodes WHERE id=?", (node_id,))

    def handle_scan(self, node_id: str, payload: dict, ts: float | None = None) -> int:
        """Process one scan batch from a node. Returns the number of readings stored."""
        now = ts or time.time()
        seq = payload.get("seq", int(now))
        rows = []
        with self.lock:
            self._ensure_node(node_id)
            node = self.nodes[node_id]
            node.update(online=1, last_seen=now)
            sid = self.session["id"]
            for item in payload.get("devices", []):
                try:
                    mac = norm_mac(item["mac"])
                    raw = int(item["rssi"])
                except (KeyError, ValueError, TypeError):
                    continue
                dev = self.devices.get(mac)
                if dev is None:
                    dev = DeviceState(mac=mac, first_seen=now, last_seen=now)
                    self.devices[mac] = dev
                dev.last_seen = now
                if item.get("name"):
                    dev.name = str(item["name"])[:64]
                if item.get("addr_type"):
                    dev.addr_type = str(item["addr_type"])
                is_audio, reason = profiles.classify(
                    dev.name, item.get("uuids"), item.get("appearance"),
                    item.get("company_id"), item.get("mfg_type"))
                if is_audio and not dev.is_audio:
                    dev.is_audio, dev.audio_reason = True, reason
                link = dev.links.get(node_id)
                if link is None:
                    link = LinkState(Kalman1D(self.settings["kalman_q"], self.settings["kalman_r"]))
                    dev.links[node_id] = link
                link.raw = raw
                link.filtered = link.kalman.update(raw)
                link.distance = self.model.distance(link.filtered)
                link.last_ts = now
                link.history.append((now, raw, round(link.filtered, 2)))
                dev.cycles[node_id].append((now, seq))
                rows.append((sid, now, node_id, mac, raw, link.filtered, link.distance))
            self.db.execute("UPDATE nodes SET online=1, last_seen=? WHERE id=?", (now, node_id))
        if rows:
            self.db.executemany(
                "INSERT INTO readings(session_id, ts, node_id, mac, rssi, filtered, distance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    # ----------------------------------------------------------------- tick
    def tick(self, now: float | None = None) -> None:
        now = now or time.time()
        s = self.settings
        room = self.config["room"]
        new_alerts = []
        device_rows, position_rows = [], []
        with self.lock:
            coverage = self._coverage_radius()
            # Nodes that stopped sending heartbeats or scans go offline.
            for nid, n in self.nodes.items():
                if n.get("online") and n.get("last_seen") and now - n["last_seen"] > max(30, 4 * s["scan_seconds"]):
                    n["online"] = 0
                    self.db.execute("UPDATE nodes SET online=0 WHERE id=?", (nid,))
            for mac, dev in list(self.devices.items()):
                # Forget devices not heard for a while (they stay in the DB).
                if now - dev.last_seen > 5 * s["stale_s"]:
                    del self.devices[mac]
                    continue
                anchors = []
                for nid, link in dev.links.items():
                    node = self.nodes.get(nid)
                    if not node or not node.get("enabled") or now - link.last_ts > s["stale_s"]:
                        continue
                    anchors.append(Anchor(nid, node["x"], node["y"], link.distance, link.filtered))
                # Readings close to the nodes' sensitivity floor are biased (only the lucky,
                # stronger-than-real packets get through), so they under-estimate distance.
                # Leave them out of the position fix when better ones exist.
                floor = s["node_min_rssi"] + FLOOR_MARGIN_DB
                strong = [a for a in anchors if a.rssi >= floor]
                if strong:
                    anchors = strong
                pos = locate(anchors, room["width"], room["height"])
                if pos:
                    # Exponential smoothing of the position: one noisy fix should not move
                    # a device across the room (or out of / into the hall).
                    if dev.smooth is None:
                        dev.smooth = (pos.raw_x, pos.raw_y)
                    else:
                        a = POSITION_ALPHA
                        dev.smooth = (a * pos.raw_x + (1 - a) * dev.smooth[0],
                                      a * pos.raw_y + (1 - a) * dev.smooth[1])
                    pos.raw_x, pos.raw_y = dev.smooth
                    pos.x = min(max(dev.smooth[0], 0.0), room["width"])
                    pos.y = min(max(dev.smooth[1], 0.0), room["height"])
                dev.position = pos.__dict__ if pos else None

                # Persistence: number of distinct scan cycles (per node) in the window.
                window_start = now - s["persistence_window_s"]
                dev.persistence = max(
                    (len({seq for t, seq in c if t >= window_start}) for c in dev.cycles.values()),
                    default=0)

                reasons = []
                near = False
                if pos:
                    m = s["inside_margin_m"]
                    # Inside = at least `m` metres inside the walls (positive margin is stricter).
                    inside = (len(anchors) >= 3 and m <= pos.raw_x <= room["width"] - m
                              and m <= pos.raw_y <= room["height"] - m
                              and pos.nearest_distance <= COVERAGE_SLACK * coverage)
                    close = pos.nearest_distance <= s["proximity_m"]
                    near_now = close or inside
                    dev.near_hist.append(near_now)
                    # "Near" must hold for most of the recent ticks, not just one.
                    near = sum(dev.near_hist) >= NEAR_MAJORITY * len(dev.near_hist) and len(dev.near_hist) >= 5
                else:
                    dev.near_hist.append(False)
                if pos:
                    if close:
                        reasons.append(f"{pos.nearest_distance:.1f} m from {pos.nearest_node}")
                    elif inside:
                        reasons.append("located inside the hall")
                persistent = dev.persistence >= s["persistence_cycles"]
                if persistent:
                    reasons.append(f"seen in {dev.persistence} scan cycles")
                if dev.is_audio:
                    reasons.append(f"audio device ({dev.audio_reason})")
                whitelisted = mac in self.whitelist
                dev.suspicious = (near and persistent and not whitelisted
                                  and (dev.is_audio or not s["audio_only"]))
                dev.reasons = reasons

                if dev.suspicious and mac not in self.alerted:
                    self.alerted.add(mac)
                    best = min(dev.links.values(), key=lambda link: link.distance)
                    new_alerts.append((dev, pos, best.filtered, "; ".join(reasons)))

                if pos:
                    device_rows.append((dev.name, dev.addr_type, int(dev.is_audio), dev.audio_reason,
                                        dev.last_seen, pos.x, pos.y, pos.error, pos.method,
                                        pos.nearest_node, pos.nearest_distance, int(dev.suspicious),
                                        self.session["id"], mac, dev.first_seen))
                    if now - self._last_position_log.get(mac, 0) >= 5:
                        self._last_position_log[mac] = now
                        position_rows.append((self.session["id"], now, mac, pos.x, pos.y, pos.error, pos.method))

        if device_rows:
            self.db.executemany(
                "INSERT INTO devices(name, addr_type, is_audio, audio_reason, last_seen, x, y, error, method, "
                "nearest_node, nearest_distance, suspicious, session_id, mac, first_seen) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(session_id, mac) DO UPDATE SET name=COALESCE(excluded.name, name), "
                "addr_type=excluded.addr_type, is_audio=MAX(is_audio, excluded.is_audio), "
                "audio_reason=COALESCE(excluded.audio_reason, audio_reason), last_seen=excluded.last_seen, "
                "x=excluded.x, y=excluded.y, error=excluded.error, method=excluded.method, "
                "nearest_node=excluded.nearest_node, nearest_distance=excluded.nearest_distance, "
                "suspicious=MAX(suspicious, excluded.suspicious)",
                device_rows)
        if position_rows:
            self.db.executemany(
                "INSERT INTO positions(session_id, ts, mac, x, y, error, method) VALUES (?,?,?,?,?,?,?)",
                position_rows)
        for dev, pos, rssi, reason in new_alerts:
            alert = self._create_alert(dev, pos, rssi, reason, now)
            self.emit("alert", alert)
        self.emit("devices", self.device_list(now))
        self.emit("nodes", self.node_list())

    def _coverage_radius(self) -> float:
        """Largest distance from any point of the hall to its nearest enabled node.

        A device whose nearest node is clearly farther than this cannot be inside the hall.
        """
        room = self.config["room"]
        nodes = [n for n in self.nodes.values() if n.get("enabled")]
        if not nodes:
            return 0.0
        best = 0.0
        steps = 24
        for i in range(steps + 1):
            for j in range(steps + 1):
                x, y = room["width"] * i / steps, room["height"] * j / steps
                best = max(best, min(((n["x"] - x) ** 2 + (n["y"] - y) ** 2) ** 0.5 for n in nodes))
        return best

    def _create_alert(self, dev: DeviceState, pos, rssi: float, reason: str, now: float) -> dict:
        severity = "high" if dev.is_audio else "medium"
        cur = self.db.execute(
            "INSERT INTO alerts(session_id, mac, name, created_at, reason, severity, x, y, nearest_node, "
            "nearest_distance, rssi) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.session["id"], dev.mac, dev.name, now, reason, severity,
             pos.x if pos else None, pos.y if pos else None,
             pos.nearest_node if pos else None, pos.nearest_distance if pos else None, rssi))
        log.info("ALERT %s %s: %s", severity, dev.mac, reason)
        return self.db.one("SELECT * FROM alerts WHERE id=?", (cur.lastrowid,))

    # ----------------------------------------------------- proctor actions
    def verify_alert(self, alert_id: int, verdict: str, user: str, note: str = "",
                     whitelist: bool = False) -> dict | None:
        if verdict not in ("confirmed", "false_alarm"):
            raise ValueError("verdict must be 'confirmed' or 'false_alarm'")
        self.db.execute(
            "UPDATE alerts SET status=?, verified_by=?, verified_at=?, note=? WHERE id=?",
            (verdict, user, time.time(), note, alert_id))
        alert = self.db.one("SELECT * FROM alerts WHERE id=?", (alert_id,))
        if alert and whitelist and verdict == "false_alarm":
            self.add_whitelist(alert["mac"], note or alert.get("name") or "verified safe")
        if alert:
            self.emit("alert_update", alert)
        return alert

    def add_whitelist(self, mac: str, label: str) -> None:
        mac = norm_mac(mac)
        self.db.execute("INSERT OR REPLACE INTO whitelist(mac, label, added_at) VALUES (?,?,?)",
                        (mac, label, time.time()))
        with self.lock:
            self.whitelist[mac] = label

    def remove_whitelist(self, mac: str) -> None:
        mac = norm_mac(mac)
        self.db.execute("DELETE FROM whitelist WHERE mac=?", (mac,))
        with self.lock:
            self.whitelist.pop(mac, None)

    def upsert_node(self, node_id: str, label: str, x: float, y: float, enabled: bool) -> None:
        self.db.execute(
            "INSERT INTO nodes(id, label, x, y, enabled) VALUES (?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET label=excluded.label, x=excluded.x, y=excluded.y, "
            "enabled=excluded.enabled", (node_id, label, x, y, int(enabled)))
        with self.lock:
            self.nodes[node_id] = self.db.one("SELECT * FROM nodes WHERE id=?", (node_id,))
        self.emit("nodes", self.node_list())

    def delete_node(self, node_id: str) -> None:
        self.db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        with self.lock:
            self.nodes.pop(node_id, None)
            for d in self.devices.values():
                d.links.pop(node_id, None)
        self.emit("nodes", self.node_list())

    def clear_data(self, session_id: int | None = None) -> None:
        with self.lock:
            self.db.clear_session_data(session_id)
            if session_id is None or session_id == self.session["id"]:
                self.devices.clear()
                self.alerted.clear()
                self.session = self.db.active_session() or self.db.start_session(
                    time.strftime("Exam %Y-%m-%d %H:%M"), self.config["room"]["name"])
        self.emit("snapshot", self.snapshot())

    # ------------------------------------------------------------ calibration
    def calibration_sample(self, node_id: str, mac: str, distance: float, seconds: float = 10) -> dict:
        """Average the raw RSSI of `mac` at `node_id` over the last `seconds` and store it."""
        mac = norm_mac(mac)
        rows = self.db.query(
            "SELECT rssi FROM readings WHERE node_id=? AND mac=? AND ts>=?",
            (node_id, mac, time.time() - seconds))
        if not rows:
            raise ValueError(f"No readings from {mac} at {node_id} in the last {seconds:.0f} s")
        mean = sum(r["rssi"] for r in rows) / len(rows)
        self.db.execute(
            "INSERT INTO calibration_points(created_at, node_id, mac, distance, mean_rssi, samples) "
            "VALUES (?,?,?,?,?,?)", (time.time(), node_id, mac, distance, mean, len(rows)))
        return {"node_id": node_id, "mac": mac, "distance": distance, "mean_rssi": mean, "samples": len(rows)}

    # ------------------------------------------------------------ views
    def device_list(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        out = []
        with self.lock:
            for dev in self.devices.values():
                links = {nid: {"raw": link.raw, "filtered": round(link.filtered, 1),
                               "distance": round(link.distance, 2), "age": round(now - link.last_ts, 1),
                               "band": proximity_band(link.filtered)}
                         for nid, link in dev.links.items()}
                out.append({
                    "mac": dev.mac, "name": dev.name, "addr_type": dev.addr_type,
                    "is_audio": dev.is_audio, "audio_reason": dev.audio_reason,
                    "first_seen": dev.first_seen, "last_seen": dev.last_seen,
                    "active": now - dev.last_seen <= self.settings["stale_s"],
                    "position": dev.position, "suspicious": dev.suspicious,
                    "whitelisted": dev.mac in self.whitelist,
                    "whitelist_label": self.whitelist.get(dev.mac),
                    "persistence": dev.persistence, "reasons": dev.reasons, "links": links,
                })
        out.sort(key=lambda d: (not d["suspicious"], not d["is_audio"],
                                (d["position"] or {}).get("nearest_distance", 99.0)))
        return out

    def device_history(self, mac: str) -> dict:
        mac = norm_mac(mac)
        with self.lock:
            dev = self.devices.get(mac)
            if dev:
                return {nid: list(link.history) for nid, link in dev.links.items()}
        rows = self.db.query(
            "SELECT ts, node_id, rssi, filtered FROM readings WHERE session_id=? AND mac=? "
            "ORDER BY ts DESC LIMIT 600", (self.session["id"], mac))
        hist: dict[str, list] = defaultdict(list)
        for r in reversed(rows):
            hist[r["node_id"]].append((r["ts"], r["rssi"], round(r["filtered"], 2)))
        return dict(hist)

    def node_list(self) -> list[dict]:
        with self.lock:
            return [dict(n) for n in sorted(self.nodes.values(), key=lambda n: n["id"])]

    def open_alerts(self) -> list[dict]:
        return self.db.query(
            "SELECT * FROM alerts WHERE session_id=? ORDER BY created_at DESC LIMIT 200",
            (self.session["id"],))

    def snapshot(self) -> dict:
        return {
            "room": self.config["room"],
            "session": self.session,
            "settings": self.settings,
            "nodes": self.node_list(),
            "devices": self.device_list(),
            "alerts": self.open_alerts(),
        }

    def heatmap(self, cell: float = 0.5, minutes: float = 30) -> dict:
        room = self.config["room"]
        cols = max(1, int(room["width"] / cell + 0.999))
        rows = max(1, int(room["height"] / cell + 0.999))
        grid = [[0] * cols for _ in range(rows)]
        pts = self.db.query(
            "SELECT p.x, p.y FROM positions p JOIN devices d ON d.session_id=p.session_id AND d.mac=p.mac "
            "WHERE p.session_id=? AND p.ts>=? AND d.mac NOT IN (SELECT mac FROM whitelist)",
            (self.session["id"], time.time() - minutes * 60))
        for p in pts:
            c = min(cols - 1, max(0, int(p["x"] / cell)))
            r = min(rows - 1, max(0, int(p["y"] / cell)))
            grid[r][c] += 1
        return {"cell": cell, "cols": cols, "rows": rows, "grid": grid}

    # ------------------------------------------------------------ loop
    def start(self, interval: float = 1.0) -> None:
        def run():
            last_purge = 0.0
            while not self._stop.wait(interval):
                try:
                    self.tick()
                    if time.time() - last_purge > 3600:
                        last_purge = time.time()
                        n = self.db.purge_older_than(self.settings["retention_days"])
                        if n:
                            log.info("Retention: purged %d old sessions", n)
                except Exception:  # keep the loop alive no matter what
                    log.exception("engine tick failed")

        self._thread = threading.Thread(target=run, name="engine-tick", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
