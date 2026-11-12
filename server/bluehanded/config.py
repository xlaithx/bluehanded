"""Load server configuration from a TOML file (see config.example.toml)."""

from __future__ import annotations

import copy
import os
import secrets
import tomllib
from pathlib import Path

DEFAULTS: dict = {
    "database": {"path": "bluehanded.db"},
    "mqtt": {
        "enabled": True,
        "host": "localhost",
        "port": 1883,
        "username": "",
        "password": "",
        "tls_ca": "",  # path to CA certificate; enables TLS when set
        "topic_prefix": "blue-handed",
        "client_id": "bluehanded-server",
    },
    "web": {"host": "0.0.0.0", "port": 5000, "secret_key": ""},
    "room": {"name": "Exam Hall", "width": 12.0, "height": 8.0},
    # Defaults for runtime settings. Admins can change these from the dashboard;
    # the changed values are stored in the database and win over these.
    "settings": {
        "rssi_at_1m": -60.0,
        "path_loss_n": 2.5,
        "kalman_q": 0.5,
        "kalman_r": 8.0,
        "node_min_rssi": -90,  # nodes drop weaker packets before sending
        "scan_seconds": 3,
        "proximity_m": 3.0,  # "near" if within this many metres of a node...
        "inside_margin_m": 0.5,  # ...or located at least this far inside the walls (3+ nodes)
        "persistence_cycles": 3,  # seen in at least this many scan cycles...
        "persistence_window_s": 30,  # ...within this window
        "stale_s": 15,  # readings older than this are ignored for positioning
        "audio_only": False,  # True: only alert for audio-profile devices
        "retention_days": 7,
    },
    "nodes": [],  # optional initial nodes: [{id, label, x, y}]
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | os.PathLike | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    path = path or os.environ.get("BLUEHANDED_CONFIG")
    if path and Path(path).exists():
        with open(path, "rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
    if not cfg["web"]["secret_key"]:
        cfg["web"]["secret_key"] = os.environ.get("BLUEHANDED_SECRET") or secrets.token_hex(32)
    return cfg
