import math
import random

import pytest

from bluehanded.localization import Anchor, locate
from bluehanded.profiles import classify
from bluehanded.rssi import Kalman1D, PathLossModel, fit_path_loss

NODES = [("n1", 0, 0), ("n2", 12, 0), ("n3", 0, 8), ("n4", 12, 8)]


def anchors_for(x, y, model=PathLossModel(), noise=0.0, rng=None):
    rng = rng or random.Random(0)
    out = []
    for nid, nx, ny in NODES:
        rssi = model.rssi(math.hypot(x - nx, y - ny)) + rng.gauss(0, noise)
        out.append(Anchor(nid, nx, ny, model.distance(rssi), rssi))
    return out


def test_path_loss_round_trip():
    m = PathLossModel(-60, 2.5)
    for d in (0.5, 1, 2, 5, 10):
        assert m.distance(m.rssi(d)) == pytest.approx(d, rel=1e-6)
    assert m.rssi(1) == -60


def test_fit_path_loss_recovers_parameters():
    true = PathLossModel(-57.0, 2.8)
    pts = [(d, true.rssi(d)) for d in (1, 2, 3, 4, 6, 8)]
    fit = fit_path_loss(pts)
    assert fit.rssi_at_1m == pytest.approx(-57.0, abs=1e-6)
    assert fit.n == pytest.approx(2.8, abs=1e-6)


def test_fit_needs_two_distances():
    with pytest.raises(ValueError):
        fit_path_loss([(1, -60), (1, -61)])


def test_kalman_reduces_noise():
    rng = random.Random(42)
    k = Kalman1D(q=0.05, r=16)
    raw, filt = [], []
    for _ in range(300):
        z = -70 + rng.gauss(0, 4)
        raw.append(z)
        filt.append(k.update(z))
    tail = filt[50:]
    var_raw = sum((v + 70) ** 2 for v in raw[50:]) / len(tail)
    var_f = sum((v + 70) ** 2 for v in tail) / len(tail)
    assert var_f < var_raw / 4
    assert abs(sum(tail) / len(tail) + 70) < 1.0


def test_kalman_tracks_a_step():
    k = Kalman1D(q=0.5, r=8)
    for _ in range(20):
        k.update(-80)
    for _ in range(30):
        v = k.update(-55)
    assert v == pytest.approx(-55, abs=1.0)


@pytest.mark.parametrize("x,y", [(3, 2), (6, 4), (10, 7), (1, 6)])
def test_trilateration_exact(x, y):
    p = locate(anchors_for(x, y), 12, 8)
    assert p.method == "trilateration"
    assert p.x == pytest.approx(x, abs=0.05)
    assert p.y == pytest.approx(y, abs=0.05)


def test_trilateration_with_noise_is_reasonable():
    rng = random.Random(7)
    errs = []
    for _ in range(200):
        x, y = rng.uniform(1, 11), rng.uniform(1, 7)
        p = locate(anchors_for(x, y, noise=2.0, rng=rng), 12, 8)
        errs.append(math.hypot(p.x - x, p.y - y))
    errs.sort()
    assert errs[len(errs) // 2] < 2.0  # median error under 2 m with 2 dB noise


def test_fallbacks():
    a = anchors_for(2, 2)
    one = locate(a[:1], 12, 8)
    assert one.method == "nearest-node" and (one.x, one.y) == (0, 0)
    two = locate(a[:2], 12, 8)
    assert two.method == "two-node" and 0 < two.x < 12 and two.y == 0
    assert locate([], 12, 8) is None


def test_position_is_clamped_but_raw_kept():
    p = locate(anchors_for(-3, 4), 12, 8)
    assert p.x == 0
    assert p.raw_x < -2


def test_audio_profiles():
    assert classify(None, ["0000110b-0000-1000-8000-00805f9b34fb"], None)[0]
    assert classify(None, ["184e"], None)[0]
    assert classify(None, [], 0x0941)[0]  # earbud appearance
    assert classify(None, [], None, 0x004C, 0x07)[0]  # AirPods
    assert classify("Galaxy Buds2", [], None)[0]
    assert not classify("Redmi Note 12", [], None)[0]
    assert not classify(None, ["180d"], 0x00C1)[0]  # heart rate watch
    assert classify("Hearing aid", [], 0x0A41) == (False, "hearing aid")
