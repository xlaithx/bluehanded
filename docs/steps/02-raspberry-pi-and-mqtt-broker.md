# Step 2: Raspberry Pi server and MQTT broker

**Goal:** the Pi runs Mosquitto (with passwords) and the Blue-Handed server as a service.
**Report:** Phase 1–2, sections 5.1.3, 5.2.7.

## 2.1 Get the code on the Pi

```bash
sudo apt install -y git
git clone https://github.com/jawad-sakher99/bluehanded.git
cd bluehanded/server
```

## 2.2 Run the installer

```bash
./deploy/install_pi.sh
```

It does five things (you can read the script; it is short):

1. Installs `python3-venv`, `mosquitto`, `mosquitto-clients`, `sqlite3`, `openssl`.
2. Creates a Python virtual environment in `server/.venv` and installs `requirements.txt` (Flask, Flask-SocketIO, paho-mqtt, NumPy).
3. Creates `config.toml` from `config.example.toml` with a random `secret_key`.
4. Installs the Mosquitto config from `deploy/` and asks you for two passwords:
   - `bluehanded-server`: used by the Python server
   - `bluehanded-node`: shared by all ESP32 nodes
   It also removes the old open test config (`allow_anonymous true`) from the README.
5. Installs and enables the `bluehanded` systemd service.

Write both passwords down somewhere safe; you need them in 2.3 and Step 3.

## 2.3 Edit config.toml

```bash
nano config.toml
```

- `[mqtt] password` = the `bluehanded-server` password.
- `[room] width / height` = your hall size in metres. `x` goes left → right when you stand at the front facing the students, `y` goes front → back.
- `[[nodes]]`: you can leave the four corners for now and fix the positions in Step 5 from the dashboard.

## 2.4 Check the broker

In one SSH window:

```bash
mosquitto_sub -h localhost -u bluehanded-server -P '<server password>' -t 'blue-handed/#' -v
```

In another:

```bash
mosquitto_pub -h localhost -u bluehanded-node -P '<node password>' -t blue-handed/status/test -m '{"status":"online"}'
```

The first window must print the message. Also check that a wrong password is refused:

```bash
mosquitto_pub -h localhost -t blue-handed/status/test -m hi   # must fail: not authorised
```

## 2.5 Create the first account and start the service

```bash
.venv/bin/python -m bluehanded -c config.toml create-user admin --role admin
.venv/bin/python -m bluehanded -c config.toml create-user proctor1 --role proctor
sudo systemctl start bluehanded
journalctl -u bluehanded -f        # Ctrl+C to stop watching
```

You should see `MQTT connected` and `Dashboard on http://0.0.0.0:5000`.

Open `http://<pi-ip>:5000` from a laptop on the same network and log in.

## 2.6 Test the whole server path without ESP32s

The simulator publishes fake scans to the broker exactly like real nodes:

```bash
# The ACL only lets the node account publish scans, so the simulator logs in as a node.
.venv/bin/python -m bluehanded -c config.toml simulate --mqtt-user bluehanded-node
```

It asks for the node password, then publishes for the nodes listed in `config.toml`. Stop it with Ctrl+C.

Within about 15 seconds the dashboard shows four nodes online, devices on the map and alerts.

## Useful commands

| Task | Command |
|---|---|
| Restart server | `sudo systemctl restart bluehanded` |
| Server logs | `journalctl -u bluehanded -f` |
| Broker logs | `journalctl -u mosquitto -f` |
| Watch all MQTT traffic | `mosquitto_sub -h localhost -u bluehanded-server -P '...' -t 'blue-handed/#' -v` |
| Update code | `cd ~/bluehanded && git pull && sudo systemctl restart bluehanded` |
| Open the database | `sqlite3 server/bluehanded.db` |

## Done when

- Mosquitto refuses connections without a password and accepts both accounts.
- `systemctl status bluehanded` is `active (running)` and survives a reboot.
- The simulator shows devices and alerts on the dashboard.
