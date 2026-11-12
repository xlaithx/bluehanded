# Step 1: Hardware and bench testing

**Goal:** every board works on its own before anything is connected together.
**Report:** Phase 1 (July 2026), sections 5.1.1, 5.1.2, 5.1.4.

## Shopping list

| Item | Qty | Notes |
|---|---|---|
| ESP32 DevKit (WROOM-32, "ESP32 Dev Module") | 4 (+1 spare) | 4 is the minimum for good trilateration in a rectangular hall; the report allows 3–6 |
| USB data cables (micro-USB or USB-C, match your boards) | 5 | charge-only cables will not flash |
| Power banks, 5 V, 5000 mAh or more | 4 | pick ones that do not auto-switch-off at low current (or use "always on" mode) |
| Raspberry Pi 4 Model B, 4 GB | 1 | |
| Official Pi USB-C power supply 5 V / 3 A | 1 | |
| microSD card, 32 GB, class A1 | 1 | |
| Wi-Fi router (2.4 GHz) | 1 | a dedicated router for the system; the ESP32 has no 5 GHz |
| Test BLE devices: a pair of BLE earbuds, a smartwatch, phones | several | for calibration and testing |
| Tape measure (10 m), masking tape, labels | 1 | node positions and calibration distances |
| Optional: USB power meter | 1 | measure node current draw |

## 1.1 Check each ESP32

Do this for every board. Label each one with a number (1, 2, 3, ...) right away.

1. Follow the README "Running the test code" section with the `esp32dev` environment.
2. With a phone nearby, the Serial Monitor must show lines like `MAC: ... | RSSI: -62 dBm`.
3. Run `wifi_test`, then `mqtt_test` (README) to confirm Wi-Fi works on that board.

Write the results in a table:

| Board | BLE scan OK | Wi-Fi OK | MQTT OK | Notes |
|---|---|---|---|---|
| 1 | | | | |

## 1.2 Measure power and battery life

A node runs BLE scanning and Wi-Fi all the time (roughly 100–150 mA at 5 V).

1. Flash the final firmware (Step 3) on one board.
2. Put a USB power meter between the power bank and the board, or measure on the bench supply. Note the average current.
3. Battery life ≈ (bank capacity in mAh × 0.8 × 3.7 V / 5 V) / current in mA. A 5000 mAh bank at 130 mA gives about 22 h, much more than an exam.
4. Run a real test: full charge, run until it dies, note the time. Also note whether the power bank cuts off on its own at low current. If it does, use a different model.

## 1.3 Prepare the Raspberry Pi

1. Flash **Raspberry Pi OS (64-bit) Lite** with Raspberry Pi Imager. In the Imager settings set hostname `bluehanded`, a username and password, your Wi-Fi (or use Ethernet) and enable SSH.
2. Boot, then from your laptop: `ssh <user>@bluehanded.local`.
3. `sudo apt update && sudo apt full-upgrade -y && sudo reboot`.
4. Give the Pi a fixed IP address: the easiest way is a DHCP reservation in the router settings (bind the Pi's MAC address to e.g. `192.168.1.10`). Every ESP32 will use this address.

## Done when

- Every ESP32 passes the three tests and is labelled.
- You know each node's current draw and battery life.
- The Pi boots, you can SSH into it, and it always gets the same IP address.
