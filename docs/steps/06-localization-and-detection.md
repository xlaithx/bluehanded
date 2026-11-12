# Step 6: Localization and detection (how it works and how to tune it)

**Goal:** know exactly how a reading becomes an alert, so you can tune it and explain it to the jury.
**Report:** sections 4.3–4.6, Phase 3.

## 6.1 From packet to distance

For every (device, node) pair:

1. The node averages all packets of the device during one scan window and sends the mean RSSI.
2. The server runs a 1D Kalman filter (A = H = 1):
   ```
   predict:  P = P + Q
   gain:     K = P / (P + R)
   update:   x = x + K (z − x);   P = (1 − K) P
   ```
3. Distance `d = 10^((RSSI₀ − x) / (10 n))`.

## 6.2 From distances to a position (`localization.py`)

Nodes that heard the device in the last `stale_s` seconds are the anchors. Readings within 3 dB of the nodes' minimum RSSI are dropped when better ones exist, because near the sensitivity floor only the "lucky" strong packets get through and the distance is underestimated.

| Anchors | Method |
|---|---|
| 3 or more | Linearised **weighted least squares** (subtract the last circle equation from the others, weight `1/d²` so close, reliable nodes count more), then **Gauss-Newton** refinement of `Σ wᵢ (‖p − nodeᵢ‖ − dᵢ)²` (the Taylor-series method in the report's related work) |
| 2 | Point on the line between the two nodes, closer to the stronger one |
| 1 | The node's position, with the distance as the uncertainty |

The uncertainty circle on the map is the RMS of the range residuals (at least 0.5 m). The position is then smoothed over time (`POSITION_ALPHA = 0.3`) so one bad fix does not jump the dot across the room.

## 6.3 The rules (`engine.py`, report 4.6)

A device is **suspicious** when all of these hold:

| Rule | Setting | Meaning |
|---|---|---|
| Near | `proximity_m` (3 m) **or** `inside_margin_m` (0.5 m) | Nearest node estimates it within 3 m, **or** with 3+ nodes it is located at least 0.5 m inside the walls. Must hold in 60% of the last 10 seconds |
| Persistent | `persistence_cycles` (3) in `persistence_window_s` (30 s) | Seen in at least 3 different scan cycles in the last 30 s: not someone walking past |
| Not whitelisted | Admin → Whitelist | Invigilators' devices |
| Profile | `audio_only` (off) | When on, only audio devices alert. When off, every device alerts and audio ones are marked **high** severity |

Audio profile (`profiles.py`): any of
- service UUID for A2DP, Headset, Hands-free, AVRCP, or LE Audio (ASCS, PACS, BASS, VCS, ...),
- GAP appearance category "Wearable audio device" (earbud, headset, headphones) or "Audio sink",
- Apple "proximity pairing" manufacturer data (AirPods, Beats),
- name like *buds, pods, earphone, headset, JBL, Beats, Soundcore, QCY, WF-/WH-...*.

Hearing aids (appearance 0x0A40) are explicitly **not** treated as audio cheating devices (report 7.3).

One alert per device per session. After a proctor marks it, it does not alert again in that session.

## 6.4 MAC randomisation

Phones and many earbuds change their MAC every ~15 minutes. Effects and how the system copes:

- A new MAC is a "new device": it needs 3 scan cycles (~9 s) to become persistent again, then it alerts again. The proctor sees a second alert at the same location, which is actually useful.
- Because the rules use **location and persistence**, not identity, detection still works (report 4.2).
- Whitelisting does not survive randomisation. For invigilators, prefer devices with a fixed address, or turn Bluetooth off on their phones.

## 6.5 Tuning guide

| Problem in the field | Try |
|---|---|
| Devices in the corridor alert | Raise `inside_margin_m` (1.0–1.5), lower `proximity_m`, raise node minimum RSSI (−85), add nodes near that wall, re-calibrate with people in the room |
| Hidden earbuds in the middle of the hall do not alert | Lower node minimum RSSI (−95), add a node in the middle (ceiling), check calibration, raise `proximity_m` |
| Alert too slow | Lower `scan_seconds` to 2, `persistence_cycles` to 2, raise Kalman Q |
| Dots jump around | Raise Kalman R, add nodes |
| Too many alerts from students' phones in bags | Enable `audio_only` |

## 6.6 Known limitation (be honest in the report)

Simulation shows the geometry matters: with only four corner nodes and **no wall between the hall and the corridor** (open area), a device 4–6 m outside the hall is sometimes placed inside it. With a normal wall (about 6 dB loss) the false-alarm rate in the simulation drops to zero. The field test (Step 8) must measure this in the real hall.
