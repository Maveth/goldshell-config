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

from miner_client import MinerClient, parse_plan

COMMON_PASSWORDS = ("123456789", "admin", "goldshell", "")


def _tcp_open(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _bfg(ip: str, cmd: str) -> dict[str, Any] | None:
    try:
        s = socket.create_connection((ip, 4028), timeout=4)
        s.sendall((json.dumps({"command": cmd}) + "\n").encode())
        s.settimeout(4)
        chunks: list[bytes] = []
        try:
            while True:
                b = s.recv(65536)
                if not b:
                    break
                chunks.append(b)
        except Exception:
            pass
        s.close()
        raw = b"".join(chunks).decode("utf-8", "replace").rstrip("\x00")
        return json.loads(raw)
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


def classify_model(status: dict[str, Any] | None, dialect: dict[str, Any]) -> dict[str, Any]:
    model = ""
    fw = ""
    if isinstance(status, dict):
        model = str(status.get("model") or status.get("Model") or status.get("type") or "")
        fw = str(status.get("firmware") or status.get("Firmware") or status.get("version") or "")
        # sometimes nested
        for k, v in status.items():
            kl = str(k).lower()
            if not model and "model" in kl:
                model = str(v)
            if not fw and ("firm" in kl or "version" in kl):
                fw = str(v)

    ml = model.lower()
    suggested = dialect.get("suggested_profile") or "unknown"
    if "sc lite" in ml or "sclite" in ml or "sc-lite" in ml:
        suggested = "sc-lite"
    elif "hs box" in ml or "hs-box" in ml or "hsbox" in ml:
        suggested = "hs-box"
    elif "sc5" in ml or "sc pro" in ml or "sc-pro" in ml:
        suggested = "sc-pro"

    return {
        "model": model or None,
        "firmware": fw or None,
        "suggested_profile": suggested,
        "known_family": suggested in ("sc-lite", "hs-box"),
        "needs_community_capture": suggested in ("unknown", "sc-pro"),
    }


def probe_miner(ip: str, password: str = "", try_common_passwords: bool = True) -> dict[str, Any]:
    """Full probe. Never echoes password in the result."""
    ip = ip.replace("http://", "").replace("https://", "").split("/")[0].strip()
    result: dict[str, Any] = {
        "ok": False,
        "ip": ip,
        "ts": time.time(),
        "ports": {},
        "bfg": {},
        "http": {},
        "login": {"ok": False},
        "dialect": {},
        "identity": {},
        "capabilities": {},
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
                result["bfg"]["devs"] = {
                    "count": len(devs),
                    "keys": sorted(devs[0].keys()) if devs else [],
                    "sample": {k: devs[0].get(k) for k in list(devs[0].keys())[:20]} if devs else None,
                }
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

    result["identity"] = classify_model(
        status if isinstance(status, dict) else None,
        result.get("dialect") or {},
    )

    # Capabilities heuristic
    result["capabilities"] = {
        "bfg_4028": bool(result["ports"].get("4028")),
        "http_80": bool(result["ports"].get("80")),
        "ssh_22": bool(result["ports"].get("22")),
        "jwt_login": True,
        "read_setting": "setting" in result["http"],
        "read_pools": "pools" in result["http"],
        "fan_kick_likely": bool((result.get("dialect") or {}).get("parseable_sc_lite_int_v"))
        or bool((result.get("dialect") or {}).get("parseable_hs_box_float_v")),
        "suggested_webui_profile": (result.get("identity") or {}).get("suggested_profile"),
        "used_common_password_hint": used_common,
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

    lines = [
        f"### Goldshell probe capture — `{model}` / fw `{fw}`",
        "",
        "Auto-generated by `sc-lite/webui` probe (passwords redacted).",
        "",
        "## Identity",
        f"- **IP probed:** `{probe.get('ip')}` (private — optional to omit when filing)",
        f"- **Model:** `{model}`",
        f"- **Firmware:** `{fw}`",
        f"- **Suggested profile:** `{profile}`",
        f"- **Known family:** `{ident.get('known_family')}`",
        "",
        "## Ports",
        f"- 80/http: `{ports.get('80')}`",
        f"- 4028/bfg: `{ports.get('4028')}`",
        f"- 22/ssh: `{ports.get('22')}`",
        "",
        "## Powerplan dialect",
        f"- raw: `{plan}`",
        f"- SC Lite int-V parse: `{dialect.get('parseable_sc_lite_int_v')}`",
        f"- HS Box float-V parse: `{dialect.get('parseable_hs_box_float_v')}`",
        f"- notes: {', '.join(dialect.get('notes') or []) or '(none)'}",
        "",
        "## Capabilities (heuristic)",
    ]
    for k, v in caps.items():
        lines.append(f"- `{k}`: `{v}`")

    lines += ["", "## BFG summary", "```json", json.dumps(bfg.get("summary") or {}, indent=2), "```"]
    if bfg.get("devs"):
        lines += ["", "## BFG devs sample keys", "```json", json.dumps(bfg.get("devs"), indent=2)[:2000], "```"]
    if http.get("setting_keys"):
        lines += ["", "## /mcb/setting keys", "```", ", ".join(http.get("setting_keys") or []), "```"]
    if http.get("pools"):
        lines += ["", "## Pools (users redacted)", "```json", json.dumps(http.get("pools"), indent=2), "```"]

    lines += [
        "",
        "## Ask / PR ask",
        "- [ ] Confirm model folder (`sc-lite` / `hs-box` / `sc5-pro` / new)",
        "- [ ] Confirm fan-kick safe with this plan dialect",
        "- [ ] Any fw-specific quirks?",
        "",
        f"_Probe ts: {probe.get('ts')}_",
    ]
    return "\n".join(lines)
