#!/usr/bin/env bash
# Create a private CA and a broker certificate for MQTT over TLS (Step 9).
# Usage: sudo ./make_certs.sh <pi-ip-address> [hostname]
set -euo pipefail
IP="${1:?usage: sudo ./make_certs.sh <pi-ip> [hostname]}"
HOST="${2:-$(hostname)}"
DIR=/etc/mosquitto/certs
mkdir -p "$DIR" && cd "$DIR"

if [ ! -f ca.key ]; then
  openssl req -x509 -new -nodes -newkey rsa:2048 -keyout ca.key -out ca.crt -days 1825 \
    -subj "/CN=Blue-Handed CA"
fi
openssl req -new -nodes -newkey rsa:2048 -keyout server.key -out server.csr -subj "/CN=${HOST}"
printf "subjectAltName=IP:%s,DNS:%s,DNS:localhost,IP:127.0.0.1\n" "$IP" "$HOST" > san.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt \
  -days 825 -extfile san.ext
rm -f server.csr san.ext
chown mosquitto:mosquitto server.key ca.crt server.crt
chmod 600 server.key ca.key
echo "Done. Copy $DIR/ca.crt into esp32-node/include/secrets.h (MQTT_CA_CERT)"
echo "and set tls_ca = \"$DIR/ca.crt\", port = 8883 in server/config.toml."
