"""Flask + Flask-SocketIO web dashboard (report 5.2.2 and use cases 6.1)."""

from __future__ import annotations

import csv
import functools
import io
import json
import secrets
import time

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_socketio import SocketIO, disconnect
from werkzeug.security import check_password_hash, generate_password_hash

from .db import Database
from .engine import Engine, norm_mac
from .rssi import fit_path_loss

socketio = SocketIO()


def create_user(db: Database, username: str, password: str, role: str) -> None:
    if role not in ("proctor", "admin"):
        raise ValueError("role must be proctor or admin")
    db.execute(
        "INSERT INTO users(username, password_hash, role, created_at) VALUES (?,?,?,?) "
        "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash, role=excluded.role",
        (username, generate_password_hash(password), role, time.time()))


def create_app(engine: Engine, config: dict) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config["web"]["secret_key"]
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    db = engine.db

    # --------------------------------------------------------------- auth
    def current_user():
        uid = session.get("uid")
        return db.one("SELECT id, username, role FROM users WHERE id=?", (uid,)) if uid else None

    def login_required(role: str | None = None):
        def deco(fn):
            @functools.wraps(fn)
            def wrapper(*a, **kw):
                user = current_user()
                if not user:
                    if request.path.startswith("/api/"):
                        abort(401)
                    return redirect(url_for("login", next=request.path))
                if role == "admin" and user["role"] != "admin":
                    abort(403)
                return fn(*a, **kw)
            return wrapper
        return deco

    @app.before_request
    def csrf_protect():
        if request.method in ("POST", "PUT", "DELETE"):
            token = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
            if request.endpoint != "login" and token != session.get("csrf"):
                abort(400, "Missing or bad CSRF token")

    @app.context_processor
    def inject():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return {"user": current_user(), "csrf": session["csrf"], "room": config["room"],
                "active_session": engine.session}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            row = db.one("SELECT * FROM users WHERE username=?", (request.form.get("username", ""),))
            if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
                session.clear()
                session["uid"] = row["id"]
                session["csrf"] = secrets.token_hex(16)
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
            flash("Wrong username or password", "error")
        no_users = db.one("SELECT COUNT(*) AS c FROM users")["c"] == 0
        return render_template("login.html", no_users=no_users)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------------------ pages
    @app.route("/")
    @login_required()
    def dashboard():
        return render_template("dashboard.html")

    @app.route("/device/<mac>")
    @login_required()
    def device_page(mac):
        mac = norm_mac(mac)
        info = next((d for d in engine.device_list() if d["mac"] == mac), None)
        if info is None:
            info = db.one("SELECT * FROM devices WHERE session_id=? AND mac=?", (engine.session["id"], mac))
            if info is None:
                abort(404)
        alerts = db.query("SELECT * FROM alerts WHERE mac=? ORDER BY created_at DESC", (mac,))
        return render_template("device.html", mac=mac, info=info, alerts=alerts)

    @app.route("/alerts")
    @login_required()
    def alerts_page():
        rows = db.query("SELECT a.*, s.name AS session_name FROM alerts a JOIN sessions s ON s.id=a.session_id "
                        "ORDER BY a.created_at DESC LIMIT 500")
        return render_template("alerts.html", alerts=rows)

    # ------------------------------------------------------------ admin pages
    @app.route("/admin")
    @login_required("admin")
    def admin():
        return render_template(
            "admin.html",
            nodes=engine.node_list(),
            settings=engine.settings,
            whitelist=db.query("SELECT * FROM whitelist ORDER BY added_at DESC"),
            users=db.query("SELECT id, username, role, created_at FROM users ORDER BY username"),
            sessions=db.query("SELECT s.*, (SELECT COUNT(*) FROM alerts a WHERE a.session_id=s.id) AS alerts, "
                              "(SELECT COUNT(*) FROM devices d WHERE d.session_id=s.id) AS devices "
                              "FROM sessions s ORDER BY id DESC"),
            calib=db.query("SELECT * FROM calibration_points ORDER BY created_at DESC"),
        )

    def back(msg: str, kind: str = "ok", anchor: str = ""):
        flash(msg, kind)
        return redirect(url_for("admin") + anchor)

    @app.route("/admin/nodes", methods=["POST"])
    @login_required("admin")
    def admin_nodes():
        f = request.form
        if f.get("action") == "delete":
            engine.delete_node(f["id"])
            return back(f"Node {f['id']} deleted", anchor="#nodes")
        try:
            engine.upsert_node(f["id"].strip(), f.get("label", "").strip() or f["id"].strip(),
                               float(f["x"]), float(f["y"]), f.get("enabled") == "on")
        except (KeyError, ValueError):
            return back("Node id, x and y are required (x, y in metres)", "error", "#nodes")
        return back(f"Node {f['id']} saved", anchor="#nodes")

    @app.route("/admin/settings", methods=["POST"])
    @login_required("admin")
    def admin_settings():
        values = {k: v for k, v in request.form.items() if k != "csrf"}
        values["audio_only"] = "audio_only" in request.form
        try:
            engine.update_settings(values)
        except ValueError:
            return back("Invalid number in settings", "error", "#settings")
        return back("Settings saved and sent to nodes", anchor="#settings")

    @app.route("/admin/whitelist", methods=["POST"])
    @login_required("admin")
    def admin_whitelist():
        f = request.form
        if f.get("action") == "delete":
            engine.remove_whitelist(f["mac"])
        else:
            engine.add_whitelist(f["mac"], f.get("label", ""))
        return back("Whitelist updated", anchor="#whitelist")

    @app.route("/admin/users", methods=["POST"])
    @login_required("admin")
    def admin_users():
        f = request.form
        if f.get("action") == "delete":
            if int(f["id"]) == session.get("uid"):
                return back("You cannot delete yourself", "error", "#users")
            db.execute("DELETE FROM users WHERE id=?", (int(f["id"]),))
            return back("User deleted", anchor="#users")
        if len(f.get("password", "")) < 8:
            return back("Password must be at least 8 characters", "error", "#users")
        create_user(db, f["username"].strip(), f["password"], f.get("role", "proctor"))
        return back(f"User {f['username']} saved", anchor="#users")

    @app.route("/admin/session", methods=["POST"])
    @login_required("admin")
    def admin_session():
        f = request.form
        action = f.get("action")
        if action == "new":
            engine.new_session(f.get("name") or time.strftime("Exam %Y-%m-%d %H:%M"))
            return back("New exam session started", anchor="#sessions")
        if action == "clear":
            sid = f.get("session_id")
            engine.clear_data(int(sid) if sid else None)
            return back("Data cleared", anchor="#sessions")
        return back("Unknown action", "error")

    @app.route("/admin/calibration", methods=["POST"])
    @login_required("admin")
    def admin_calibration():
        f = request.form
        action = f.get("action")
        try:
            if action == "sample":
                p = engine.calibration_sample(f["node_id"], f["mac"], float(f["distance"]),
                                              float(f.get("seconds") or 10))
                return back(f"Recorded {p['samples']} samples: mean {p['mean_rssi']:.1f} dBm at "
                            f"{p['distance']} m", anchor="#calibration")
            if action == "fit":
                pts = [(r["distance"], r["mean_rssi"]) for r in db.query("SELECT * FROM calibration_points")]
                model = fit_path_loss(pts)
                if not (1.0 <= model.n <= 6.0):
                    return back(f"Fit gave n={model.n:.2f}, which is not realistic. Record more points.",
                                "error", "#calibration")
                engine.update_settings({"rssi_at_1m": round(model.rssi_at_1m, 2),
                                        "path_loss_n": round(model.n, 3)})
                return back(f"Calibrated: RSSI at 1 m = {model.rssi_at_1m:.1f} dBm, n = {model.n:.2f}",
                            anchor="#calibration")
            if action == "delete":
                db.execute("DELETE FROM calibration_points WHERE id=?", (int(f["id"]),))
                return back("Point deleted", anchor="#calibration")
            if action == "clear":
                db.execute("DELETE FROM calibration_points")
                return back("Calibration points cleared", anchor="#calibration")
        except (KeyError, ValueError) as e:
            return back(str(e), "error", "#calibration")
        return back("Unknown action", "error")

    # ------------------------------------------------------------ export
    @app.route("/admin/export/<int:session_id>.<fmt>")
    @login_required("admin")
    def export(session_id, fmt):
        s = db.one("SELECT * FROM sessions WHERE id=?", (session_id,))
        if not s:
            abort(404)
        alerts = db.query("SELECT * FROM alerts WHERE session_id=? ORDER BY created_at", (session_id,))
        devices = db.query("SELECT * FROM devices WHERE session_id=? ORDER BY first_seen", (session_id,))

        def iso(ts):
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""

        if fmt == "json":
            body = json.dumps({"session": s, "alerts": alerts, "devices": devices}, indent=2)
            return Response(body, mimetype="application/json", headers={
                "Content-Disposition": f"attachment; filename=bluehanded-session-{session_id}.json"})
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["Session", s["name"], "Room", s["room"], "Started", iso(s["started_at"]),
                        "Ended", iso(s["ended_at"])])
            w.writerow([])
            w.writerow(["alert_id", "time", "mac", "name", "severity", "reason", "x_m", "y_m", "nearest_node",
                        "nearest_distance_m", "rssi_dbm", "status", "verified_by", "verified_at", "note"])
            for a in alerts:
                w.writerow([a["id"], iso(a["created_at"]), a["mac"], a["name"] or "", a["severity"], a["reason"],
                            _r(a["x"]), _r(a["y"]), a["nearest_node"] or "", _r(a["nearest_distance"]),
                            _r(a["rssi"]), a["status"], a["verified_by"] or "", iso(a["verified_at"]),
                            a["note"] or ""])
            w.writerow([])
            w.writerow(["mac", "name", "audio", "audio_reason", "first_seen", "last_seen", "suspicious",
                        "last_x_m", "last_y_m"])
            for d in devices:
                w.writerow([d["mac"], d["name"] or "", d["is_audio"], d["audio_reason"] or "", iso(d["first_seen"]),
                            iso(d["last_seen"]), d["suspicious"], _r(d["x"]), _r(d["y"])])
            return Response(buf.getvalue(), mimetype="text/csv", headers={
                "Content-Disposition": f"attachment; filename=bluehanded-session-{session_id}.csv"})
        abort(404)

    # ------------------------------------------------------------ JSON API
    @app.route("/api/state")
    @login_required()
    def api_state():
        return jsonify(engine.snapshot())

    @app.route("/api/device/<mac>/history")
    @login_required()
    def api_history(mac):
        return jsonify(engine.device_history(mac))

    @app.route("/api/heatmap")
    @login_required()
    def api_heatmap():
        return jsonify(engine.heatmap(minutes=float(request.args.get("minutes", 30))))

    @app.route("/api/alerts/<int:alert_id>/verify", methods=["POST"])
    @login_required()
    def api_verify(alert_id):
        data = request.get_json(silent=True) or request.form
        try:
            alert = engine.verify_alert(alert_id, data.get("verdict", ""), current_user()["username"],
                                        data.get("note", ""), bool(data.get("whitelist")))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        if not alert:
            abort(404)
        return jsonify(alert)

    @app.route("/healthz")
    def healthz():
        return jsonify(ok=True, session=engine.session["id"], nodes=len(engine.nodes),
                       devices=len(engine.devices))

    # ------------------------------------------------------------ Socket.IO
    @socketio.on("connect")
    def on_connect(auth=None):
        if not current_user():
            disconnect()
            return False
        socketio.emit("snapshot", engine.snapshot(), to=request.sid)

    return app


def _r(v, nd=2):
    return "" if v is None else round(v, nd)
