# Blue-Handed

Detection and Localization of Unauthorized Wireless Devices.

## About

Blue-Handed is an anti-cheat system for exam halls. ESP32 nodes passively scan Bluetooth Low Energy (BLE) signals, and a Raspberry Pi estimates the location of suspicious devices and alerts the proctor on a web dashboard.

## Team

- Yanal Al-Qudah
- Rashida Khraise
- Yazan Nayfeh
- Jawad Bani Amer

## Structure

- `docs/`: project report and documents
  - `docs/steps/`: **step-by-step build guide**, start with [Step 0: Overview](docs/steps/00-overview.md)
- `esp32-node/`: ESP32 firmware (PlatformIO project, Arduino framework)
  - `src/node.cpp`: final scanning node firmware (env `node`)
  - `src/main.cpp`, `src/wifi_test.cpp`, `src/mqtt_test.cpp`: bench test programs
- `server/`: Raspberry Pi application (Python): MQTT ingest, Kalman filter, multilateration, detection rules, SQLite, Flask + Socket.IO dashboard

## Quick start (no hardware needed)

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m bluehanded create-user admin --role admin
python -m bluehanded serve --simulate      # open http://localhost:5000
python -m pytest                           # run the tests
```

`--simulate` runs four fake nodes and five fake devices (hidden earbuds, a phone, an invigilator's watch, a phone in the corridor) so you can see alerts, the live map and the admin pages.

## The build guide

| Step | Guide |
|---|---|
| 0 | [Overview, architecture, MQTT format](docs/steps/00-overview.md) |
| 1 | [Hardware and bench testing](docs/steps/01-hardware-and-bench-testing.md) |
| 2 | [Raspberry Pi and MQTT broker](docs/steps/02-raspberry-pi-and-mqtt-broker.md) |
| 3 | [ESP32 node firmware](docs/steps/03-esp32-node-firmware.md) |
| 4 | [Server and dashboard](docs/steps/04-server-and-dashboard.md) |
| 5 | [Node placement and calibration](docs/steps/05-node-placement-and-calibration.md) |
| 6 | [Localization and detection](docs/steps/06-localization-and-detection.md) |
| 7 | [Running an exam](docs/steps/07-running-an-exam.md) |
| 8 | [Field testing](docs/steps/08-field-testing.md) |
| 9 | [Security hardening](docs/steps/09-security-hardening.md) |
| 10 | [Final report and jury demo](docs/steps/10-final-report-and-demo.md) |

## Bench test programs

The sections below describe the original test programs used to check each board (Step 1). The final firmware is `src/node.cpp` (environment `node`, see Step 3).

## Running the test code

Requirements:
- An ESP32 board (ESP32 Dev Module / WROOM-32) and a USB data cable
- Visual Studio Code with the **PlatformIO IDE** extension
- Git

Steps:
1. Clone the repository and open the **`esp32-node`** folder in VS Code (File > Open Folder...). Open this subfolder, not the repository root, because PlatformIO needs the folder that contains `platformio.ini` to show Project Tasks (Build / Upload / Monitor).
2. Wait for PlatformIO to finish setting up (the first time it downloads the ESP32 tools and takes a few minutes).
3. Connect the ESP32 to the computer with the USB cable.
4. Click **Build** to check that the code compiles (PlatformIO icon > Project Tasks > esp32dev > General > Build).
5. Click **Upload** to flash the board. If it hangs on `Connecting......`, see the next section.
6. Click **Monitor** to open the Serial Monitor (115200 baud).

Expected output (the scan repeats about every 7 seconds: 5 seconds of scanning plus a short pause):

```
Scanning...
MAC: aa:bb:cc:dd:ee:ff | Name: (no name) | RSSI: -62 dBm | ~2.1 m
Scan done. Devices seen: 1
```

Notes:
- Keep a Bluetooth device nearby (phone or smartwatch with Bluetooth on), otherwise nothing is listed.
- BLE devices do not have an IP address. The test prints MAC, name (if advertised), RSSI and an approximate distance.
- The distance uses the log-distance path loss model with `RSSI_AT_1M = -60` (measured at 1 m with a phone) and `PATH_LOSS_N = 2.5` (default, not calibrated yet). It is approximate and needs calibration in the real environment. Signals weaker than `MIN_RSSI = -90` dBm are ignored.
- Many modern phones randomize their MAC address, so the same device may appear with different addresses.
- The BLE library uses about 90% of the default flash. If we add Wi-Fi and MQTT, we will need a bigger partition table.

## Uploading code to the ESP32

If the upload hangs on `Connecting......`, the board is not in download mode. Do this:

1. Click Upload (the arrow icon in PlatformIO's bottom status bar, or the right-arrow button in Arduino IDE).
2. When `Connecting......` appears, press and hold the `BOOT` button on the ESP32.
3. While holding `BOOT`, press and release the `EN` (reset) button.
4. Release `BOOT` once the upload starts (you will see `Writing at 0x...`).

Notes:
- Use a USB cable that supports data, not a charge-only cable.
- If no COM port appears when the board is connected, install the USB-to-serial driver for your board (CP210x or CH340, depending on the board).
- Close the Serial Monitor before uploading, because it can block the port.
## Wi-Fi test

The project has these PlatformIO environments (plus `node`, the final firmware, see Step 3):
- `esp32dev` (default): the BLE scanner test (`src/main.cpp`). It does not need Wi-Fi settings.
- `wifi_test`: connects the ESP32 to Wi-Fi and prints its IP address (`src/wifi_test.cpp`).

To run `wifi_test`:
1. Copy `esp32-node/include/secrets.example.h` to `esp32-node/include/secrets.h`.
2. Put your own network name and password in `secrets.h`. The network must be 2.4 GHz (ESP32 does not support 5 GHz).
3. In PlatformIO Project Tasks, choose **wifi_test** > General > Build / Upload / Monitor (not `esp32dev`).

Expected output:

=== WiFi Test ===
Connecting.......
WiFi: CONNECTED
IP address: 192.168.x.x


Never commit `secrets.h`: it contains your Wi-Fi password and is ignored by Git.

## Wi-Fi and MQTT tests

The test environments are:
- `esp32dev` (default): BLE scanner test (`src/main.cpp`). It does not need Wi-Fi settings.
- `wifi_test`: connects the ESP32 to Wi-Fi and prints its IP address (`src/wifi_test.cpp`).
- `mqtt_test`: connects to Wi-Fi, then to an MQTT broker, and publishes a message every 2 seconds (`src/mqtt_test.cpp`).

Setup (needed for `wifi_test` and `mqtt_test`):
1. Copy `esp32-node/include/secrets.example.h` to `esp32-node/include/secrets.h`.
2. Edit `secrets.h`: your Wi-Fi name and password (2.4 GHz only, the ESP32 does not support 5 GHz) and `MQTT_HOST` (the IP address of the Raspberry Pi).
3. In PlatformIO Project Tasks, choose the environment (`wifi_test` or `mqtt_test`) > General > Build / Upload / Monitor.

Never commit `secrets.h`: it contains your Wi-Fi password and is ignored by Git.

Raspberry Pi side (MQTT broker, needed for `mqtt_test`):
1. Install Mosquitto: `sudo apt update && sudo apt install -y mosquitto mosquitto-clients`
2. Allow connections from the network: create `/etc/mosquitto/conf.d/blue-handed.conf` with the two lines `listener 1883` and `allow_anonymous true`, then run `sudo systemctl restart mosquitto`.
3. Watch the messages: `mosquitto_sub -h <pi-ip> -t blue-handed/test`

Expected output of `mqtt_test` in the Serial Monitor:

```
WiFi connected, IP: 192.168.1.xx
Connecting to MQTT... connected
Published: hello from esp32 #0
```

Note: `allow_anonymous true` lets any device on the network connect. It is only for testing on a private network. The final system should use a username/password and TLS.
