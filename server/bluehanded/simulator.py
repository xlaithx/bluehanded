"""Simulate ESP32 nodes and BLE devices so the whole system can run without hardware.

Each simulated node produces the same JSON scan batches as the real firmware,
using the path loss model plus Gaussian noise. Batches go either straight into
the engine (`serve --simulate`) or to an MQTT broker (`simulate` command), which
also exercises Mosquitto and the MQTT ingest path.
"""

from __future__ import annotations

import json
import math
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .rssi import PathLossModel

Sink = Callable[[str, dict], None]


@dataclass
class SimDevice:
    mac: str
    name: str | None
    x: float
    y: float
    uuids: list[str]
    appearance: int | None = None
    company_id: int | None = None
    mfg_type: int | None = None
    vx: float = 0.0  # m/s, for walking devices
    vy: float = 0.0
    tx_offset: float = 0.0  # dB: some devices transmit stronger/weaker
    on_after: float = 0.0  # seconds after start before the device turns on

    def step(self, dt: float, width: float, height: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
        if not -6 <= self.x <= width + 6:
            self.vx = -self.vx
        if not -6 <= self.y <= height + 6:
            self.vy = -self.vy


def default_scenario(width: float, height: float) -> list[SimDevice]:
    """A small exam: two hidden earbuds, a phone, an invigilator watch, a passer-by in the hallway."""
    return [
        SimDevice("d4:3a:2c:11:22:01", "Galaxy Buds2", width * 0.30, height * 0.40, ["0000184e-0000-1000-8000-00805f9b34fb"],
                  appearance=0x0941, on_after=5),
        SimDevice("6e:91:aa:10:00:02", None, width * 0.70, height * 0.65, [], company_id=0x004C, mfg_type=0x07,
                  on_after=20),
        SimDevice("f0:5c:77:aa:bb:03", "Redmi Note 12", width * 0.55, height * 0.25, [], on_after=12),
        SimDevice("c8:28:32:00:00:04", "Invigilator Watch", width * 0.50, height * 0.90, ["180d"],
                  appearance=0x00C1, vx=0.25),
        SimDevice("5a:12:9e:00:00:05", "Hallway Phone", -6.0, height * 0.2, [], vy=0.4),
    ]


def default_nodes(width: float, height: float) -> list[dict]:
    return [
        {"id": "node-1", "label": "Front left", "x": 0.0, "y": 0.0},
        {"id": "node-2", "label": "Front right", "x": width, "y": 0.0},
        {"id": "node-3", "label": "Back left", "x": 0.0, "y": height},
        {"id": "node-4", "label": "Back right", "x": width, "y": height},
    ]


class Simulator:
    def __init__(self, nodes: list[dict], devices: list[SimDevice], width: float, height: float,
                 model: PathLossModel | None = None, noise_db: float = 4.0, scan_seconds: float = 3.0,
                 min_rssi: int = -90, seed: int | None = None, wall_loss_db: float = 6.0):
        self.nodes = nodes
        self.devices = devices
        self.width, self.height = width, height
        self.model = model or PathLossModel()
        self.noise_db = noise_db
        self.scan_seconds = scan_seconds
        self.min_rssi = min_rssi
        self.wall_loss_db = wall_loss_db
        self.rng = random.Random(seed)
        self.seq = 0
        self.t0 = time.time()
        self._stop = threading.Event()

    def batch(self, node: dict, elapsed: float) -> dict:
        found = []
        for d in self.devices:
            if elapsed < d.on_after:
                continue
            dist = math.hypot(d.x - node["x"], d.y - node["y"])
            rssi = self.model.rssi(dist) + d.tx_offset + self.rng.gauss(0, self.noise_db)
            # A device outside the hall is behind a wall.
            if not (0 <= d.x <= self.width and 0 <= d.y <= self.height):
                rssi -= self.wall_loss_db
            # Occasional deep fade (multipath, a body in the way).
            if self.rng.random() < 0.05:
                rssi -= self.rng.uniform(8, 15)
            rssi = int(round(max(rssi, -100)))
            if rssi < self.min_rssi:
                continue
            item = {"mac": d.mac, "rssi": rssi, "addr_type": "random" if int(d.mac[:2], 16) & 0x40 else "public"}
            if d.name:
                item["name"] = d.name
            if d.uuids:
                item["uuids"] = d.uuids
            if d.appearance is not None:
                item["appearance"] = d.appearance
            if d.company_id is not None:
                item["company_id"] = d.company_id
                item["mfg_type"] = d.mfg_type
            found.append(item)
        return {"node": node["id"], "seq": self.seq, "uptime": int(elapsed), "devices": found}

    def step(self, sink: Sink, dt: float) -> None:
        elapsed = time.time() - self.t0
        for d in self.devices:
            d.step(dt, self.width, self.height)
        self.seq += 1
        for node in self.nodes:
            sink(node["id"], self.batch(node, elapsed))

    def run(self, sink: Sink, status_sink: Sink | None = None) -> None:
        for node in self.nodes:
            if status_sink:
                status_sink(node["id"], {"status": "online", "ip": "sim", "fw": "simulator", "uptime": 0})
        while not self._stop.is_set():
            self.step(sink, self.scan_seconds)
            self._stop.wait(self.scan_seconds)

    def start_thread(self, sink: Sink, status_sink: Sink | None = None) -> threading.Thread:
        t = threading.Thread(target=self.run, args=(sink, status_sink), name="simulator", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()


def run_over_mqtt(cfg: dict, room: dict, nodes: list[dict], scan_seconds: float = 3.0) -> None:
    """Publish simulated scans to the MQTT broker, exactly like real nodes."""
    import paho.mqtt.client as mqtt

    prefix = cfg["topic_prefix"].rstrip("/")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bluehanded-simulator")
    if cfg.get("username"):
        client.username_pw_set(cfg["username"], cfg.get("password") or None)
    if cfg.get("tls_ca"):
        client.tls_set(ca_certs=cfg["tls_ca"])
    client.connect(cfg["host"], int(cfg["port"]))
    client.loop_start()
    sim = Simulator(nodes, default_scenario(room["width"], room["height"]), room["width"], room["height"],
                    scan_seconds=scan_seconds)

    def pub(node_id, payload):
        client.publish(f"{prefix}/scan/{node_id}", json.dumps(payload))

    def status(node_id, payload):
        client.publish(f"{prefix}/status/{node_id}", json.dumps(payload), retain=True)

    print(f"Simulating {len(nodes)} nodes -> mqtt://{cfg['host']}:{cfg['port']} (Ctrl+C to stop)")
    try:
        sim.run(pub, status)
    except KeyboardInterrupt:
        pass
    finally:
        for node in nodes:
            client.publish(f"{prefix}/status/{node['id']}", json.dumps({"status": "offline"}), retain=True)
        client.loop_stop()
        client.disconnect()
