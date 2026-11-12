# Step 5: Node placement and calibration

**Goal:** nodes are at known positions in the real hall and the path loss model matches that room.
**Report:** Phase 3 (November 2026), objective "Environment Calibration", section 4.3.

## 5.1 Measure the hall and pick the coordinate system

1. Stand at the front of the hall (whiteboard / invigilator desk), facing the students.
2. The **front-left corner** is (0, 0). `x` grows to the right, `y` grows towards the back.
3. Measure width (x) and depth (y) in metres. Put them in `config.toml` `[room]` and restart the service.

## 5.2 Place the nodes

Rules of thumb:

- **Use at least 4 nodes** for a rectangular hall. With 3, positions near the edges are poor.
- Spread them around the **perimeter**: the four corners, then add mid-wall nodes for halls longer than ~12 m.
- Mount them at the **same height**, about 1–1.5 m (desk height to shoulder height), on walls or pillars, out of students' reach (report 7.2 "Physical Security").
- Keep them **away from metal** (radiators, cabinets) and not directly on concrete pillars if possible.
- Every point where a student sits should be within ~6 m of at least three nodes.
- Note each node's exact position with the tape measure.

In the dashboard: **Admin → Nodes**, enter x and y for each node id, tick **Enabled**, Save. The map updates at once.

Example for a 15 × 10 m hall with 6 nodes:

| Node | x | y |
|---|---|---|
| node-1 | 0 | 0 |
| node-2 | 7.5 | 0 |
| node-3 | 15 | 0 |
| node-4 | 0 | 10 |
| node-5 | 7.5 | 10 |
| node-6 | 15 | 10 |

## 5.3 Calibrate RSSI₀ and n

The model is `RSSI = RSSI₀ − 10·n·log10(d)`. Defaults (−60 dBm, n = 2.5) are a guess; calibration replaces them with values for this room.

You need: one node, a test device (use the type you most want to catch: a BLE earbud; a phone works too), the tape measure, and the device's MAC (read it from the dashboard device table; turn the device on and off to see which row it is).

Note: many earbuds only advertise when they are out of the case and **not** connected to a phone. Disconnect them from the phone, or use the phone itself.

1. Admin → **Path loss calibration**.
2. Hold the device at **1 m** from the node, at the node's height, with a clear line of sight. Wait 20 s.
3. Choose the node, paste the MAC, type `1`, keep `15` seconds, click **Record point**. The table shows the mean RSSI and the number of samples (you want 10+ samples).
4. Repeat at **2, 3, 4, 6, 8 m** (and further if the hall is big).
5. Repeat the whole series on a second node in a different part of the room if you have time. More points from different places give a better average.
6. Click **Fit model**. The new RSSI at 1 m and n are saved and used immediately. A realistic n indoors is 2 to 4; the dashboard refuses values outside 1–6.

Offline alternative (for your report): record pairs by hand and run

```bash
python -m bluehanded fit-pathloss 1:-58 2:-66 3:-70 4:-73 6:-78 8:-81
```

## 5.4 What to put in the report

Make a table and a plot of distance vs. mean RSSI with the fitted curve, for:

- empty hall,
- hall with people sitting (body attenuation is large, often 5–10 dB),
- device in a pocket vs. in the open.

This is exactly the "characterize the RF propagation environment" objective. If the full-hall fit and the empty-hall fit differ a lot, use the full-hall values during exams.

## 5.5 Tune the Kalman filter (optional)

- `Kalman R` (measurement noise): roughly the variance of raw RSSI for a still device. Look at the device chart: if raw points scatter about ±3 dB, R ≈ 9.
- `Kalman Q` (process noise): how quickly the true value may change. 0.5 follows a walking person in a few seconds; 0.05 is very smooth but slow.

## Done when

All nodes are placed and enabled with measured positions, and the fitted model gives a position error you can live with: put a device at 3–4 known spots and compare the dashboard position with reality (aim for under 2 m).
