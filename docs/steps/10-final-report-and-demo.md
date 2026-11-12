# Step 10: Final report and jury demo

**Goal:** a GP2 report and a live demo that show every objective from the GP1 report working.
**Report:** Phase 6 (February 2027).

## 10.1 Final report outline

Reuse the GP1 chapters and add what was built and measured.

1. Abstract (update with results)
2. Introduction and objectives (unchanged; mark each objective as achieved with a pointer to the evidence)
3. Related work (unchanged)
4. Background (unchanged; add the actual Kalman Q/R and the fitted RSSI₀/n)
5. Hardware and software (update: Flask-SocketIO threading mode instead of eventlet; no GPIO used; ArduinoJson v7; huge_app partition)
6. **Implementation** (new)
   - System architecture diagram (Step 0)
   - MQTT topics and JSON format (Step 0)
   - Firmware flow (Step 3), compare with flow chart 6.2.1
   - Server modules, database schema, API (Step 4)
   - Localization and detection algorithms with equations (Step 6)
   - Dashboard screenshots: map with alerts, device detail graph, admin pages, export
7. **Calibration** (new): measurements and fitted curve (Step 5)
8. **Testing and results** (new): unit tests (`pytest`), simulator results, field tests T1–T6 with tables and plots (Step 8)
9. Professional constraints: how each was met (Step 9 table)
10. Limitations and future work: MAC randomisation, open-plan halls, fingerprinting / ML (from related work), ceiling-mounted nodes, PoE nodes, OTA updates
11. Roles (Chapter 9)
12. References

Plots worth including: distance vs. RSSI with the fit; raw vs. Kalman-filtered RSSI for a still device (screenshot of the device page); CDF of localization error; time-to-alert histogram.

## 10.2 Demo plan (10 minutes)

Setup before the jury enters: 4 nodes on stands at the corners of the demo area, Pi + router on the table, dashboard on a projector, a new session named "Jury demo".

| Time | What you do | What the jury sees |
|---|---|---|
| 0:00 | Explain the problem and architecture (1 slide) | |
| 1:00 | Show the dashboard: nodes online, empty map | Live system |
| 2:00 | A teammate sits at a "seat" and takes earbuds out of the case | Within ~15 s: beep, red alert card, red dot at the seat |
| 3:30 | Open Details | RSSI per node, raw vs. filtered graph, distance per node |
| 4:30 | Walk to the seat, "find" the earbuds, click **Confirmed cheating** with a note | Alert closes on screen |
| 5:30 | A teammate walks past outside the area with a phone | No alert (persistence and location) |
| 6:30 | Show an invigilator watch on the whitelist | Green dot, no alert |
| 7:00 | Admin: thresholds, calibration page, node config pushed over MQTT | |
| 8:00 | Export the CSV, open it | Full log with verdicts |
| 8:30 | Clear the session data | Privacy constraint |
| 9:00 | Questions | |

Backup plan: if the RF environment of the room misbehaves, run `python -m bluehanded serve --simulate` on a laptop to show the full workflow, and show the recorded field-test results.

## 10.3 Before the defence

- [ ] Fresh calibration in the demo room the day before
- [ ] All power banks charged, spare ESP32 flashed with each node id
- [ ] `git tag v1.0` on the final code
- [ ] Screenshots and exported CSVs from the field tests in `docs/`
- [ ] Slides and report submitted
