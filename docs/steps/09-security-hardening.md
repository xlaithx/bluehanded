# Step 9: Security hardening

**Goal:** the deployed system meets the security and privacy constraints of Chapter 7.
**Report:** Phase 5 (January 2027), sections 7.1 and 7.2.

## Already in place after Steps 2–4

| Constraint | How |
|---|---|
| Only authorised clients on MQTT | `allow_anonymous false`, password file, two accounts (server, nodes) |
| A student cannot inject fake scans as the server, nor read the scans | ACL (`deploy/mosquitto-bluehanded.acl`): only `bluehanded-node` can write `scan/#`, only `bluehanded-server` can read it |
| Dashboard login | Hashed passwords (Werkzeug PBKDF2), two roles, admin-only configuration |
| CSRF | Every POST needs the per-session token |
| Socket.IO only for logged-in users | Connection is refused otherwise |
| Data minimisation (7.1) | Only MAC, name, RSSI and advertisement hints are stored. No connection, no payload, no audio |
| Retention (7.1) | Per-session clear, "clear all", automatic purge after `retention_days` |
| Anti-spoofing (7.2) | Alerts are warnings that a proctor must confirm physically |

## 9.1 MQTT over TLS

On the Pi:

```bash
cd ~/bluehanded/server
sudo ./deploy/make_certs.sh <pi-ip-address>
sudo nano /etc/mosquitto/conf.d/bluehanded.conf
```

In that file, uncomment the `listener 8883` block and comment out `listener 1883` with its four lines. Then:

```bash
sudo systemctl restart mosquitto
journalctl -u mosquitto -n 20     # must show "Opening ipv4 listen socket on port 8883"
```

Server, in `config.toml`:

```toml
[mqtt]
port = 8883
tls_ca = "/etc/mosquitto/certs/ca.crt"
host = "localhost"
```

`sudo systemctl restart bluehanded`, and check the log for `MQTT connected`.

Nodes, in `esp32-node/include/secrets.h`:

```c
#define MQTT_HOST "192.168.1.10"   // must be the IP given to make_certs.sh
#define MQTT_PORT 8883
#define MQTT_USE_TLS
static const char MQTT_CA_CERT[] = R"EOF(
-----BEGIN CERTIFICATE-----
...paste the content of /etc/mosquitto/certs/ca.crt here...
-----END CERTIFICATE-----
)EOF";
```

Re-flash every node (env `node`). TLS adds about 40 KB of RAM use per node; check `free_heap` in the node status stays above ~40 KB.

Verify that plain MQTT is gone: `mosquitto_sub -h <pi-ip> -p 1883 -t '#'` must fail to connect.

## 9.2 HTTPS for the dashboard (recommended)

Put the dashboard behind nginx with the same CA:

```bash
sudo apt install -y nginx
```

`/etc/nginx/sites-available/bluehanded`:

```nginx
server {
    listen 443 ssl;
    ssl_certificate     /etc/mosquitto/certs/server.crt;
    ssl_certificate_key /etc/nginx/server.key;   # copy of the broker key readable by nginx
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

Enable it, set `[web] host = "127.0.0.1"` in `config.toml` so Flask is only reachable through nginx, and import `ca.crt` as a trusted certificate on the proctors' laptops.

## 9.3 Network

- Use a **dedicated router** for the system with WPA2/WPA3 and a strong password. Do not tell students the SSID password; hide the SSID if you want.
- Turn off WPS and the router's admin page from Wi-Fi.
- Give the Pi a fixed address (DHCP reservation).

## 9.4 Raspberry Pi

```bash
sudo passwd <user>                         # strong password
sudo apt install -y unattended-upgrades ufw
sudo ufw allow 22/tcp; sudo ufw allow 443/tcp; sudo ufw allow 8883/tcp   # (5000 and 1883 only if not using nginx/TLS)
sudo ufw enable
```

Prefer SSH keys and disable password login in `/etc/ssh/sshd_config` (`PasswordAuthentication no`).

## 9.5 Physical

- Mount nodes high or inside small enclosures, cable-tied, out of students' reach (report 7.2).
- Keep the Pi and router in the invigilator area or a locked cabinet.
- A node going offline during an exam shows on the dashboard: treat it as an incident and check it.

## Done when

- Port 1883 is closed and nodes and server work on 8883 with TLS.
- Dashboard over HTTPS (or at least on a closed, password-protected Wi-Fi).
- Pi firewall on, default passwords changed.
