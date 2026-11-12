"""RSSI signal processing: Kalman filtering and the log-distance path loss model.

Report sections 4.3 and 4.4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


class Kalman1D:
    """One-dimensional Kalman filter for a slowly varying RSSI value.

    Model (report 4.4):  x_k = A x_{k-1} + K (z_k - H x_{k-1}),  with A = H = 1.

    q: process noise variance (how fast the true RSSI is allowed to drift, dBm^2 per step)
    r: measurement noise variance (how noisy one raw reading is, dBm^2)
    """

    def __init__(self, q: float = 0.5, r: float = 8.0):
        self.q = q
        self.r = r
        self.x: float | None = None  # estimate
        self.p = 1.0  # estimate variance

    def update(self, z: float) -> float:
        if self.x is None:
            # First reading initialises the state.
            self.x = float(z)
            self.p = self.r
            return self.x
        # Predict (A = 1): state unchanged, uncertainty grows.
        p_pred = self.p + self.q
        # Update (H = 1).
        k = p_pred / (p_pred + self.r)
        self.x = self.x + k * (z - self.x)
        self.p = (1 - k) * p_pred
        return self.x

    @property
    def gain(self) -> float:
        p_pred = self.p + self.q
        return p_pred / (p_pred + self.r)


@dataclass
class PathLossModel:
    """Log-distance path loss:  RSSI = RSSI0 - 10 n log10(d)  (report 4.3)."""

    rssi_at_1m: float = -60.0
    n: float = 2.5

    def distance(self, rssi: float) -> float:
        """Estimated distance in metres for a (filtered) RSSI value."""
        return 10 ** ((self.rssi_at_1m - rssi) / (10.0 * self.n))

    def rssi(self, distance: float) -> float:
        """Expected RSSI at a distance (used by the simulator and calibration)."""
        return self.rssi_at_1m - 10.0 * self.n * math.log10(max(distance, 0.01))


def fit_path_loss(points: list[tuple[float, float]]) -> PathLossModel:
    """Fit RSSI0 and n from calibration points [(distance_m, mean_rssi), ...].

    RSSI = RSSI0 - 10 n log10(d) is linear in log10(d), so ordinary least squares
    on (x = -10 log10 d, y = RSSI) gives slope n and intercept RSSI0.
    Needs at least two different distances.
    """
    pts = [(d, r) for d, r in points if d > 0]
    if len({round(d, 3) for d, _ in pts}) < 2:
        raise ValueError("Need calibration points at two or more different distances")
    x = np.array([-10.0 * math.log10(d) for d, _ in pts])
    y = np.array([r for _, r in pts])
    a = np.vstack([x, np.ones_like(x)]).T
    (n, rssi0), *_ = np.linalg.lstsq(a, y, rcond=None)
    return PathLossModel(rssi_at_1m=float(rssi0), n=float(n))


def proximity_band(rssi: float) -> str:
    """Rough bands from report 4.3: -40..-60 => 0-2 m, -60..-75 => 2-5 m, below => >5 m."""
    if rssi >= -60:
        return "near"
    if rssi >= -75:
        return "mid"
    return "far"
