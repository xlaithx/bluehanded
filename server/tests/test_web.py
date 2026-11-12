import copy
import re

import pytest

from bluehanded.config import DEFAULTS
from bluehanded.db import Database
from bluehanded.engine import Engine
from bluehanded.simulator import default_nodes
from bluehanded.web import create_app, create_user, socketio


@pytest.fixture
def app(tmp_path):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["database"]["path"] = str(tmp_path / "w.db")
    cfg["nodes"] = default_nodes(12, 8)
    cfg["web"]["secret_key"] = "test"
    engine = Engine(Database(cfg["database"]["path"]), cfg)
    create_user(engine.db, "admin", "adminpass123", "admin")
    create_user(engine.db, "proc", "procpass123", "proctor")
    app = create_app(engine, cfg)
    socketio.init_app(app, async_mode="threading")
    app.engine = engine
    return app


def login(client, user, pw):
    return client.post("/login", data={"username": user, "password": pw})


def csrf(client):
    html = client.get("/").get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([0-9a-f]+)"', html).group(1)


def test_requires_login(app):
    c = app.test_client()
    assert c.get("/").status_code == 302
    assert c.get("/api/state").status_code == 401


def test_bad_password(app):
    c = app.test_client()
    r = login(c, "admin", "nope")
    assert r.status_code == 200 and b"Wrong username" in r.data


def test_proctor_cannot_open_admin(app):
    c = app.test_client()
    login(c, "proc", "procpass123")
    assert c.get("/").status_code == 200
    assert c.get("/admin").status_code == 403


def test_admin_pages_and_export(app):
    c = app.test_client()
    login(c, "admin", "adminpass123")
    assert c.get("/admin").status_code == 200
    assert c.get("/alerts").status_code == 200
    state = c.get("/api/state").get_json()
    assert len(state["nodes"]) == 4
    sid = state["session"]["id"]
    r = c.get(f"/admin/export/{sid}.csv")
    assert r.status_code == 200 and b"alert_id" in r.data
    assert c.get(f"/admin/export/{sid}.json").get_json()["session"]["id"] == sid


def test_post_without_csrf_is_rejected(app):
    c = app.test_client()
    login(c, "admin", "adminpass123")
    assert c.post("/admin/settings", data={"proximity_m": "2"}).status_code == 400


def test_settings_and_nodes_forms(app):
    c = app.test_client()
    login(c, "admin", "adminpass123")
    tok = csrf(c)
    r = c.post("/admin/settings", data={"csrf": tok, "proximity_m": "2.2", "persistence_cycles": "4"})
    assert r.status_code == 302
    assert app.engine.settings["proximity_m"] == 2.2 and app.engine.settings["audio_only"] is False
    c.post("/admin/nodes", data={"csrf": tok, "id": "node-5", "label": "Middle", "x": "6", "y": "4", "enabled": "on"})
    assert "node-5" in app.engine.nodes and app.engine.nodes["node-5"]["x"] == 6


def test_verify_via_api(app):
    eng = app.engine
    c = app.test_client()
    login(c, "proc", "procpass123")
    tok = csrf(c)
    cur = eng.db.execute("INSERT INTO alerts(session_id, mac, created_at, reason, severity) VALUES (?,?,?,?,?)",
                         (eng.session["id"], "aa:bb:cc:dd:ee:ff", 1.0, "test", "high"))
    r = c.post(f"/api/alerts/{cur.lastrowid}/verify", json={"verdict": "confirmed", "note": "seat 14"},
               headers={"X-CSRF-Token": tok})
    assert r.status_code == 200
    assert r.get_json()["status"] == "confirmed" and r.get_json()["verified_by"] == "proc"


def test_socketio_snapshot(app):
    c = app.test_client()
    login(c, "admin", "adminpass123")
    sc = socketio.test_client(app, flask_test_client=c)
    assert sc.is_connected()
    names = [m["name"] for m in sc.get_received()]
    assert "snapshot" in names


def test_socketio_rejects_anonymous(app):
    sc = socketio.test_client(app)
    assert not sc.is_connected()
