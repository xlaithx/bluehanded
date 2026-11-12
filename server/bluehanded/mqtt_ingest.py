"""MQTT subscriber: receives ESP32 scan data from Mosquitto (report 5.1.3).

Topics (prefix defaults to "blue-handed"):
  <prefix>/scan/<node_id>     node -> server   JSON scan batch
  <prefix>/status/<node_id>   node -> server   JSON heartbeat, retained; LWT {"status":"offline"}
  <prefix>/config/<node_id>   server -> node   JSON {"min_rssi": -85, "scan_seconds": 3}, retained
  <prefix>/config/all         server -> nodes  same, for every node
"""

from __future__ import annotations

import json
import logging
import ssl

import paho.mqtt.client as mqtt

from .engine import Engine

log = logging.getLogger(__name__)


class MqttIngest:
    def __init__(self, engine: Engine, cfg: dict):
        self.engine = engine
        self.cfg = cfg
        self.prefix = cfg["topic_prefix"].rstrip("/")
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg["client_id"])
        if cfg.get("username"):
            self.client.username_pw_set(cfg["username"], cfg.get("password") or None)
        if cfg.get("tls_ca"):
            self.client.tls_set(ca_certs=cfg["tls_ca"], tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.connected = False
        engine.on_settings_changed = self.push_node_config

    def start(self) -> None:
        log.info("Connecting to MQTT broker %s:%s", self.cfg["host"], self.cfg["port"])
        self.client.reconnect_delay_set(1, 30)
        self.client.connect_async(self.cfg["host"], int(self.cfg["port"]), keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            log.error("MQTT connect failed: %s", reason_code)
            return
        self.connected = True
        log.info("MQTT connected")
        client.subscribe([(f"{self.prefix}/scan/+", 0), (f"{self.prefix}/status/+", 1)])
        self.push_node_config(self.engine.settings)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = False
        log.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            parts = msg.topic.split("/")
            kind, node_id = parts[-2], parts[-1]
            payload = json.loads(msg.payload.decode("utf-8", "replace") or "{}")
            if not isinstance(payload, dict):
                return
            if kind == "scan":
                self.engine.handle_scan(payload.get("node", node_id), payload)
            elif kind == "status":
                self.engine.handle_status(node_id, payload)
        except Exception:
            log.exception("Bad MQTT message on %s", msg.topic)

    def push_node_config(self, settings: dict) -> None:
        """Send detection threshold and scan duration to all nodes (retained)."""
        if not self.connected:
            return
        body = json.dumps({"min_rssi": int(settings["node_min_rssi"]),
                           "scan_seconds": int(settings["scan_seconds"])})
        self.client.publish(f"{self.prefix}/config/all", body, qos=1, retain=True)
