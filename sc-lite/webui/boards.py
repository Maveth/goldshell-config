#!/usr/bin/env python3
"""Multi-board parsing for Goldshell :4028 ``devs`` and ``/dbg/minerinfo``.

Adapted from ``gbox/api.py`` helpers in crProductGuy/goldshell-box-tools-productguy
(MIT License) — see ``ATTRIBUTION.md``. Used so SC5 Pro (4× PGA) and SC Lite
multi-board units classify correctly in probe / fleet snapshots.
"""
from __future__ import annotations

import json
import re
from typing import Any

_MINERINFO_FIELDS = {
    "elapsed": "Device Elapsed",
    "mhs_av": "MHS av",
    "mhs_20s": "MHS 20s",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "hw_errors": "Hardware Errors",
    "hw_pct": "Device Hardware%",
    "clock": "clock",
    "fan0": "fan0",
    "fan1": "fan1",
    "chip_temp": "tstemp-0",
    "chip_temp1": "tstemp-1",
    "board_temp": "tstemp-2",
    "rebootcnt": "rebootcnt",
    "overheat": "overheat",
}

_PGA_RE = re.compile(r"^\[PGA(\d+)\] =>", re.M)


def _num(s: Any) -> float | int | None:
    if s is None or s == "":
        return None
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    if isinstance(s, str) and "." not in s and f.is_integer():
        return int(f)
    return int(f) if f.is_integer() else f


def _kv(text: str, key: str) -> str | None:
    m = re.search(r"\[" + re.escape(key) + r"\] => ([^\n]*)", text)
    return m.group(1).strip() if m else None


def _fan_list(read) -> list[float | int]:
    fans: list[float | int] = []
    for n in range(8):
        v = read(n)
        if v is None:
            break
        fans.append(v)
    return fans


def _board_from_kv(block: str, unit_text: str, index: int) -> dict[str, Any]:
    b = {name: _num(_kv(block, key)) for name, key in _MINERINFO_FIELDS.items()}
    b["board"] = index
    b["nonced"] = _num(_kv(block, "Nonced"))
    b["fans"] = _fan_list(lambda n: _num(_kv(block, "fan%d" % n)))
    b["voltage_mv"] = _num(_kv(unit_text, "voltage"))
    b["current_ma"] = _num(_kv(unit_text, "current"))
    return b


def parse_minerinfo_boards(text: str) -> list[dict[str, Any]]:
    """One dict per ``[PGAn] =>`` block of ``/dbg/minerinfo``."""
    text = text or ""
    heads = list(_PGA_RE.finditer(text))
    if not heads:
        return [_board_from_kv(text, text, 0)]
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append(_board_from_kv(text[m.start() : end], text, int(m.group(1))))
    return out


def parse_devs4028(payload: dict[str, Any] | str | bytes) -> list[dict[str, Any]]:
    """Port-4028 ``devs`` JSON → per-board list (SC5 Pro II = 4 PGA rows)."""
    if isinstance(payload, (bytes, bytearray)):
        text = bytes(payload).decode("utf-8", "replace")
        j = json.loads(text.rstrip("\x00"))
    elif isinstance(payload, str):
        j = json.loads(payload.rstrip("\x00"))
    else:
        j = payload
    out: list[dict[str, Any]] = []
    for d in j.get("DEVS") or []:
        if not isinstance(d, dict):
            continue

        def g(k: str):
            return _num(None if d.get(k) is None else str(d.get(k)))

        b = {name: g(key) for name, key in _MINERINFO_FIELDS.items()}
        b["board"] = int(d.get("PGA", len(out)))
        b["nonced"] = g("Nonced")
        b["fans"] = _fan_list(lambda n: g("fan%d" % n))
        b["voltage_mv"] = g("voltage")
        b["current_ma"] = g("current")
        b["status"] = d.get("Status")
        b["enabled"] = d.get("Enabled")
        out.append(b)
    return out


def hottest_index(boards: list[dict[str, Any]]) -> int:
    best_i, best_t = 0, None
    for i, b in enumerate(boards):
        t = b.get("chip_temp")
        if t is not None and (best_t is None or t > best_t):
            best_i, best_t = i, t
    return best_i


def board_totals(boards: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate multi-board stats; temps from the hottest board (ProductGuy semantics)."""
    if not boards:
        return {"nboards": 0, "hot_board": 0, "fans": [], "watts_dc": None}
    if len(boards) == 1:
        out = {name: boards[0].get(name) for name in _MINERINFO_FIELDS}
    else:
        out: dict[str, Any] = {}
        elapsed = [b["elapsed"] for b in boards if b.get("elapsed") is not None]
        out["elapsed"] = max(elapsed) if elapsed else None
        for key in ("mhs_av", "mhs_20s", "accepted", "rejected", "hw_errors"):
            vals = [b[key] for b in boards if b.get(key) is not None]
            out[key] = sum(vals) if vals else None
        nonced = [b.get("nonced") for b in boards]
        if (
            all(n is not None for n in nonced)
            and sum(nonced) > 0  # type: ignore[arg-type]
            and all(b.get("hw_errors") is not None for b in boards)
        ):
            out["hw_pct"] = 100.0 * sum(b["hw_errors"] for b in boards) / sum(nonced)  # type: ignore[arg-type]
        else:
            pcts = [b["hw_pct"] for b in boards if b.get("hw_pct") is not None]
            out["hw_pct"] = (sum(pcts) / len(pcts)) if pcts else None
        out["clock"] = next((b["clock"] for b in boards if b.get("clock") is not None), None)
        rebootcnt = [b["rebootcnt"] for b in boards if b.get("rebootcnt") is not None]
        out["rebootcnt"] = max(rebootcnt) if rebootcnt else None
        overheat = [b["overheat"] for b in boards if b.get("overheat") is not None]
        out["overheat"] = max(overheat) if overheat else None
        hot = boards[hottest_index(boards)]
        out["chip_temp"] = hot.get("chip_temp")
        out["chip_temp1"] = hot.get("chip_temp1")
        out["board_temp"] = hot.get("board_temp")
        fans = boards[0].get("fans") or []
        out["fan0"] = fans[0] if len(fans) > 0 else None
        out["fan1"] = fans[1] if len(fans) > 1 else None
    out["fans"] = list(boards[0].get("fans") or [])
    out["nboards"] = len(boards)
    out["hot_board"] = hottest_index(boards)
    v, c = boards[0].get("voltage_mv"), boards[0].get("current_ma")
    out["watts_dc"] = (v * c / 1e6) if (v is not None and c is not None) else None
    return out


def summarize_boards(boards: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact probe/fleet summary."""
    tot = board_totals(boards)
    return {
        "nboards": tot.get("nboards"),
        "hot_board": tot.get("hot_board"),
        "chip_temp_hot": tot.get("chip_temp"),
        "board_temp_hot": tot.get("board_temp"),
        "mhs_av": tot.get("mhs_av"),
        "accepted": tot.get("accepted"),
        "hw_errors": tot.get("hw_errors"),
        "clock": tot.get("clock"),
        "fans": tot.get("fans"),
        "nfans": len(tot.get("fans") or []),
        "watts_dc": tot.get("watts_dc"),
        "rebootcnt": tot.get("rebootcnt"),
        "boards": [
            {
                "id": b.get("board"),
                "status": b.get("status"),
                "mhs_av": b.get("mhs_av"),
                "chip_temp": b.get("chip_temp"),
                "board_temp": b.get("board_temp"),
                "clock": b.get("clock"),
                "hw_errors": b.get("hw_errors"),
                "accepted": b.get("accepted"),
            }
            for b in boards
        ],
    }
