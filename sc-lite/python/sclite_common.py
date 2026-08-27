#!/usr/bin/env python3
"""Shared Goldshell SC Lite HTTP + JWT helpers (fw 2.2.0)."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from Crypto.Cipher import AES

# Prefer env SCLITE_IP / SCLITE_PASSWORD (or temp-manager JSON). No lab IP baked in.
DEFAULT_IP = os.environ.get("SCLITE_IP", "")
DEFAULT_PASSWORD = os.environ.get("SCLITE_PASSWORD", "")
KEY = b"!" * 16  # CryptoJS Utf8.parse("!!!!!!!!!!!!!!!!") — cipher key, not login password
IV = b"\0" * 16

_token: str | None = None


def configure(ip: str | None = None, password: str | None = None) -> None:
    """Override miner IP / password (also used by temp manager config)."""
    global _token
    if ip:
        os.environ["SCLITE_IP"] = ip
    if password is not None:
        os.environ["SCLITE_PASSWORD"] = password
    _token = None  # force re-login next call


def host() -> str:
    ip = os.environ.get("SCLITE_IP", DEFAULT_IP)
    if not ip:
        raise RuntimeError(
            "SCLITE_IP is not set. export SCLITE_IP=192.168.x.x "
            "(or set miner.ip in the temp-manager JSON)"
        )
    if ip.startswith("http://") or ip.startswith("https://"):
        return ip.rstrip("/")
    return f"http://{ip}"


def zero_pad(data: bytes, block: int = 16) -> bytes:
    return data + (b"\0" * ((-len(data)) % block))


def encrypt_password(password: str) -> str:
    ct = AES.new(KEY, AES.MODE_CBC, IV).encrypt(zero_pad(password.encode()))
    return ct.hex()


def login(password: str | None = None) -> str:
    global _token
    plain = password if password is not None else os.environ.get("SCLITE_PASSWORD", DEFAULT_PASSWORD)
    if not plain:
        raise RuntimeError(
            "SCLITE_PASSWORD is not set. export SCLITE_PASSWORD=... "
            "(or set miner.password in the temp-manager JSON)"
        )
    pw = encrypt_password(plain)
    qs = urllib.parse.urlencode(
        {"username": "admin", "password": pw, "cipher": "true"}
    )
    with urllib.request.urlopen(f"{host()}/user/login?{qs}", timeout=12) as r:
        j = json.loads(r.read())
    token = j.get("JWT Token") or j.get("token")
    if not token:
        raise RuntimeError(f"login failed: {j}")
    _token = token
    return token


def api(method: str, path: str, body: dict | None = None, retries: int = 3) -> Any:
    global _token
    last_err: Exception | None = None
    for _ in range(retries):
        if _token is None:
            login()
        assert _token is not None
        data = None
        headers = {"Authorization": _token, "Accept": "*/*"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            host() + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
            if not raw:
                return None
            try:
                return json.loads(raw)
            except Exception:
                return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 401:
                login()
                continue
            raise
        except Exception as e:
            last_err = e
            try:
                login()
            except Exception:
                pass
    raise RuntimeError(f"API {method} {path} failed: {last_err}")


def get_setting() -> dict:
    s = api("GET", "/mcb/setting")
    if not isinstance(s, dict):
        raise RuntimeError(f"bad setting: {s!r}")
    return s


def put_setting(payload: dict) -> None:
    api("PUT", "/mcb/setting", payload)


def soft_restart(timeout: float = 8.0) -> str:
    """Request soft restart via GET /mcb/restart.

    Often drops the TCP connection immediately when reboot starts.
    Returns a short status string. Does NOT call /mcb/facrst.
    """
    global _token
    if _token is None:
        login()
    assert _token is not None
    req = urllib.request.Request(
        host() + "/mcb/restart",
        headers={"Authorization": _token, "Accept": "*/*"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            _ = r.read()
            return f"restart HTTP {getattr(r, 'status', 200)}"
    except Exception as e:
        # Connection drop mid-restart is common/expected
        msg = str(e).lower()
        if "closed" in msg or "reset" in msg or "timed out" in msg or "timeout" in msg:
            return f"restart requested ({e.__class__.__name__})"
        raise


def wait_until_up(timeout_s: float = 120.0, poll_s: float = 5.0) -> bool:
    """Re-login + GET setting until success or timeout."""
    global _token
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            _token = None
            login()
            get_setting()
            return True
        except Exception:
            time.sleep(poll_s)
    return False


def parse_plan(plan: str) -> tuple[int, int, int, int, int]:
    m = re.match(
        r"(\d+)\s*MHz\s+(\d+)\s*V\s+(\d+)\s*RPM\s+(\d+)\s*RPM\s+PV\s+(\d+)",
        plan or "",
    )
    if not m:
        raise RuntimeError(f"cannot parse powerplan: {plan!r}")
    return tuple(map(int, m.groups()))  # type: ignore[return-value]


def build_plan(mhz: int, mv: int, fan_a: int, fan_b: int, pv: int) -> str:
    return f"{mhz} MHz {mv} V {fan_a} RPM {fan_b} RPM PV {pv}"


def parse_temp(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    num = "".join(ch for ch in str(val) if ch.isdigit() or ch == ".")
    return float(num) if num else None


def board_snapshot() -> dict:
    devs = api("GET", "/mcb/cgminer?cgminercmd=devs")
    boards = []
    if isinstance(devs, dict):
        for d in devs.get("data", []):
            boards.append(
                {
                    "id": d.get("id"),
                    "temp": parse_temp(d.get("temp")),
                    "fans": d.get("fanspeed"),
                    "hr_ths": (d.get("hashrate") or 0) / 1e6,
                }
            )
    temps = [b["temp"] for b in boards if b["temp"] is not None]
    return {
        "boards": boards,
        "max_t": max(temps) if temps else None,
        "min_t": min(temps) if temps else None,
    }


def print_snapshot(label: str = "NOW") -> dict:
    setting = get_setting()
    boards = board_snapshot()
    print(
        f"[{label}] manual={setting.get('manual')} tc={setting.get('tempcontrol')} "
        f"plan={setting.get('manualPowerplan')}"
    )
    print(f"[{label}] maxT={boards.get('max_t')} minT={boards.get('min_t')}")
    for b in boards["boards"]:
        print(
            f"  board {b['id']}: temp={b['temp']} fans={b['fans']} "
            f"hr={b['hr_ths']:.3f} TH/s"
        )
    return {"setting": setting, "boards": boards}
