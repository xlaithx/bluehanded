#!/usr/bin/env bash
# One-shot setup of the Blue-Handed server on Raspberry Pi OS (64-bit).
# Run from the server/ folder:  ./deploy/install_pi.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
USER_NAME="$(id -un)"

echo "== 1/5 System packages"
sudo apt update
sudo apt install -y python3-venv python3-pip mosquitto mosquitto-clients sqlite3 openssl

echo "== 2/5 Python environment"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "== 3/5 Config"
if [ ! -f config.toml ]; then
  cp config.example.toml config.toml
  SECRET="$(openssl rand -hex 32)"
  sed -i "s/^secret_key = \"\"/secret_key = \"${SECRET}\"/" config.toml
  echo "   created config.toml (edit room size, node positions, MQTT password)"
fi

echo "== 4/5 Mosquitto"
sudo cp deploy/mosquitto-bluehanded.conf /etc/mosquitto/conf.d/bluehanded.conf
sudo cp deploy/mosquitto-bluehanded.acl /etc/mosquitto/bluehanded.acl
sudo rm -f /etc/mosquitto/conf.d/blue-handed.conf   # old open test config from the README
if [ ! -f /etc/mosquitto/passwd ]; then
  echo "   Choose the password for the server account (bluehanded-server):"
  sudo mosquitto_passwd -c /etc/mosquitto/passwd bluehanded-server
  echo "   Choose the password for the ESP32 nodes (bluehanded-node):"
  sudo mosquitto_passwd /etc/mosquitto/passwd bluehanded-node
  sudo chown mosquitto:mosquitto /etc/mosquitto/passwd
  sudo chmod 600 /etc/mosquitto/passwd
  echo "   Put the server password in config.toml [mqtt] password"
  echo "   and the node password in esp32-node/include/secrets.h"
fi
sudo systemctl enable --now mosquitto
sudo systemctl restart mosquitto

echo "== 5/5 Service"
sed -e "s#__DIR__#${DIR}#g" -e "s#__USER__#${USER_NAME}#g" deploy/bluehanded.service \
  | sudo tee /etc/systemd/system/bluehanded.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable bluehanded

echo
echo "Next:"
echo "  1. Edit config.toml (MQTT password, room size, nodes)"
echo "  2. .venv/bin/python -m bluehanded -c config.toml create-user admin --role admin"
echo "  3. sudo systemctl start bluehanded && journalctl -u bluehanded -f"
echo "  4. Open http://$(hostname -I | awk '{print $1}'):5000"
