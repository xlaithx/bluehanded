import copy

import pytest

from bluehanded.config import DEFAULTS
from bluehanded.db import Database
from bluehanded.engine import Engine
from bluehanded.simulator import SimDevice, Simulator, default_nodes


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(DEFAULTS)
    c["database"]["path"] = str(tmp_path / "t.db")
    c["nodes"] = default_nodes(12, 8)
    c["web"]["secret_key"] = "x"
    return c


@pytest.fixture
def engine(cfg):
    events = []
    e = Engine(Database(cfg["database"]["path"]), cfg, emit=lambda ev, data: events.append((ev, data)))
    e.events = events
    return e


def run(engine, devices, seconds=60, scan=3.0, seed=1):
    """Drive the engine with simulated scans on a virtual clock."""
    sim = Simulator(engine.node_list(), devices, 12, 8, noise_db=3.0, seed=seed)
    t0 = 1_000_000.0
    t = 0.0
    while t < seconds:
        for d in devices:
            d.step(scan, 12, 8)
        sim.seq += 1
        for node in engine.node_list():
            engine.handle_scan(node["id"], sim.batch(node, t), ts=t0 + t)
        # The engine ticks every second.
        for k in range(int(scan)):
            engine.tick(now=t0 + t + k)
        t += scan
    return t0 + t


def alerts(engine):
    return [data for ev, data in engine.events if ev == "alert"]


def test_hidden_earbud_raises_one_high_alert(engine):
    bud = SimDevice("d4:3a:2c:11:22:01", "Galaxy Buds2", 4.0, 3.0, ["184e"], appearance=0x0941)
    run(engine, [bud])
    a = alerts(engine)
    assert len(a) == 1
    assert a[0]["mac"] == bud.mac and a[0]["severity"] == "high"
    assert abs(a[0]["x"] - 4.0) < 2.5 and abs(a[0]["y"] - 3.0) < 2.5
    dev = engine.device_list()[0]
    assert dev["suspicious"] and dev["is_audio"]


def test_whitelisted_device_never_alerts(engine):
    engine.add_whitelist("C8:28:32:00:00:04", "invigilator")
    watch = SimDevice("c8:28:32:00:00:04", "Watch", 6.0, 4.0, [])
    run(engine, [watch])
    assert alerts(engine) == []


def test_device_far_outside_hall_does_not_alert(engine):
    corridor = SimDevice("5a:12:9e:00:00:05", "Phone", -9.0, 4.0, [])
    run(engine, [corridor], seconds=90)
    assert alerts(engine) == []


def test_passer_by_is_not_persistent(engine):
    # Shows up in one scan cycle only.
    walker = SimDevice("aa:00:00:00:00:01", None, 2.0, 2.0, [], on_after=0)
    sim = Simulator(engine.node_list(), [walker], 12, 8, noise_db=0, seed=1)
    for node in engine.node_list():
        engine.handle_scan(node["id"], sim.batch(node, 0), ts=1000.0)
    for k in range(10):
        engine.tick(now=1000.0 + k)
    assert alerts(engine) == []


def test_audio_only_setting(engine):
    engine.update_settings({"audio_only": True})
    phone = SimDevice("f0:5c:77:aa:bb:03", "Redmi Note 12", 6.0, 4.0, [])
    run(engine, [phone])
    assert alerts(engine) == []


def test_verify_alert_and_whitelist(engine):
    bud = SimDevice("d4:3a:2c:11:22:01", "Buds", 4.0, 3.0, ["110b"])
    run(engine, [bud])
    alert = alerts(engine)[0]
    out = engine.verify_alert(alert["id"], "false_alarm", "proctor1", "teacher's earbuds", whitelist=True)
    assert out["status"] == "false_alarm" and out["verified_by"] == "proctor1"
    assert "d4:3a:2c:11:22:01" in engine.whitelist
    with pytest.raises(ValueError):
        engine.verify_alert(alert["id"], "maybe", "p")


def test_settings_persist(engine, cfg):
    engine.update_settings({"proximity_m": "2.5", "persistence_cycles": "5"})
    again = Engine(engine.db, cfg)
    assert again.settings["proximity_m"] == 2.5
    assert again.settings["persistence_cycles"] == 5


def test_unknown_node_is_registered_disabled(engine):
    engine.handle_scan("node-99", {"seq": 1, "devices": [{"mac": "aa:bb:cc:dd:ee:ff", "rssi": -50}]})
    n = [n for n in engine.node_list() if n["id"] == "node-99"][0]
    assert n["enabled"] == 0


def test_bad_items_are_skipped(engine):
    stored = engine.handle_scan("node-1", {"devices": [{"mac": "x"}, {"rssi": -40}, {"mac": "aa:aa:aa:aa:aa:aa", "rssi": "-50"}]})
    assert stored == 1


def test_new_session_and_clear(engine):
    bud = SimDevice("d4:3a:2c:11:22:01", "Buds", 4.0, 3.0, ["110b"])
    run(engine, [bud])
    old = engine.session["id"]
    engine.new_session("Second exam")
    assert engine.session["id"] != old and engine.devices == {}
    engine.clear_data(old)
    assert engine.db.query("SELECT * FROM alerts WHERE session_id=?", (old,)) == []


def test_calibration_sample(engine):
    import time
    now = time.time()
    for i in range(5):
        engine.handle_scan("node-1", {"seq": i, "devices": [{"mac": "aa:bb:cc:dd:ee:01", "rssi": -60 - i % 2}]},
                           ts=now - 4 + i)
    p = engine.calibration_sample("node-1", "aa:bb:cc:dd:ee:01", 1.0, seconds=10)
    assert p["samples"] == 5 and -61 <= p["mean_rssi"] <= -60
    with pytest.raises(ValueError):
        engine.calibration_sample("node-2", "aa:bb:cc:dd:ee:01", 1.0)
