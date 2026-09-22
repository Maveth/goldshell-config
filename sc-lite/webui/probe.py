#!/usr/bin/env python3
"""Probe an unknown Goldshell box and classify useful settings (no secrets in export)."""
from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from boards import parse_devs4028, summarize_boards
from miner_client import MinerClient, parse_plan
from models import profile_for

COMMON_PASSWORDS = ("123456789", "admin", "goldshell", "")

# Firmware care note (ProductGuy docs/firmware-api.md) — surface in probe markdown.
FIRMWARE_CARE = [
    "One request in flight; avoid poll bursts (token race / web backend crash).",
    "Stock UI Miner settings Save can clear manual clock — prefer plan/fan APIs.",
    "SC Lite: tempcontrol=false does NOT stop the ~85C fanctrl walk (keep ON; re-pulse kicks).",
]

FIRMWARE_CARE_BY_PROFILE: dict[str, list[str]] = {
    "sc-lite": [
        "tempcontrol=false does NOT stop the ~85C fanctrl walk — keep ON; re-pulse kicks.",
        "4028 voltage often drifts vs plan (e.g. plan 9100 → reported ~9330).",
        "Auth: raw Authorization <token> and Bearer both work (fw 2.2.0).",
    ],
    "sc5-pro-ii": [
        "Same mv_pv plan dialect as SC Lite — fan kick via plan RPM fields is likely.",
        "No temp_targets / no adjustable fan target (fixed basis).",
        "4028 voltage typically matches plan (unlike SC Lite drift).",
        "/mcb/status may answer without JWT; still send JWT for setting/dbg.",
        "Model string uses Unicode Ⅱ (U+2161) — normalize keys carefully.",
    ],
    "sc5-pro": [
        "Treat like SC5 Pro II until a plain SC5 Pro capture lands.",
    ],
}


def _pace(deep: bool, seconds: float = 2.0) -> None:
    if deep:
        time.sleep(seconds)


def _http_get_auth(
    url: str, token: str, *, bearer: bool, timeout: float = 12.0
) -> tuple[int | None, Any]:
    auth = f"Bearer {token}" if bearer else token
    req = urllib.request.Request(
        url, headers={"Authorization": auth, "Accept": "*/*"}, method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            code = getattr(r, "status", 200)
            try:
                return code, json.loads(raw)
            except Exception:
                return code, raw.decode("utf-8", "replace")[:800]
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = str(e)
        return e.code, body
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _plan_voltage_mv(plan: str) -> float | None:
    try:
        _mhz, mv, _fa, _fb, _pv = parse_plan(plan)
        return float(mv)
    except Exception:
        m = re.search(r"(\d+(?:\.\d+)?)\s*V", plan or "", re.I)
        if not m:
            return None
        try:
            v = float(m.group(1))
        except Exception:
            return None
        # float-V HS Box (~0.4) vs millivolt SC Lite/SC5 (~9100)
        return v * 1000.0 if v < 100 else v


def _measured_voltages(boards_summary: dict[str, Any] | None, bfg_devs: dict | None) -> list[float]:
    vals: list[float] = []
    # from summarize_boards boards list if present
    if isinstance(boards_summary, dict):
        for b in boards_summary.get("boards") or []:
            # boards summary may not include voltage — check raw bfg
            pass
    raw = (bfg_devs or {}).get("sample") if isinstance(bfg_devs, dict) else None
    # Prefer full DEVS via boards parser fields — re-read from stored boards if we add voltage later
    return vals


def _icinfo_board_chip_counts(payload: Any) -> dict[str, Any]:
    """Best-effort chip counts from /dbg/icinfo JSON."""
    out: dict[str, Any] = {"boards": [], "total_chips": None}
    if not isinstance(payload, dict):
        out["raw_type"] = type(payload).__name__
        return out
    table = payload.get("tabledata") or payload.get("data") or payload.get("boards")
    chips_total = 0
    found = False
    if isinstance(table, list):
        for i, row in enumerate(table):
            if not isinstance(row, dict):
                continue
            # common shapes: chipnum / chips / count
            n = row.get("chipnum") or row.get("chips") or row.get("chip_count") or row.get("count")
            try:
                n_i = int(n) if n is not None else None
            except Exception:
                n_i = None
            name = row.get("name") or row.get("board") or row.get("id") or i
            out["boards"].append({"id": name, "chips": n_i})
            if n_i is not None:
                chips_total += n_i
                found = True
    if found:
        out["total_chips"] = chips_total
    out["keys"] = sorted(payload.keys())[:40]
    return out


def _fanctrllog_snippet(text: str, limit: int = 8) -> list[str]:
    lines = [
        ln.strip()
        for ln in (text or "").splitlines()
        if "Fans Change" in ln or "Fan stay" in ln or "target_temp" in ln
    ]
    return lines[-limit:]


def _tcp_open(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _bfg(ip: str, cmd: str) -> dict[str, Any] | None:
    """BFG read using MinerClient hardened multi-packet parser when possible."""
    try:
        c = MinerClient(ip=ip, password="x", name="probe")
        return c.bfg(cmd)
    except Exception:
        return None


def _http_get(url: str, timeout: float = 5.0) -> tuple[int | None, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            raw = r.read()
            code = getattr(r, "status", 200)
            try:
                return code, json.loads(raw)
            except Exception:
                return code, raw.decode("utf-8", "replace")[:500]
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            body = str(e)
        return e.code, body
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def detect_plan_dialect(plan: str) -> dict[str, Any]:
    """Classify powerplan string without requiring prior model knowledge."""
    plan = (plan or "").strip()
    out: dict[str, Any] = {
        "raw": plan,
        "parseable_sc_lite_int_v": False,
        "parseable_hs_box_float_v": False,
        "suggested_profile": "unknown",
        "notes": [],
    }
    if not plan:
        out["notes"].append("empty manualPowerplan")
        return out

    # SC Lite style: 625 MHz 9100 V 40 RPM 40 RPM PV 9400
    try:
        parse_plan(plan)
        out["parseable_sc_lite_int_v"] = True
    except Exception as e:
        out["notes"].append(f"sc_lite_parse: {e}")

    # HS Box style: 750 MHz 0.41 V 50 RPM 50 RPM  (PV optional)
    m = re.match(
        r"(\d+(?:\.\d+)?)\s*MHz\s+(\d+(?:\.\d+)?)\s*V\s+(\d+)\s*RPM\s+(\d+)\s*RPM(?:\s+PV\s+(\d+(?:\.\d+)?))?",
        plan,
        re.I,
    )
    if m:
        mv = m.group(2)
        out["parseable_hs_box_float_v"] = "." in mv or float(mv) < 100
        out["hs_box_groups"] = {
            "mhz": m.group(1),
            "v": mv,
            "fan_a": int(m.group(3)),
            "fan_b": int(m.group(4)),
            "pv": m.group(5),
        }

    if out["parseable_sc_lite_int_v"] and not out["parseable_hs_box_float_v"]:
        out["suggested_profile"] = "sc-lite"
        out["notes"].append("Looks like SC Lite integer-V + PV plan")
    elif out["parseable_hs_box_float_v"] and not out["parseable_sc_lite_int_v"]:
        out["suggested_profile"] = "hs-box"
        out["notes"].append("Looks like HS Box float-V plan (PV may be omitted)")
    elif out["parseable_sc_lite_int_v"] and out["parseable_hs_box_float_v"]:
        # ambiguous — prefer float if V has decimal
        if "." in plan.split("V")[0].split()[-1] if "V" in plan else False:
            out["suggested_profile"] = "hs-box"
        else:
            # check V token
            vm = re.search(r"(\d+(?:\.\d+)?)\s*V", plan)
            if vm and "." in vm.group(1):
                out["suggested_profile"] = "hs-box"
            else:
                out["suggested_profile"] = "sc-lite"
        out["notes"].append("Both parsers matched — check V field carefully")
    else:
        out["suggested_profile"] = "unknown"
        out["notes"].append("Unrecognized powerplan — capture for GitHub issue/PR")

    return out


def classify_model(
    status: dict[str, Any] | None,
    dialect: dict[str, Any],
    boards_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Identify model using ProductGuy-style capability table + dialect/board hints."""
    model = ""
    fw = ""
    hardware = ""
    mcbversion = ""
    if isinstance(status, dict):
        model = str(status.get("model") or status.get("Model") or status.get("type") or "")
        fw = str(status.get("firmware") or status.get("Firmware") or status.get("version") or "")
        hardware = str(status.get("hardware") or "")
        mcbversion = str(status.get("mcbversion") or "")
        for k, v in status.items():
            kl = str(k).lower()
            if not model and "model" in kl:
                model = str(v)
            if not fw and ("firm" in kl or kl == "version"):
                fw = str(v)

    prof = profile_for(model or None)
    suggested = prof.get("profile_id") or "unknown"

    # Dialect can refine unknown / ambiguous
    dial = dialect.get("suggested_profile") or "unknown"
    if suggested == "unknown" and dial in ("sc-lite", "hs-box"):
        suggested = dial
        prof = {**prof, "profile_id": suggested}

    # Board-count hint: SC5 Pro II fixtures show 4 PGA boards + 4 fans
    nboards = (boards_summary or {}).get("nboards")
    nfans = (boards_summary or {}).get("nfans")
    if suggested in ("unknown", "sc5-pro") and nboards == 4 and (nfans or 0) >= 4:
        suggested = "sc5-pro-ii"
        prof = {**prof, "profile_id": "sc5-pro-ii", "boards": 4, "fans": 4}

    known = bool(prof.get("known")) or suggested in (
        "sc-lite",
        "hs-box",
        "sc-box",
        "sc5-pro",
        "sc5-pro-ii",
    )
    needs_capture = suggested in ("unknown",) or not prof.get("verified_string")
    support = prof.get("support_level") or (
        "fleet-monitor"
        if suggested in ("sc-lite", "hs-box", "sc5-pro-ii", "sc-box")
        else "probe-only"
    )

    return {
        "model": model or None,
        "firmware": fw or None,
        "hardware": hardware or None,
        "mcbversion": mcbversion or None,
        "suggested_profile": suggested,
        "known_family": known,
        "needs_community_capture": needs_capture,
        "support_level": support,
        "capability": {
            "name": prof.get("name"),
            "plan_dialect": prof.get("plan_dialect"),
            "board_source": prof.get("board_source"),
            "dbg_expected": prof.get("dbg_expected"),
            "fan_target": prof.get("fan_target"),
            "temp_target_basis": prof.get("temp_target_basis"),
            "plan_names": prof.get("plan_names"),
            "absent_signature": prof.get("absent_signature"),
            "rated_mhs": prof.get("rated_mhs"),
            "rated_watts": prof.get("rated_watts"),
            "boards_expected": prof.get("boards"),
            "fans_expected": prof.get("fans"),
            "source": prof.get("source"),
            "known": prof.get("known"),
            "verified_string": prof.get("verified_string"),
            "support_level": support,
            "fan_kick_tested": prof.get("fan_kick_tested"),
        },
        "boards_observed": {
            "nboards": nboards,
            "nfans": nfans,
            "chip_temp_hot": (boards_summary or {}).get("chip_temp_hot"),
            "mhs_av": (boards_summary or {}).get("mhs_av"),
            "watts_dc": (boards_summary or {}).get("watts_dc"),
            "clock": (boards_summary or {}).get("clock"),
        },
        "attribution": "models/boards adapted from crProductGuy/goldshell-box-tools-productguy (MIT)",
    }


def probe_miner(
    ip: str,
    password: str = "",
    try_common_passwords: bool = True,
    *,
    deep: bool = True,
) -> dict[str, Any]:
    """Probe a Goldshell box. Never echoes password in the result.

    deep=True (default): paced extra reads — auth Bearer vs raw, plan vs measured
    voltage, /dbg/icinfo chip counts, fanctrllog snippet, algosetting. One request
    at a time with sleeps to avoid the firmware token-race crash.
    """
    ip = ip.replace("http://", "").replace("https://", "").split("/")[0].strip()
    result: dict[str, Any] = {
        "ok": False,
        "ip": ip,
        "ts": time.time(),
        "deep": bool(deep),
        "ports": {},
        "bfg": {},
        "http": {},
        "login": {"ok": False},
        "dialect": {},
        "identity": {},
        "capabilities": {},
        "deep_findings": {},
        "github_issue_markdown": "",
        "error": None,
    }

    result["ports"] = {
        "80": _tcp_open(ip, 80),
        "4028": _tcp_open(ip, 4028),
        "22": _tcp_open(ip, 22),
    }

    # BFG (no auth)
    if result["ports"]["4028"]:
        for cmd in ("version", "summary", "devs", "pools", "config"):
            j = _bfg(ip, cmd)
            if j is None:
                result["bfg"][cmd] = None
                continue
            # trim large payloads
            if cmd == "devs":
                devs = j.get("DEVS") or []
                try:
                    boards = parse_devs4028(j)
                    bsum = summarize_boards(boards)
                except Exception as e:
                    boards = []
                    bsum = {"error": f"{type(e).__name__}: {e}"}
                result["bfg"]["devs"] = {
                    "count": len(devs),
                    "keys": sorted(devs[0].keys()) if devs else [],
                    "sample": {k: devs[0].get(k) for k in list(devs[0].keys())[:20]} if devs else None,
                    "boards": bsum,
                }
                result["boards"] = bsum
            elif cmd == "pools":
                pools = j.get("POOLS") or []
                result["bfg"]["pools"] = [
                    {
                        "id": p.get("POOL"),
                        "status": p.get("Status"),
                        "url": p.get("URL"),
                        "user": _redact_user(p.get("User")),
                        "priority": p.get("Priority"),
                        "stratum_active": p.get("Stratum Active"),
                        "accepted": p.get("Accepted"),
                    }
                    for p in pools
                ]
            elif cmd == "summary":
                s = (j.get("SUMMARY") or [{}])[0]
                result["bfg"]["summary"] = {
                    k: s.get(k)
                    for k in (
                        "Elapsed",
                        "MHS av",
                        "Accepted",
                        "Rejected",
                        "Hardware Errors",
                        "Difficulty Accepted",
                    )
                    if k in s
                }
            elif cmd == "version":
                result["bfg"]["version"] = j.get("VERSION") or j
            else:
                result["bfg"][cmd] = j

    # Unauth status attempt
    code, body = _http_get(f"http://{ip}/mcb/status")
    result["http"]["status_unauth"] = {"code": code, "body": _trim(body)}

    # Login attempts
    passwords: list[str] = []
    if password:
        passwords.append(password)
    if try_common_passwords:
        for p in COMMON_PASSWORDS:
            if p not in passwords:
                passwords.append(p)

    client = None
    used_common = False
    for i, pw in enumerate(passwords):
        if not pw and i > 0:
            continue
        try:
            c = MinerClient(ip=ip, password=pw or "x")
            c.login()
            client = c
            result["login"] = {
                "ok": True,
                "used_provided_password": bool(password) and i == 0 and pw == password,
                "used_common_password": bool(pw) and (not password or pw != password),
                # never return the password
            }
            used_common = result["login"]["used_common_password"]
            break
        except Exception as e:
            result["login"]["last_error"] = f"{type(e).__name__}: {e}"

    if client is None:
        result["error"] = "login failed — provide password"
        result["github_issue_markdown"] = render_github_issue(result)
        return result

    # Authenticated captures
    try:
        status = client.api("GET", "/mcb/status")
        result["http"]["status"] = _trim(status)
    except Exception as e:
        status = None
        result["http"]["status_error"] = f"{type(e).__name__}: {e}"

    setting = None
    try:
        setting = client.api("GET", "/mcb/setting")
        # redact nothing sensitive usually; strip if any
        if isinstance(setting, dict):
            safe = {k: setting.get(k) for k in setting.keys() if "pass" not in k.lower()}
            result["http"]["setting_keys"] = sorted(setting.keys())
            result["http"]["setting"] = safe
            plan = str(setting.get("manualPowerplan") or "")
            result["dialect"] = detect_plan_dialect(plan)
            result["http"]["tempcontrol"] = setting.get("tempcontrol")
            result["http"]["manual"] = setting.get("manual")
            result["http"]["powerplans_count"] = len(setting.get("powerplans") or [])
        else:
            result["http"]["setting"] = _trim(setting)
            result["dialect"] = detect_plan_dialect("")
    except Exception as e:
        result["http"]["setting_error"] = f"{type(e).__name__}: {e}"
        result["dialect"] = detect_plan_dialect("")

    try:
        pools = client.api("GET", "/mcb/pools")
        if isinstance(pools, list):
            result["http"]["pools"] = [
                {
                    "url": p.get("url"),
                    "user": _redact_user(p.get("user")),
                    "active": p.get("active"),
                    "pool-priority": p.get("pool-priority"),
                }
                for p in pools
                if isinstance(p, dict)
            ]
        else:
            result["http"]["pools"] = _trim(pools)
    except Exception as e:
        result["http"]["pools_error"] = f"{type(e).__name__}: {e}"

    # Optional /dbg/minerinfo (SC5 / SC-BOX often open; SC Lite often locked)
    dbg_info: dict[str, Any] = {"attempted": False}
    try:
        code, body = _http_get(f"http://{ip}/dbg/minerinfo")
        # unauth probe first
        dbg_info = {"attempted": True, "unauth_code": code}
        if code == 200 and isinstance(body, str) and "[PGA" in body:
            from boards import parse_minerinfo_boards, summarize_boards as _sumb

            dbg_info["boards"] = _sumb(parse_minerinfo_boards(body))
            dbg_info["pga_blocks"] = dbg_info["boards"].get("nboards")
        # authed
        try:
            raw = client.api("GET", "/dbg/minerinfo")
            if isinstance(raw, str) and raw.strip():
                from boards import parse_minerinfo_boards, summarize_boards as _sumb

                dbg_info["authed"] = True
                dbg_info["boards"] = _sumb(parse_minerinfo_boards(raw))
            elif isinstance(raw, dict):
                dbg_info["authed_json_keys"] = sorted(raw.keys())[:40]
        except Exception as e:
            dbg_info["authed_error"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        dbg_info["error"] = f"{type(e).__name__}: {e}"
    result["http"]["dbg_minerinfo"] = dbg_info

    boards_summary = result.get("boards") or (dbg_info.get("boards") if isinstance(dbg_info, dict) else None)

    result["identity"] = classify_model(
        status if isinstance(status, dict) else None,
        result.get("dialect") or {},
        boards_summary if isinstance(boards_summary, dict) else None,
    )

    ident = result["identity"]
    cap = ident.get("capability") or {}
    profile_id = ident.get("suggested_profile") or "unknown"
    # Named plan levels (SC5 Pro II / table)
    plan_names = cap.get("plan_names")
    if isinstance(setting, dict):
        result["http"]["plan_levels"] = [
            {
                "level": p.get("level"),
                "name": (plan_names or {}).get(p.get("level")) if isinstance(plan_names, dict) else None,
                "info": p.get("info"),
            }
            for p in (setting.get("powerplans") or [])
            if isinstance(p, dict)
        ]
        result["http"]["has_temp_targets"] = "temp_targets" in setting

    # --- Deep findings (paced) ---
    deep_out: dict[str, Any] = {}
    token = getattr(client, "_token", None) or ""

    # Plan vs measured voltage (from 4028 board rows)
    plan_raw = (result.get("dialect") or {}).get("raw") or ""
    plan_mv = _plan_voltage_mv(plan_raw)
    measured: list[float] = []
    try:
        # Re-parse boards for voltage fields
        if result.get("ports", {}).get("4028"):
            jdevs = _bfg(ip, "devs")
            if jdevs:
                for b in parse_devs4028(jdevs):
                    if b.get("voltage_mv") is not None:
                        measured.append(float(b["voltage_mv"]))
    except Exception as e:
        deep_out["voltage_parse_error"] = f"{type(e).__name__}: {e}"
    if plan_mv is not None and measured:
        avg_m = sum(measured) / len(measured)
        deep_out["voltage"] = {
            "plan_mv": plan_mv,
            "measured_mv": measured,
            "measured_avg_mv": avg_m,
            "matches_plan": abs(avg_m - plan_mv) < 50,
            "delta_mv": avg_m - plan_mv,
        }
    elif plan_mv is not None:
        deep_out["voltage"] = {"plan_mv": plan_mv, "measured_mv": measured}

    if deep and token:
        _pace(deep)
        # Auth forms
        code_raw, _ = _http_get_auth(f"http://{ip}/mcb/status", token, bearer=False)
        _pace(deep)
        code_bearer, _ = _http_get_auth(f"http://{ip}/mcb/status", token, bearer=True)
        deep_out["auth"] = {
            "raw_authorization": code_raw,
            "bearer_authorization": code_bearer,
            "status_unauth": (result.get("http") or {}).get("status_unauth", {}).get("code"),
        }

        _pace(deep)
        try:
            algo = client.api("GET", "/mcb/algosetting")
            deep_out["algosetting"] = _trim(algo, 1200)
        except Exception as e:
            deep_out["algosetting_error"] = f"{type(e).__name__}: {e}"

        _pace(deep)
        try:
            ici = client.api("GET", "/dbg/icinfo")
            deep_out["icinfo"] = _icinfo_board_chip_counts(ici)
        except Exception as e:
            deep_out["icinfo_error"] = f"{type(e).__name__}: {e}"

        _pace(deep)
        try:
            flog = client.api("GET", "/dbg/fanctrllog")
            text = flog.decode("utf-8", "replace") if isinstance(flog, (bytes, bytearray)) else str(flog)
            deep_out["fanctrllog_snippet"] = _fanctrllog_snippet(text)
            deep_out["fanctrllog_bytes"] = len(text)
            # peek target_temp mentions
            tgt = re.findall(r"target_temp\s*:\s*([0-9.]+)", text)
            deep_out["fanctrllog_target_temps"] = sorted({t for t in tgt})[-5:]
        except Exception as e:
            deep_out["fanctrllog_error"] = f"{type(e).__name__}: {e}"

        _pace(deep)
        try:
            code_cg, body_cg = _http_get_auth(
                f"http://{ip}/mcb/cgminer?cgminercmd=devs", token, bearer=False
            )
            deep_out["cgminer_devs"] = {
                "code": code_cg,
                "ok": code_cg == 200,
                "preview": _trim(body_cg, 400),
            }
        except Exception as e:
            deep_out["cgminer_devs_error"] = f"{type(e).__name__}: {e}"

    result["deep_findings"] = deep_out

    care = list(FIRMWARE_CARE)
    care.extend(FIRMWARE_CARE_BY_PROFILE.get(profile_id, []))

    # Capabilities heuristic
    result["capabilities"] = {
        "bfg_4028": bool(result["ports"].get("4028")),
        "http_80": bool(result["ports"].get("80")),
        "ssh_22": bool(result["ports"].get("22")),
        "jwt_login": True,
        "read_setting": "setting" in result["http"],
        "read_pools": "pools" in result["http"],
        "has_temp_targets": bool(result["http"].get("has_temp_targets")),
        "fan_kick_likely": bool((result.get("dialect") or {}).get("parseable_sc_lite_int_v"))
        or bool((result.get("dialect") or {}).get("parseable_hs_box_float_v")),
        "fan_target_adjustable": bool(cap.get("fan_target")),
        "temp_target_basis": cap.get("temp_target_basis"),
        "board_source": cap.get("board_source"),
        "dbg_expected": cap.get("dbg_expected"),
        "dbg_minerinfo_ok": bool(
            isinstance(dbg_info, dict)
            and (dbg_info.get("authed") or dbg_info.get("pga_blocks"))
        ),
        "absent_signature": bool(cap.get("absent_signature")),
        "nboards_observed": (boards_summary or {}).get("nboards") if isinstance(boards_summary, dict) else None,
        "nfans_observed": (boards_summary or {}).get("nfans") if isinstance(boards_summary, dict) else None,
        "watts_dc_observed": (boards_summary or {}).get("watts_dc") if isinstance(boards_summary, dict) else None,
        "voltage_matches_plan": (deep_out.get("voltage") or {}).get("matches_plan"),
        "auth_raw_ok": (deep_out.get("auth") or {}).get("raw_authorization") == 200,
        "auth_bearer_ok": (deep_out.get("auth") or {}).get("bearer_authorization") == 200,
        "icinfo_total_chips": (deep_out.get("icinfo") or {}).get("total_chips"),
        "suggested_webui_profile": profile_id,
        "support_level": ident.get("support_level"),
        "used_common_password_hint": used_common,
        "firmware_care": care,
        "soft_watchdog_ready": True,
        "power_cycle_plug": False,
        "deep": bool(deep),
    }

    result["ok"] = True
    result["github_issue_markdown"] = render_github_issue(result)
    return result


def _redact_user(user: Any) -> str | None:
    if user is None:
        return None
    u = str(user)
    if "." in u:
        addr, worker = u.split(".", 1)
        if len(addr) > 12:
            return addr[:8] + "…" + addr[-4:] + "." + worker
        return u
    if len(u) > 16:
        return u[:8] + "…" + u[-4:]
    return u


def _trim(obj: Any, limit: int = 2500) -> Any:
    if isinstance(obj, (dict, list)):
        s = json.dumps(obj, default=str)
        if len(s) <= limit:
            return obj
        return {"_truncated": True, "preview": s[:limit]}
    s = str(obj)
    return s if len(s) <= limit else s[:limit] + "…"


def render_github_issue(probe: dict[str, Any]) -> str:
    """Markdown suitable for goldshell-config issue/PR — no passwords."""
    ident = probe.get("identity") or {}
    dialect = probe.get("dialect") or {}
    caps = probe.get("capabilities") or {}
    ports = probe.get("ports") or {}
    bfg = probe.get("bfg") or {}
    http = probe.get("http") or {}

    model = ident.get("model") or "(unknown)"
    fw = ident.get("firmware") or "(unknown)"
    profile = ident.get("suggested_profile") or "unknown"
    plan = dialect.get("raw") or ""

    cap = ident.get("capability") or {}
    boards = probe.get("boards") or bfg.get("devs", {}).get("boards") or {}

    lines = [
        f"### Goldshell probe capture — `{model}` / fw `{fw}`",
        "",
        "Auto-generated by `sc-lite/webui` probe (passwords redacted).",
        "Model/board tables adapted from "
        "[crProductGuy/goldshell-box-tools-productguy](https://github.com/crProductGuy/goldshell-box-tools-productguy) (MIT).",
        "",
        "## Identity",
        f"- **IP probed:** `{probe.get('ip')}` (private — optional to omit when filing)",
        f"- **Model:** `{model}`",
        f"- **Firmware:** `{fw}`",
        f"- **Hardware / MCB:** `{ident.get('hardware')}` / `{ident.get('mcbversion')}`",
        f"- **Suggested profile:** `{profile}`",
        f"- **Support level:** `{ident.get('support_level') or caps.get('support_level')}`",
        f"- **Known family:** `{ident.get('known_family')}`",
        f"- **Needs community capture:** `{ident.get('needs_community_capture')}`",
        f"- **Deep probe:** `{probe.get('deep')}`",
        f"- **Capability source:** {cap.get('source') or '(n/a)'}",
        "",
        "## Ports",
        f"- 80/http: `{ports.get('80')}`",
        f"- 4028/bfg: `{ports.get('4028')}`",
        f"- 22/ssh: `{ports.get('22')}`",
        "",
        "## Boards (4028 / dbg)",
        f"- nboards: `{boards.get('nboards')}` · nfans: `{boards.get('nfans')}` · "
        f"hot chip: `{boards.get('chip_temp_hot')}` · MHS av: `{boards.get('mhs_av')}` · "
        f"watts_dc: `{boards.get('watts_dc')}`",
        "",
        "## Powerplan dialect",
        f"- raw: `{plan}`",
        f"- table dialect: `{cap.get('plan_dialect')}`",
        f"- SC Lite int-V parse: `{dialect.get('parseable_sc_lite_int_v')}`",
        f"- HS Box float-V parse: `{dialect.get('parseable_hs_box_float_v')}`",
        f"- plan names: `{cap.get('plan_names')}`",
        f"- has_temp_targets: `{http.get('has_temp_targets')}`",
        f"- notes: {', '.join(dialect.get('notes') or []) or '(none)'}",
        "",
        "## Capabilities (heuristic)",
    ]
    for k, v in caps.items():
        if k == "firmware_care":
            continue
        lines.append(f"- `{k}`: `{v}`")
    lines += ["", "### Firmware care", *[f"- {x}" for x in (caps.get("firmware_care") or FIRMWARE_CARE)]]

    deep = probe.get("deep_findings") or {}
    if deep:
        lines += ["", "## Deep findings", "```json", json.dumps(deep, indent=2, default=str)[:3500], "```"]

    lines += ["", "## BFG summary", "```json", json.dumps(bfg.get("summary") or {}, indent=2), "```"]
    if boards:
        lines += ["", "## Boards summary", "```json", json.dumps(boards, indent=2)[:2500], "```"]
    if bfg.get("devs"):
        slim = {k: v for k, v in (bfg.get("devs") or {}).items() if k != "boards"}
        lines += ["", "## BFG devs sample keys", "```json", json.dumps(slim, indent=2)[:2000], "```"]
    if http.get("setting_keys"):
        lines += ["", "## /mcb/setting keys", "```", ", ".join(http.get("setting_keys") or []), "```"]
    if http.get("plan_levels"):
        lines += ["", "## Plan levels", "```json", json.dumps(http.get("plan_levels"), indent=2), "```"]
    if http.get("pools"):
        lines += ["", "## Pools (users redacted)", "```json", json.dumps(http.get("pools"), indent=2), "```"]

    lines += [
        "",
        "## Ask / PR ask",
        f"- [x] Model folder suggestion: `{profile}`",
        "- [ ] Confirm fan-kick safe with this plan dialect (live kick once)",
        "- [ ] Soft-watchdog: enable dry_run first?",
        "- [ ] Any fw-specific quirks?",
        "",
        f"_Probe ts: {probe.get('ts')} · deep={probe.get('deep')}_",
    ]
    return "\n".join(lines)
