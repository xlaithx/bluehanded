# Step 0: Overview and roadmap

This folder turns the GP1 report (`docs/GP REPORT.pdf`) into a build plan. Each file is one step you take, in order. Every step says what you need, what to do, and how you know it worked.

## What we are building

```
 ESP32 node x3-6  ──BLE passive scan──►  JSON over MQTT (Wi-Fi)  ──►  Raspberry Pi 4
   node.cpp                                 Mosquitto broker            ├─ mqtt_ingest.py   receive scans
                                                                         ├─ engine.py        Kalman → distance → position → rules → alerts
                                                                         ├─ db.py            SQLite (readings, devices, alerts, whitelist)
                                                                         └─ web.py           Flask + Socket.IO dashboard
                                                                                    │
                                                              Proctor's browser ◄───┘  live map, alerts + sound, verify, export
```

| Report requirement | Where it is implemented |
|---|---|
| Passive BLE scanning, MAC + RSSI extraction (2, 4.2, 5.1.1) | `esp32-node/src/node.cpp` |
| RSSI threshold on the node (flow chart 6.2.1) | `node.cpp` `minRssi`, set from the dashboard |
| JSON over Mosquitto MQTT (5.1.3, Phase 2) | `node.cpp` + `server/bluehanded/mqtt_ingest.py` |
| 1D Kalman filter (4.4) | `server/bluehanded/rssi.py` `Kalman1D` |
| Log-distance path loss + calibration (4.3, objective 2) | `rssi.py` `PathLossModel`, `fit_path_loss`; Admin > Calibration |
| Weighted least squares multilateration (4.5, Phase 3) | `server/bluehanded/localization.py` (WLS + Gauss-Newton) |
| Suspicious device rules: proximity, audio profile, persistence, whitelist (4.6) | `engine.py` `tick()`, `profiles.py` |
| SQLite storage (5.2.3) | `server/bluehanded/db.py` |
| Flask + Flask-SocketIO dashboard, map, Chart.js graphs (5.2.2) | `web.py`, `templates/`, `static/js/` |
| Login, monitor, alert (visual + audible), device details, verification (6.1.1) | Dashboard + Alert log |
| Configure nodes, thresholds, export logs, clear data (6.1.2) | Admin page |
| Heatmap (Chapter 9, Yazan) | Dashboard "Heatmap" toggle |
| TLS, passwords, ACLs (7.2, Phase 5) | `server/deploy/`, Step 9 |
| Data retention / clearing (7.1) | Admin > Exam sessions, `retention_days` |

## The steps

| Step | File | Report phase | Owner (Chapter 9) |
|---|---|---|---|
| 1 | [Hardware and bench testing](01-hardware-and-bench-testing.md) | Phase 1, Jul 2026 | Yanal |
| 2 | [Raspberry Pi and MQTT broker](02-raspberry-pi-and-mqtt-broker.md) | Phase 1–2 | Rashida |
| 3 | [ESP32 node firmware](03-esp32-node-firmware.md) | Phase 2, Sep 2026 | Yanal |
| 4 | [Server and dashboard](04-server-and-dashboard.md) | Phase 3–4 | Rashida, Jawad |
| 5 | [Node placement and calibration](05-node-placement-and-calibration.md) | Phase 3, Nov 2026 | Yazan |
| 6 | [Localization and detection tuning](06-localization-and-detection.md) | Phase 3 | Yazan |
| 7 | [Running an exam](07-running-an-exam.md) | Phase 4, Dec 2026 | Jawad |
| 8 | [Field testing](08-field-testing.md) | Phase 5, Jan 2027 | all |
| 9 | [Security hardening](09-security-hardening.md) | Phase 5 | Rashida, Yanal |
| 10 | [Final report and jury demo](10-final-report-and-demo.md) | Phase 6, Feb 2027 | Jawad |

You can do Step 4 first with no hardware at all: `python -m bluehanded serve --simulate` runs the full system with four fake nodes and five fake devices.

## Repository layout

```
docs/steps/          these guides
esp32-node/          PlatformIO project
  src/node.cpp       final node firmware  (env: node)
  src/main.cpp       BLE scan test         (env: esp32dev)
  src/wifi_test.cpp  Wi-Fi test            (env: wifi_test)
  src/mqtt_test.cpp  MQTT test             (env: mqtt_test)
server/              Raspberry Pi application (Python)
  bluehanded/        the package (engine, web, db, ...)
  tests/             pytest suite
  deploy/            install script, systemd unit, Mosquitto config, TLS script
  config.example.toml
```

## MQTT message format (contract between firmware and server)

`blue-handed/scan/<node_id>`, one message per scan cycle (split into several if more than 20 devices):

```json
{"node": "node-1", "seq": 42, "uptime": 360,
 "devices": [
   {"mac": "d4:3a:2c:11:22:01", "rssi": -67, "max": -63, "n": 9, "addr_type": "random",
    "name": "Galaxy Buds2", "appearance": 2369, "uuids": ["0000184e-0000-1000-8000-00805f9b34fb"],
    "company_id": 117, "mfg_type": 1}
 ]}
```

`rssi` is the mean over the scan window. Only `mac` and `rssi` are required.

`blue-handed/status/<node_id>` (retained): `{"status":"online","ip":"192.168.1.21","wifi_rssi":-55,"uptime":360,"fw":"1.0.0"}`. The broker publishes `{"status":"offline"}` (last will) if the node disappears.

`blue-handed/config/all` (retained, server → nodes): `{"min_rssi": -90, "scan_seconds": 3}`.
