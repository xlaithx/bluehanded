#pragma once

// Copy this file to include/secrets.h and put your own details there.
// secrets.h is ignored by Git, so your passwords are never uploaded.

// Wi-Fi: must be 2.4 GHz (ESP32 does not support 5 GHz).
#define WIFI_SSID "your-network-name"
#define WIFI_PASSWORD "your-password"

// MQTT broker = the Raspberry Pi.
#define MQTT_HOST "your-raspberry-pi-ip"
#define MQTT_PORT 1883

// ---- Final node firmware (env "node") only ----

// Unique per board: node-1, node-2, ... It must match the node id in the dashboard.
#define NODE_ID "node-1"

// Broker login (Step 2 of the guide). Leave empty only for the open test broker.
#define MQTT_USER "bluehanded-node"
#define MQTT_PASSWORD "change-me"

// TLS (Step 9). Uncomment, set MQTT_PORT to 8883 and paste the CA certificate
// from the Pi (/etc/mosquitto/certs/ca.crt). MQTT_HOST must then match the name or
// IP address in the broker certificate.
// #define MQTT_USE_TLS
// static const char MQTT_CA_CERT[] = R"EOF(
// -----BEGIN CERTIFICATE-----
// ...
// -----END CERTIFICATE-----
// )EOF";
