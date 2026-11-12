"""Device localization from per-node distance estimates (report 4.5).

- 3+ nodes: linearised weighted least squares, refined with Gauss-Newton.
- 2 nodes: weighted point on the line between the two nodes.
- 1 node: the node position, with the distance as the uncertainty radius.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Anchor:
    node_id: str
    x: float
    y: float
    distance: float  # estimated distance from this node (m)
    rssi: float  # filtered RSSI, used for weighting


@dataclass
class Position:
    x: float
    y: float
    error: float  # rough uncertainty radius in metres
    method: str
    raw_x: float  # unclamped estimate, can be outside the room (used for the "inside" test)
    raw_y: float
    nearest_node: str
    nearest_distance: float


def _weights(anchors: list[Anchor]) -> np.ndarray:
    # Stronger signal => closer => RSSI is more reliable. Weight ~ 1/d^2.
    d = np.array([max(a.distance, 0.3) for a in anchors])
    return 1.0 / d**2


def _wls(anchors: list[Anchor]) -> np.ndarray:
    """Linearise the circle equations against the last anchor and solve WLS."""
    p = np.array([[a.x, a.y] for a in anchors])
    d = np.array([a.distance for a in anchors])
    w = _weights(anchors)
    ref = len(anchors) - 1
    xr, yr, dr = p[ref, 0], p[ref, 1], d[ref]
    a_rows, b_rows, w_rows = [], [], []
    for i in range(ref):
        xi, yi, di = p[i, 0], p[i, 1], d[i]
        a_rows.append([2 * (xr - xi), 2 * (yr - yi)])
        b_rows.append(di**2 - dr**2 - xi**2 + xr**2 - yi**2 + yr**2)
        w_rows.append(min(w[i], w[ref]))
    a = np.array(a_rows)
    b = np.array(b_rows)
    sw = np.sqrt(np.array(w_rows))
    sol, *_ = np.linalg.lstsq(a * sw[:, None], b * sw, rcond=None)
    return sol


def _gauss_newton(anchors: list[Anchor], start: np.ndarray, iters: int = 10) -> np.ndarray:
    """Iteratively minimise sum w_i (||x - p_i|| - d_i)^2 (Taylor series method)."""
    p = np.array([[a.x, a.y] for a in anchors])
    d = np.array([a.distance for a in anchors])
    w = _weights(anchors)
    x = start.astype(float).copy()
    for _ in range(iters):
        diff = x - p
        ranges = np.linalg.norm(diff, axis=1)
        ranges = np.where(ranges < 1e-6, 1e-6, ranges)
        j = diff / ranges[:, None]
        r = ranges - d
        jw = j * w[:, None]
        h = j.T @ jw
        if abs(np.linalg.det(h)) < 1e-9:
            break
        step = np.linalg.solve(h, jw.T @ r)
        x = x - step
        if np.linalg.norm(step) < 1e-4:
            break
    return x


def locate(anchors: list[Anchor], width: float, height: float) -> Position | None:
    if not anchors:
        return None
    anchors = sorted(anchors, key=lambda a: a.distance)
    nearest = anchors[0]

    if len(anchors) == 1:
        x, y = nearest.x, nearest.y
        err, method = nearest.distance, "nearest-node"
    elif len(anchors) == 2:
        a, b = anchors
        # Point between the two nodes, closer to the stronger one.
        t = a.distance / (a.distance + b.distance)
        x = a.x + t * (b.x - a.x)
        y = a.y + t * (b.y - a.y)
        err, method = max(a.distance, 1.0), "two-node"
    else:
        try:
            guess = _wls(anchors)
        except np.linalg.LinAlgError:
            guess = np.array([nearest.x, nearest.y])
        if not np.all(np.isfinite(guess)):
            guess = np.array([nearest.x, nearest.y])
        sol = _gauss_newton(anchors, guess)
        if not np.all(np.isfinite(sol)):
            sol = guess
        x, y = float(sol[0]), float(sol[1])
        resid = [abs(np.hypot(x - an.x, y - an.y) - an.distance) for an in anchors]
        err, method = float(max(0.5, np.sqrt(np.mean(np.square(resid))))), "trilateration"

    # Keep the drawn estimate on the floor plan, but remember the raw one.
    raw_x, raw_y = float(x), float(y)
    x = float(min(max(x, 0.0), width))
    y = float(min(max(y, 0.0), height))
    return Position(
        x=x,
        y=y,
        raw_x=raw_x,
        raw_y=raw_y,
        error=float(err),
        method=method,
        nearest_node=nearest.node_id,
        nearest_distance=float(nearest.distance),
    )
