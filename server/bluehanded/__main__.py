"""Command line entry point.

    python -m bluehanded serve [--config config.toml] [--simulate]
    python -m bluehanded create-user <username> --role admin|proctor
    python -m bluehanded simulate [--config config.toml]      # fake nodes over MQTT
    python -m bluehanded fit-pathloss 1:-58 2:-66 3:-71 ...   # offline calibration helper
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from .config import load_config


def _engine(cfg, emit=None):
    from .db import Database
    from .engine import Engine

    return Engine(Database(cfg["database"]["path"]), cfg, emit)


def cmd_serve(args) -> None:
    from .web import create_app, socketio

    cfg = load_config(args.config)
    if args.simulate:
        cfg["mqtt"]["enabled"] = False
        if not cfg["nodes"]:
            from .simulator import default_nodes
            cfg["nodes"] = default_nodes(cfg["room"]["width"], cfg["room"]["height"])

    engine = _engine(cfg, emit=lambda event, data: socketio.emit(event, data))
    app = create_app(engine, cfg)
    socketio.init_app(app, async_mode="threading", cors_allowed_origins=[])

    if engine.db.one("SELECT COUNT(*) AS c FROM users")["c"] == 0:
        logging.warning("No users yet. Create one: python -m bluehanded create-user admin --role admin")

    ingest = None
    if cfg["mqtt"]["enabled"]:
        from .mqtt_ingest import MqttIngest
        ingest = MqttIngest(engine, cfg["mqtt"])
        ingest.start()

    sim = None
    if args.simulate:
        from .simulator import Simulator, default_scenario
        room = cfg["room"]
        sim = Simulator(engine.node_list(), default_scenario(room["width"], room["height"]),
                        room["width"], room["height"], scan_seconds=engine.settings["scan_seconds"])
        # Demo: the invigilator's watch is pre-registered, so it never alerts.
        engine.add_whitelist("c8:28:32:00:00:04", "Invigilator watch (demo)")
        sim.start_thread(engine.handle_scan, engine.handle_status)
        logging.info("Simulator running with %d nodes", len(engine.nodes))

    engine.start()
    host, port = cfg["web"]["host"], int(cfg["web"]["port"])
    logging.info("Dashboard on http://%s:%d", host, port)
    try:
        socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)
    finally:
        engine.stop()
        if ingest:
            ingest.stop()
        if sim:
            sim.stop()


def cmd_create_user(args) -> None:
    from .db import Database
    from .web import create_user

    cfg = load_config(args.config)
    password = args.password or getpass.getpass(f"Password for {args.username}: ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters")
    create_user(Database(cfg["database"]["path"]), args.username, password, args.role)
    print(f"User '{args.username}' ({args.role}) saved")


def cmd_simulate(args) -> None:
    from .simulator import default_nodes, run_over_mqtt

    cfg = load_config(args.config)
    if args.mqtt_user:
        cfg["mqtt"]["username"] = args.mqtt_user
        cfg["mqtt"]["password"] = args.mqtt_password or getpass.getpass(f"MQTT password for {args.mqtt_user}: ")
    room = cfg["room"]
    nodes = cfg["nodes"] or default_nodes(room["width"], room["height"])
    run_over_mqtt(cfg["mqtt"], room, nodes, scan_seconds=args.scan_seconds)


def cmd_fit(args) -> None:
    from .rssi import fit_path_loss

    pts = []
    for p in args.points:
        d, r = p.split(":")
        pts.append((float(d), float(r)))
    m = fit_path_loss(pts)
    print(f"rssi_at_1m = {m.rssi_at_1m:.2f}\npath_loss_n = {m.n:.3f}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="bluehanded", description="Blue-Handed Raspberry Pi server")
    p.add_argument("--config", "-c", help="path to config.toml (or set BLUEHANDED_CONFIG)")
    p.add_argument("--verbose", "-v", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the MQTT ingest, engine and dashboard")
    s.add_argument("--simulate", action="store_true", help="feed fake nodes into the engine (no broker needed)")
    s.set_defaults(fn=cmd_serve)

    u = sub.add_parser("create-user", help="create or update a dashboard user")
    u.add_argument("username")
    u.add_argument("--role", choices=["proctor", "admin"], default="proctor")
    u.add_argument("--password", help="omit to be prompted")
    u.set_defaults(fn=cmd_create_user)

    m = sub.add_parser("simulate", help="publish fake node scans to the MQTT broker")
    m.add_argument("--scan-seconds", type=float, default=3.0)
    m.add_argument("--mqtt-user", help="publish as this MQTT user (e.g. bluehanded-node)")
    m.add_argument("--mqtt-password", help="omit to be prompted")
    m.set_defaults(fn=cmd_simulate)

    f = sub.add_parser("fit-pathloss", help="fit RSSI0 and n from distance:rssi pairs")
    f.add_argument("points", nargs="+", help="e.g. 1:-58 2:-66 4:-74")
    f.set_defaults(fn=cmd_fit)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args.fn(args)


if __name__ == "__main__":
    main()
