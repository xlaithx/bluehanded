"""Recognise BLE advertisements that look like audio devices (earphones, headsets).

Report 4.6, "Device profile" criterion. Uses three hints the ESP32 forwards:
service UUIDs, the GAP Appearance value, and the device name.
"""

from __future__ import annotations

import re

# 16-bit service UUIDs linked to audio.
AUDIO_SERVICE_UUIDS = {
    "1108": "Headset",
    "110b": "Audio Sink (A2DP)",
    "110d": "Advanced Audio",
    "110e": "AV Remote Control",
    "111e": "Handsfree",
    "1131": "Headset HS",
    "1843": "Audio Input Control",
    "1844": "Volume Control",
    "1845": "Volume Offset Control",
    "184e": "Audio Stream Control (LE Audio)",
    "184f": "Broadcast Audio Scan (LE Audio)",
    "1850": "Published Audio Capabilities (LE Audio)",
    "1853": "Common Audio (LE Audio)",
    "1854": "Hearing Access",
    "fd6f": None,  # Exposure notification, explicitly not audio
}

# GAP Appearance category 0x0940 (wearable audio) and 0x0840 (audio sink), report as audio.
AUDIO_APPEARANCE_CATEGORIES = {0x0940 >> 6: "Wearable audio device", 0x0840 >> 6: "Audio sink"}
HEARING_AID_CATEGORY = 0x0A40 >> 6

NAME_PATTERN = re.compile(
    r"(buds?(?:\d|\b)|pods\b|\bear(?:buds?|phones?|pods?|\b)|headset|headphone|hands?-?free|airdots|\btws\b|\bjbl\b|beats|soundcore|"
    r"freebuds|\bwf-|\bwh-|\bqcy\b|\bbose\b|haylou|lenovo lp|nothing ear|\bebs?\b)",
    re.IGNORECASE,
)

# Manufacturer company IDs (little-endian in the payload, the node sends them as int).
APPLE = 0x004C


def _uuid16(u: str) -> str:
    u = u.lower().strip()
    if u.startswith("0x"):
        u = u[2:]
    # 0000XXXX-0000-1000-8000-00805f9b34fb  => XXXX
    if len(u) == 36 and u.endswith("-0000-1000-8000-00805f9b34fb"):
        return u[4:8]
    return u


def classify(name: str | None, uuids: list[str] | None, appearance: int | None,
             company_id: int | None = None, mfg_type: int | None = None) -> tuple[bool, str]:
    """Return (is_audio, reason)."""
    for u in uuids or []:
        key = _uuid16(u)
        label = AUDIO_SERVICE_UUIDS.get(key)
        if label:
            return True, f"service {label}"
    if appearance:
        cat = appearance >> 6
        if cat in AUDIO_APPEARANCE_CATEGORIES:
            return True, f"appearance {AUDIO_APPEARANCE_CATEGORIES[cat]}"
        if cat == HEARING_AID_CATEGORY:
            # Medical device: never flag as audio cheating gear (report 7.3).
            return False, "hearing aid"
    if company_id == APPLE and mfg_type == 0x07:
        # Apple "proximity pairing" message, sent by AirPods / Beats.
        return True, "Apple proximity pairing (AirPods/Beats)"
    if name and NAME_PATTERN.search(name):
        return True, f"name '{name}'"
    return False, ""
