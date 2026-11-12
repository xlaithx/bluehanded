# Step 8: Field testing

**Goal:** measure how well the system works in a real hall, with numbers for the final report.
**Report:** Phase 5 (January 2027), "full field tests simulating an examination hall".

Run every test in the real exam hall, ideally with volunteers sitting in the seats. Start a new session for each test (Admin → Exam sessions) so the exports are separate, and export the CSV after each one.

## Test devices

At least: 2 pairs of BLE earbuds (different brands, e.g. Galaxy Buds / AirPods / cheap TWS), 1 smartwatch, 2 phones, 1 BLE "mini earpiece" if you can get one.

## T1. Localization accuracy

1. Mark 10 seat positions on the floor plan with known (x, y).
2. Put a test device on each spot for 60 s.
3. From the export (`devices` / `positions` table) or the device page, take the mean estimated position.
4. Error = distance between true and estimated position.

| Spot | True (x, y) | Estimated (x, y) | Error (m) | Nodes heard |
|---|---|---|---|---|

Report mean, median and max error. Repeat empty vs. full hall.

## T2. Detection rate (true positives)

Place an earbud at 10 seats, one at a time, in a pocket or a pencil case, for 2 minutes each.

| Seat | Device | Alerted? | Time to alert (s) | Severity |
|---|---|---|---|---|

Detection rate = alerted / total. Time to alert = alert time − time the device was turned on.

## T3. False alarms

1. Corridor: a person with a phone and earbuds walks along the corridor for 5 minutes, then stands at the door for 2 minutes.
2. Neighbouring room: devices on the other side of a wall for 10 minutes.
3. Invigilator: whitelisted watch walking around for 10 minutes.

Count alerts in each case. Target: zero. If not zero, apply the tuning table in Step 6.5 and repeat.

## T4. MAC randomisation

Use a phone (iOS or Android) for 30 minutes at one seat. Count how many different MACs appear for it in the device list and whether each one alerted at the same location.

## T5. Reliability

| Test | Expected |
|---|---|
| Run 3 hours continuously (a long exam) | No crash; `journalctl -u bluehanded` clean; all nodes online |
| Reboot the Pi during a session | Service and nodes come back by themselves, session continues |
| Turn one node off | Dashboard shows it offline; positions still computed from the others |
| Battery life of a node | Measure time until it dies |
| 2–3 dashboards open at once | All update live; a verification on one shows on the others |

## T6. Latency

Turn earbuds on at a known time (stopwatch) and note when the alert appears. Expected about `persistence_cycles × scan_seconds` + a few seconds (≈ 10–15 s with defaults). Compare with the report's goal "reported within seconds" (4.7).

## Results summary for the final report

| Metric | Value |
|---|---|
| Median localization error (full hall) | |
| Detection rate (earbuds) | |
| False alarms per hour | |
| Mean time to alert | |
| Node battery life | |
| Final calibrated RSSI₀ / n | |
