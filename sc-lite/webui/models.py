#!/usr/bin/env python3
"""Per-model capability table for Goldshell Yotta / cloud-box firmware.

Adapted from ``gbox/models.py`` in crProductGuy/goldshell-box-tools-productguy
(MIT License) — see ``ATTRIBUTION.md``. SC5 Pro II row and capability fields
(board_source, plan_dialect, fan_target, temp_target_basis, absent_signature,
plan_names) come from that project; SC Lite / HS Box rows blend ProductGuy's
table with Maveth/goldshell-config live captures.

Keyed by the ``model`` string ``GET /mcb/status`` returns. Lookup ignores case,
spaces, hyphens, and underscores so ``Goldshell-SC5ProⅡ`` (Unicode Ⅱ) still
matches.
"""
from __future__ import annotations

from typing import Any

PLAN_DIALECTS = ("box", "mv_pv", "float_pv")

# webui profile ids used by our fleet UI / probe
PROFILE_IDS = ("sc-lite", "hs-box", "sc-box", "sc5-pro", "sc5-pro-ii", "unknown")

MODELS: dict[str, dict[str, Any]] = {
    "Goldshell-SCBox": {
        "name": "SC-BOX",
        "profile_id": "sc-box",
        "rated_mhs": 900_000.0,
        "rated_watts": 200.0,
        "fans": 2,
        "fan_max_rpm": 4900.0,
        "boards": 1,
        "source": (
            "ProductGuy gbox models.py — Goldshell spec via retailer listings; "
            "fan max observed on one unit"
        ),
        "verified_string": True,
        "plan_dialect": "box",
        "board_source": "icinfo",
        "dbg_expected": True,
        "fan_target": True,
        "temp_target_basis": "board_sensor",
        "plan_names": None,
        "absent_signature": True,
    },
    "Goldshell-SCBox II": {
        "name": "SC-BOX II",
        "profile_id": "sc-box",
        "rated_mhs": 1_900_000.0,
        "rated_watts": 400.0,
        "fans": 2,
        "fan_max_rpm": None,
        "boards": 1,
        "source": "ProductGuy gbox models.py — retailer listings; model string not read from a unit",
        "verified_string": False,
        "plan_dialect": "box",
        "board_source": "icinfo",
        "dbg_expected": True,
        "fan_target": True,
        "temp_target_basis": "board_sensor",
        "plan_names": None,
        "absent_signature": False,
    },
    "Goldshell-SCLITE": {
        "name": "SC Lite",
        "profile_id": "sc-lite",
        "rated_mhs": 4_400_000.0,
        "rated_watts": 950.0,
        "fans": 4,
        "fan_max_rpm": 2200.0,
        "boards": 4,
        "source": (
            "Live capture fixtures/sclite-live 2026-09-22 (fw 2.2.0, hw 30.40.SA, "
            "MCB_V4_3): model Goldshell-SCLITE, 4×PGA / fan0-3, mv_pv plan, "
            "no temp_targets, /dbg/minerinfo 200 with JWT, fanctrllog target_temp:85"
        ),
        "verified_string": True,
        "plan_dialect": "mv_pv",
        "board_source": "http_devs",
        "dbg_expected": True,  # answers with JWT on this unit (MCB_V4_3)
        "fan_target": False,
        "temp_target_basis": "fixed",
        "plan_names": None,
        "absent_signature": False,
    },
    "Goldshell-HSBox": {
        "name": "HS Box",
        "profile_id": "hs-box",
        "rated_mhs": None,
        "rated_watts": None,
        "fans": 2,
        "fan_max_rpm": None,
        "boards": None,
        "source": "Maveth/goldshell-config live HS Box (float-V plan; fan kick confirmed)",
        "verified_string": False,
        "plan_dialect": "float_pv",
        "board_source": "http_devs",
        "dbg_expected": False,
        "fan_target": False,
        "temp_target_basis": "fixed",
        "plan_names": None,
        "absent_signature": False,
    },
    # Exact bytes from /mcb/status on a friend's unit (Unicode Ⅱ, U+2161) — ProductGuy capture
    "Goldshell-SC5ProⅡ": {
        "name": "SC5 Pro II",
        "profile_id": "sc5-pro-ii",
        "rated_mhs": 14_000_000.0,
        "rated_watts": 3300.0,
        "fans": 4,
        "fan_max_rpm": None,
        "boards": 4,
        "source": (
            "ProductGuy gbox models.py + fixtures/sc5proii (friend capture 2026-09-15; "
            "MCB_V3_3 fw 2.2.0 hw 30.50.SA; 4 PGA boards / 4 fans; mv_pv plan)"
        ),
        "verified_string": True,
        "plan_dialect": "mv_pv",
        "board_source": "icinfo",
        "dbg_expected": True,
        "fan_target": False,
        "temp_target_basis": "fixed",
        "plan_names": {0: "Hashrate Mode", 2: "Low-power Mode", 3: "Idle Mode"},
        "absent_signature": False,
    },
    "Goldshell-SC5Pro": {
        "name": "SC5 Pro",
        "profile_id": "sc5-pro",
        "rated_mhs": 11_000_000.0,
        "rated_watts": 2820.0,
        "fans": None,
        "fan_max_rpm": None,
        "boards": None,
        "source": (
            "ProductGuy gbox models.py — Goldshell spec sheet 2026-09-15; "
            "capabilities assumed as SC5 Pro II"
        ),
        "verified_string": False,
        "plan_dialect": "mv_pv",
        "board_source": "icinfo",
        "dbg_expected": True,
        "fan_target": False,
        "temp_target_basis": "fixed",
        "plan_names": None,
        "absent_signature": False,
    },
}

UNKNOWN: dict[str, Any] = {
    "name": None,
    "profile_id": "unknown",
    "rated_mhs": None,
    "rated_watts": None,
    "fans": None,
    "fan_max_rpm": None,
    "boards": None,
    "source": "not in the table — probe and file a capture issue",
    "verified_string": False,
    "plan_dialect": "box",
    "board_source": "icinfo",
    "dbg_expected": True,
    "fan_target": False,
    "temp_target_basis": "board_sensor",
    "plan_names": None,
    "absent_signature": False,
}


def model_key(model: Any) -> str:
    text = model if isinstance(model, str) else ("" if model is None else str(model))
    return "".join(ch for ch in text.casefold() if ch not in " -_")


_BY_KEY = {model_key(k): v for k, v in MODELS.items()}


def rated_for(model: Any) -> dict[str, Any] | None:
    return _BY_KEY.get(model_key(model))


def profile_for(model: Any) -> dict[str, Any]:
    """Capability profile for a firmware model string (always a fresh dict)."""
    text = model if isinstance(model, str) and model else None
    row = _BY_KEY.get(model_key(model))
    if row is not None:
        p = dict(row)
        p.update(known=True, model=text)
    else:
        p = dict(UNKNOWN)
        p.update(known=False, model=text, name=text)
        # Fuzzy fallbacks for strings not yet in the table
        mk = model_key(model)
        if "sclite" in mk:
            p["profile_id"] = "sc-lite"
            p["plan_dialect"] = "mv_pv"
            p["board_source"] = "http_devs"
            p["fan_target"] = False
            p["temp_target_basis"] = "fixed"
        elif "hsbox" in mk or mk.endswith("hs"):
            p["profile_id"] = "hs-box"
            p["plan_dialect"] = "float_pv"
        elif "sc5proii" in mk or "sc5pro2" in mk:
            p["profile_id"] = "sc5-pro-ii"
            p["plan_dialect"] = "mv_pv"
            p["boards"] = 4
            p["fans"] = 4
        elif "sc5" in mk:
            p["profile_id"] = "sc5-pro"
            p["plan_dialect"] = "mv_pv"
        elif "scbox" in mk:
            p["profile_id"] = "sc-box"
            p["plan_dialect"] = "box"
    return p
