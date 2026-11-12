# Step 3: ESP32 node firmware

**Goal:** every ESP32 runs the final firmware, connects to the Pi and shows up online on the dashboard.
**Report:** Phase 2 (September 2026), flow chart 6.2.1 ESP32, sections 4.2, 5.2.5.

## What the firmware does

`esp32-node/src/node.cpp`, PlatformIO environment **`node`**:

1. Starts the BLE stack in **passive** mode (it never transmits scan requests, it only listens to advertisements on channels 37/38/39).
2. Connects to Wi-Fi and to Mosquitto with the node account. It registers a "last will" so the server knows when a node dies.
3. Loop:
   - Scans for `scan_seconds` (default 3 s). Every advertisement with RSSI ≥ `min_rssi` is collected per MAC: mean and max RSSI, packet count, name, address type, appearance, service UUIDs, manufacturer id.
   - Publishes the batch as JSON to `blue-handed/scan/<NODE_ID>` (20 devices per message).
   - Every 10 s publishes a heartbeat to `blue-handed/status/<NODE_ID>`.
4. Listens to `blue-handed/config/all` and `blue-handed/config/<NODE_ID>`. When an admin changes the threshold or scan time in the dashboard, all nodes update and save it in flash.

BLE and Wi-Fi together are too big for the default partition, so the `node` environment uses `huge_app.csv` (3 MB app, no over-the-air updates).

## 3.1 Configure secrets.h

```
esp32-node/include/secrets.example.h  →  copy to  →  esp32-node/include/secrets.h
```

Set:

| Define | Value |
|---|---|
| `WIFI_SSID`, `WIFI_PASSWORD` | the exam network (2.4 GHz) |
| `MQTT_HOST` | the Pi's fixed IP from Step 1.3 |
| `MQTT_PORT` | `1883` (8883 after Step 9) |
| `NODE_ID` | `node-1`, `node-2`, ... **different for every board**, matching the board label |
| `MQTT_USER`, `MQTT_PASSWORD` | `bluehanded-node` and its password from Step 2.2 |

`secrets.h` is in `.gitignore`. Never commit it.

## 3.2 Flash each board

For each board:

1. Set `NODE_ID` in `secrets.h` to that board's number.
2. In VS Code / PlatformIO: Project Tasks → **node** → General → **Upload** (hold BOOT if it hangs on `Connecting...`, see README).
3. **Monitor** (115200 baud). Expected:

```
=== Blue-Handed node node-1 (fw 1.0.0) ===
Connecting to Wi-Fi....
Wi-Fi connected, IP 192.168.1.21, RSSI -48 dBm
Connecting to MQTT... connected
Scan #1: 7 devices >= -90 dBm
Scan #2: 8 devices >= -90 dBm
```

4. On the dashboard (Nodes panel) the node appears **online**. If you used an id that is not in `config.toml`, it appears as a new node, disabled, at (0, 0): place it in Admin > Nodes (Step 5).

Command-line alternative: `cd esp32-node && pio run -e node -t upload && pio device monitor`.

## 3.3 Check the data

On the Pi:

```bash
mosquitto_sub -h localhost -u bluehanded-server -P '...' -t 'blue-handed/scan/#' -v
```

You should see one JSON message per node every ~3 seconds.

## 3.4 Robustness checks

| Test | Expected |
|---|---|
| Unplug the router for 30 s, plug back | Node prints reconnect, comes back online by itself |
| Stop Mosquitto (`sudo systemctl stop mosquitto`) and start it again | Node retries every 2 s and reconnects |
| Power off a node | Dashboard shows it offline within ~30 s (last will) |
| Change "Node minimum RSSI" to -80 in Admin > Thresholds | Serial monitor prints `Config updated: min_rssi=-80` |
| 30+ BLE devices nearby | Several scan messages per cycle, no crash; `free_heap` in the status stays stable |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Sketch too big` / partition error | You built `esp32dev` instead of `node`. The `node` env sets `huge_app.csv` |
| `Connecting to MQTT... failed, rc=5` | Wrong MQTT user/password (rc=5 means not authorised) |
| `rc=-2` | Wrong `MQTT_HOST`, Pi not reachable, or firewall |
| Wi-Fi timeout, board restarts | 5 GHz network or wrong password |
| Node online but no devices | `min_rssi` too high, or nothing advertising nearby |

## Done when

All boards are flashed with unique ids, show online on the dashboard, and survive the robustness checks.
