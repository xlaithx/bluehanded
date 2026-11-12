# Step 7: Running an exam (operator procedure)

**Goal:** a checklist that any proctor or admin can follow on exam day.
**Report:** use cases 6.1.1 (Proctor) and 6.1.2 (System Administrator), sequence diagram 6.3.

## Before the exam (admin, 20 minutes before)

1. Charge all node power banks the night before.
2. Power on the router, then the Raspberry Pi. Wait 1 minute.
3. Power on and mount the nodes at their marked positions.
4. Log in at `http://<pi-ip>:5000` as admin.
5. **Admin → Exam sessions → Start new session**, name it (course, hall, date). This separates the logs of each exam.
6. Dashboard → **Nodes** panel: every node **online**, "x s ago" under 10 s.
7. Admin → **Whitelist**: add the invigilators' devices if they must keep Bluetooth on. Easiest: ask invigilators to turn Bluetooth off.
8. Walk-test: put your own earbuds (out of the case) on a desk in the middle. Within ~15 s an alert must appear on the dashboard. Mark it **False alarm** with note "pre-exam test".

## During the exam (proctor)

1. Log in as proctor on a laptop or tablet at the invigilator desk. Click anywhere on the page once so the browser allows the alarm sound. Keep **Sound** ticked.
2. When an alert appears (red card, beep, flashing tab title):
   - read the reason and the approximate location; the red pulsing dot on the map shows where,
   - click **Details** for the RSSI per node and the live graph: the closest node with the strongest RSSI tells you which side of the room,
   - walk to that area and check physically (report 7.2: alerts are warnings, never automatic punishment).
3. Record the outcome:
   - **Confirmed cheating**: note the seat number / student and what was found,
   - **False alarm**: note whose device it was; tick "add to whitelist" if it belongs to staff.
4. The alert is closed on every open dashboard.

## After the exam (admin)

1. Admin → **Exam sessions** → **CSV** (or JSON) next to the session: the report with every alert, its time, MAC, location, verdict, verifier and notes, plus every device seen.
2. Hand the export to the exam committee.
3. When the review period is over, **Clear data** for that session (report 7.1: data retention). Ended sessions older than `retention_days` (default 7) are deleted automatically anyway.
4. Power off nodes and recharge.

## Roles

| Task | Proctor | Admin |
|---|---|---|
| Log in, watch dashboard, see alerts | ✓ | ✓ |
| View device details | ✓ | ✓ |
| Confirm / dismiss alerts | ✓ | ✓ |
| Start sessions, export, clear data | | ✓ |
| Configure nodes, thresholds, calibration, whitelist | | ✓ |
| Manage users | | ✓ |
