// Blue-Handed ESP32 scanning node (final firmware).
//
// Flow (report 6.2.1 ESP32):
//   init passive BLE sniffer -> connect Wi-Fi -> connect MQTT ->
//   loop: scan for SCAN_SECONDS, keep devices with RSSI >= threshold,
//         publish one JSON batch {node, seq, devices[]} to blue-handed/scan/<NODE_ID>.
//
// The node also:
//   - publishes a retained heartbeat to blue-handed/status/<NODE_ID> every 10 s,
//     with an MQTT "last will" of {"status":"offline"} so the dashboard sees it drop,
//   - listens on blue-handed/config/all and blue-handed/config/<NODE_ID> for
//     {"min_rssi": -85, "scan_seconds": 3} and saves them in flash (NVS),
//   - forwards hints the server uses to recognise earphones: service UUIDs,
//     GAP appearance, manufacturer company id and first data byte.
//
// Build with the PlatformIO environment "node". Settings go in include/secrets.h.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <BLEAdvertisedDevice.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include <map>
#include <string>
#include <vector>

#include "secrets.h"

#ifdef MQTT_USE_TLS
#include <WiFiClientSecure.h>
#endif

#ifndef NODE_ID
#define NODE_ID "node-1"
#endif
#ifndef MQTT_USER
#define MQTT_USER ""
#endif
#ifndef MQTT_PASSWORD
#define MQTT_PASSWORD ""
#endif
#ifndef TOPIC_PREFIX
#define TOPIC_PREFIX "blue-handed"
#endif

static const char* FW_VERSION = "1.0.0";
static const size_t MAX_DEVICES_PER_MSG = 20;   // keeps each MQTT message under the buffer size
static const size_t MQTT_BUFFER = 4096;
static const uint32_t HEARTBEAT_MS = 10000;
static const size_t MAX_TRACKED = 150;          // protects RAM in a crowded room

// Runtime settings (changed from the dashboard over MQTT, stored in NVS).
static int minRssi = -90;
static int scanSeconds = 3;

static String topicScan, topicStatus, topicConfigAll, topicConfigMine;

#ifdef MQTT_USE_TLS
WiFiClientSecure net;
#else
WiFiClient net;
#endif
PubSubClient mqtt(net);
Preferences prefs;
BLEScan* scanner = nullptr;

// One entry per MAC seen during the current scan window.
struct Seen {
  int rssiSum = 0;
  int count = 0;
  int rssiMax = -127;
  std::string name;
  bool randomAddr = false;
  int appearance = -1;
  int companyId = -1;
  int mfgType = -1;
  std::vector<std::string> uuids;
};

static std::map<std::string, Seen> seen;
static SemaphoreHandle_t seenLock;
static uint32_t seq = 0;
static uint32_t lastHeartbeat = 0;

// ---------------------------------------------------------------- BLE callback
class ScanCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice dev) override {
    int rssi = dev.getRSSI();
    if (rssi < minRssi) return;  // "Ignore device (outside exam zone)"

    std::string mac = dev.getAddress().toString().c_str();
    xSemaphoreTake(seenLock, portMAX_DELAY);
    if (seen.size() >= MAX_TRACKED && seen.find(mac) == seen.end()) {
      xSemaphoreGive(seenLock);
      return;
    }
    Seen& s = seen[mac];
    s.rssiSum += rssi;
    s.count++;
    if (rssi > s.rssiMax) s.rssiMax = rssi;
    if (dev.haveName() && s.name.empty()) s.name = dev.getName().c_str();
    s.randomAddr = dev.getAddressType() == 1;  // 1 = random address (Bluedroid and NimBLE)
    if (dev.haveAppearance()) s.appearance = dev.getAppearance();
    if (dev.haveServiceUUID() && s.uuids.empty()) {
      int n = dev.getServiceUUIDCount();
      for (int i = 0; i < n && i < 4; i++) s.uuids.push_back(dev.getServiceUUID(i).toString().c_str());
    }
    if (dev.haveManufacturerData() && s.companyId < 0) {
      auto md = dev.getManufacturerData();
      if (md.length() >= 2) s.companyId = (uint8_t)md[0] | ((uint8_t)md[1] << 8);
      if (md.length() >= 3) s.mfgType = (uint8_t)md[2];
    }
    xSemaphoreGive(seenLock);
  }
};

// ---------------------------------------------------------------- settings
void loadSettings() {
  prefs.begin("bluehanded", true);
  minRssi = prefs.getInt("min_rssi", minRssi);
  scanSeconds = prefs.getInt("scan_s", scanSeconds);
  prefs.end();
}

void saveSettings() {
  prefs.begin("bluehanded", false);
  prefs.putInt("min_rssi", minRssi);
  prefs.putInt("scan_s", scanSeconds);
  prefs.end();
}

void onMqttMessage(char* topic, byte* payload, unsigned int len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;
  bool changed = false;
  if (doc["min_rssi"].is<int>()) {
    int v = constrain(doc["min_rssi"].as<int>(), -110, -20);
    changed |= v != minRssi;
    minRssi = v;
  }
  if (doc["scan_seconds"].is<int>()) {
    int v = constrain(doc["scan_seconds"].as<int>(), 1, 30);
    changed |= v != scanSeconds;
    scanSeconds = v;
  }
  if (changed) {
    saveSettings();
    Serial.printf("Config updated: min_rssi=%d scan_seconds=%d\n", minRssi, scanSeconds);
  }
}

// ---------------------------------------------------------------- network
void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);  // required while BLE is active (Wi-Fi/BLE coexistence)
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - start > 30000) {
      Serial.println(" timeout, restarting");
      ESP.restart();
    }
  }
  Serial.printf("\nWi-Fi connected, IP %s, RSSI %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
}

void publishStatus(bool online) {
  JsonDocument doc;
  doc["status"] = online ? "online" : "offline";
  doc["node"] = NODE_ID;
  doc["ip"] = WiFi.localIP().toString();
  doc["wifi_rssi"] = WiFi.RSSI();
  doc["uptime"] = millis() / 1000;
  doc["fw"] = FW_VERSION;
  doc["min_rssi"] = minRssi;
  doc["free_heap"] = ESP.getFreeHeap();
  char buf[256];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(topicStatus.c_str(), (const uint8_t*)buf, n, true);
}

void connectMqtt() {
  while (!mqtt.connected()) {
    connectWifi();
    Serial.print("Connecting to MQTT...");
    const char* will = "{\"status\":\"offline\"}";
    bool ok = strlen(MQTT_USER) > 0
                  ? mqtt.connect(NODE_ID, MQTT_USER, MQTT_PASSWORD, topicStatus.c_str(), 1, true, will)
                  : mqtt.connect(NODE_ID, topicStatus.c_str(), 1, true, will);
    if (ok) {
      Serial.println(" connected");
      mqtt.subscribe(topicConfigAll.c_str(), 1);
      mqtt.subscribe(topicConfigMine.c_str(), 1);
      publishStatus(true);
    } else {
      Serial.printf(" failed, rc=%d, retrying in 2 s\n", mqtt.state());
      delay(2000);
    }
  }
}

// ---------------------------------------------------------------- publishing
void publishBatch(std::vector<std::pair<std::string, Seen>>& items, size_t from, size_t to) {
  JsonDocument doc;
  doc["node"] = NODE_ID;
  doc["seq"] = seq;
  doc["uptime"] = millis() / 1000;
  JsonArray arr = doc["devices"].to<JsonArray>();
  for (size_t i = from; i < to; i++) {
    const auto& mac = items[i].first;
    const Seen& s = items[i].second;
    JsonObject o = arr.add<JsonObject>();
    o["mac"] = mac;
    o["rssi"] = (int)lroundf((float)s.rssiSum / s.count);  // mean RSSI over the window
    o["max"] = s.rssiMax;
    o["n"] = s.count;
    o["addr_type"] = s.randomAddr ? "random" : "public";
    if (!s.name.empty()) o["name"] = s.name;
    if (s.appearance >= 0) o["appearance"] = s.appearance;
    if (s.companyId >= 0) {
      o["company_id"] = s.companyId;
      if (s.mfgType >= 0) o["mfg_type"] = s.mfgType;
    }
    if (!s.uuids.empty()) {
      JsonArray u = o["uuids"].to<JsonArray>();
      for (auto& id : s.uuids) u.add(id);
    }
  }
  static char buf[MQTT_BUFFER];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  if (!mqtt.publish(topicScan.c_str(), (const uint8_t*)buf, n, false)) {
    Serial.printf("Publish failed (%u bytes)\n", (unsigned)n);
  }
}

void scanAndPublish() {
  xSemaphoreTake(seenLock, portMAX_DELAY);
  seen.clear();
  xSemaphoreGive(seenLock);

  scanner->start(scanSeconds, false);  // blocking; onResult() fills `seen`
  scanner->clearResults();

  std::vector<std::pair<std::string, Seen>> items;
  xSemaphoreTake(seenLock, portMAX_DELAY);
  items.assign(seen.begin(), seen.end());
  xSemaphoreGive(seenLock);

  seq++;
  if (!mqtt.connected()) connectMqtt();
  if (items.empty()) {
    publishBatch(items, 0, 0);  // empty batch still tells the server we are alive
  }
  for (size_t i = 0; i < items.size(); i += MAX_DEVICES_PER_MSG) {
    publishBatch(items, i, std::min(items.size(), i + MAX_DEVICES_PER_MSG));
    mqtt.loop();
  }
  Serial.printf("Scan #%u: %u devices >= %d dBm\n", (unsigned)seq, (unsigned)items.size(), minRssi);
}

// ---------------------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.printf("\n=== Blue-Handed node %s (fw %s) ===\n", NODE_ID, FW_VERSION);

  seenLock = xSemaphoreCreateMutex();
  loadSettings();

  String prefix = TOPIC_PREFIX;
  topicScan = prefix + "/scan/" + NODE_ID;
  topicStatus = prefix + "/status/" + NODE_ID;
  topicConfigAll = prefix + "/config/all";
  topicConfigMine = prefix + "/config/" + NODE_ID;

  BLEDevice::init("");
  scanner = BLEDevice::getScan();
  scanner->setAdvertisedDeviceCallbacks(new ScanCallbacks(), true);  // true: report every packet
  scanner->setActiveScan(false);  // passive: never transmits scan requests
  scanner->setInterval(100);
  scanner->setWindow(90);         // leave radio time for Wi-Fi

  connectWifi();
#ifdef MQTT_USE_TLS
  net.setCACert(MQTT_CA_CERT);
#endif
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(MQTT_BUFFER);
  mqtt.setKeepAlive(60);  // a scan can block mqtt.loop() for up to 30 s
  mqtt.setCallback(onMqttMessage);
  connectMqtt();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  scanAndPublish();

  if (millis() - lastHeartbeat > HEARTBEAT_MS) {
    lastHeartbeat = millis();
    publishStatus(true);
  }
  mqtt.loop();
}
