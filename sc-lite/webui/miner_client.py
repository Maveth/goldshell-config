#!/usr/bin/env python3
"""Per-miner Goldshell SC Lite client (thread-safe; no process-global token)."""
from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from Crypto.Cipher import AES

KEY = b"!" * 16
IV = b"\0" * 16
BFG_PORT = 4028


def _zero_pad(data: bytes, block: int = 16) -> bytes:
    return data + (b"\0" * ((-len(data)) % block))


def encrypt_password(password: str) -> str:
    return AES.new(KEY, AES.MODE_CBC, IV).encrypt(_zero_pad(password.encode())).hex()


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


@dataclass
class MinerClient:
    ip: str
    password: str
    name: str = ""
    id: str = ""
    _token: str | None = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        self.ip = self.ip.replace("http://", "").replace("https://", "").split("/")[0]
        if not self.id:
            self.id = self.ip
        if not self.name:
            self.name = self.ip

    def host(self) -> str:
        return f"http://{self.ip}"

    def login(self) -> str:
        with self._lock:
            pw = encrypt_password(self.password)
            qs = urllib.parse.urlencode(
                {"username": "admin", "password": pw, "cipher": "true"}
            )
            with urllib.request.urlopen(f"{self.host()}/user/login?{qs}", timeout=12) as r:
                j = json.loads(r.read())
            token = j.get("JWT Token") or j.get("token")
            if not token:
                raise RuntimeError(f"login failed: {j}")
            self._token = token
            return token

    def api(self, method: str, path: str, body: dict | list | None = None, retries: int = 3) -> Any:
        with self._lock:
            last_err: Exception | None = None
            for _ in range(retries):
                if self._token is None:
                    self.login()
                assert self._token is not None
                data = None
                headers = {"Authorization": self._token, "Accept": "*/*"}
                if body is not None:
                    data = json.dumps(body).encode()
                    headers["Content-Type"] = "application/json"
                req = urllib.request.Request(
                    self.host() + path, data=data, headers=headers, method=method
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
                        self._token = None
                        continue
                    raise
                except Exception as e:
                    last_err = e
                    self._token = None
            raise RuntimeError(f"API {method} {path} failed: {last_err}")

    @staticmethod
    def _parse_bfg_json(raw: bytes | str) -> dict[str, Any]:
        """Goldshell :4028 often null-terminates or returns slightly broken JSON."""
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", "replace")
        else:
            text = raw
        text = text.replace("\x00", "").strip()
        if not text:
            raise RuntimeError("empty bfg response")
        # Try straight parse
        try:
            out = json.loads(text)
            if isinstance(out, dict):
                return out
        except json.JSONDecodeError:
            pass
        # Truncate to last closing brace of first object
        if text[0] == "{":
            depth = 0
            in_str = False
            esc = False
            for i, ch in enumerate(text):
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            out = json.loads(text[: i + 1])
                            if isinstance(out, dict):
                                return out
                        except json.JSONDecodeError:
                            break
        # Last resort: replace NaN/Infinity which some firmwares emit
        cleaned = (
            text.replace("NaN", "null")
            .replace("Infinity", "null")
            .replace("-Infinity", "null")
        )
        out = json.loads(cleaned)
        if not isinstance(out, dict):
            raise RuntimeError("bfg response not an object")
        return out

    @staticmethod
    def _bfg_json_complete(buf: bytes) -> bool:
        """True when buf holds a full top-level JSON object (ignore trailing NULs)."""
        text = buf.replace(b"\x00", b"").strip()
        if not text.startswith(b"{"):
            return False
        depth = 0
        in_str = False
        esc = False
        for ch in text:
            if in_str:
                if esc:
                    esc = False
                elif ch == ord("\\"):
                    esc = True
                elif ch == ord('"'):
                    in_str = False
                continue
            if ch == ord('"'):
                in_str = True
                continue
            if ch == ord("{"):
                depth += 1
            elif ch == ord("}"):
                depth -= 1
                if depth == 0:
                    return True
        return False

    def bfg(self, cmd: str, parameter: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"command": cmd}
        if parameter is not None:
            payload["parameter"] = parameter
        last_err: Exception | None = None
        for _attempt in range(3):
            try:
                s = socket.create_connection((self.ip, BFG_PORT), timeout=5)
                s.sendall((json.dumps(payload) + "\n").encode())
                # Goldshell often splits a multi-KB reply across several TCP
                # segments; never stop on the first short packet.
                s.settimeout(2.5)
                chunks: list[bytes] = []
                try:
                    while True:
                        b = s.recv(65536)
                        if not b:
                            break
                        chunks.append(b)
                        joined = b"".join(chunks)
                        if b"\x00" in joined or self._bfg_json_complete(joined):
                            break
                except socket.timeout:
                    pass
                except Exception:
                    pass
                s.close()
                return self._parse_bfg_json(b"".join(chunks))
            except Exception as e:
                last_err = e
                time.sleep(0.2)
        raise RuntimeError(f"bfg {cmd} failed: {last_err}")

    def ping(self) -> dict[str, Any]:
        """Lightweight reachability via :4028 summary (no JWT)."""
        try:
            summ = (self.bfg("summary").get("SUMMARY") or [{}])[0]
            return {"ok": True, "elapsed": summ.get("Elapsed"), "mhs": summ.get("MHS av")}
        except Exception as e:
            # JWT fallback — miner still "up" if web API answers
            try:
                st = self.api("GET", "/mcb/status")
                return {
                    "ok": True,
                    "via": "jwt",
                    "status": st if isinstance(st, dict) else None,
                    "bfg_error": f"{type(e).__name__}: {e}",
                }
            except Exception as e2:
                return {
                    "ok": False,
                    "error": f"bfg: {type(e).__name__}: {e}; jwt: {type(e2).__name__}: {e2}",
                }

    def snapshot(self) -> dict[str, Any]:
        """Combined status for UI cards / detail."""
        out: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "ip": self.ip,
            "ok": False,
            "ts": time.time(),
        }
        summary: dict[str, Any] = {}
        pools: list[dict[str, Any]] = []
        devs: list[dict[str, Any]] = []
        bfg_ok = False
        try:
            summary = (self.bfg("summary").get("SUMMARY") or [{}])[0]
            pools = list(self.bfg("pools").get("POOLS") or [])
            devs = list(self.bfg("devs").get("DEVS") or [])
            bfg_ok = True
        except Exception as e:
            out["bfg_error"] = f"bfg: {type(e).__name__}: {e}"
            # Fall through — JWT /mcb can still prove the miner is up.

        # working pool = newest last-share among Alive
        working = None
        candidates = []
        for p in pools:
            if str(p.get("Status")) != "Alive":
                continue
            try:
                last = float(p.get("Last Share Time") or 0)
                idx = int(p.get("POOL"))
            except Exception:
                continue
            if last > 0:
                candidates.append((last, idx, p))
        if candidates:
            candidates.sort(reverse=True)
            working = candidates[0][2]

        temps = []
        fans = []
        mhs = []
        for d in devs:
            # Goldshell SC Lite: tstemp-0/1/2 (and sometimes Temperature)
            board_temps = []
            if d.get("Temperature") is not None:
                board_temps.append(float(d["Temperature"]))
            for k, v in d.items():
                if str(k).startswith("tstemp-") and v is not None:
                    try:
                        board_temps.append(float(v))
                    except Exception:
                        pass
            temps.extend(board_temps)
            # fan0..fanN numeric fields, or Fans string
            for k, v in d.items():
                if re.fullmatch(r"fan\d+", str(k)) and v is not None:
                    try:
                        fans.append(int(float(v)))
                    except Exception:
                        pass
            fs = str(d.get("Fans") or d.get("Fan Speed") or "")
            for part in re.findall(r"\d+", fs):
                fans.append(int(part))
            if d.get("MHS av") is not None:
                mhs.append(float(d["MHS av"]))
            elif d.get("MHS 5s") is not None:
                mhs.append(float(d["MHS 5s"]))

        def _board_temp(d: dict) -> float | None:
            vals = []
            if d.get("Temperature") is not None:
                vals.append(float(d["Temperature"]))
            for k, v in d.items():
                if str(k).startswith("tstemp-") and v is not None:
                    try:
                        vals.append(float(v))
                    except Exception:
                        pass
            return max(vals) if vals else None

        def _board_fans(d: dict) -> str:
            parts = []
            for i in range(8):
                if f"fan{i}" in d and d[f"fan{i}"] is not None:
                    parts.append(str(int(float(d[f"fan{i}"]))))
            if parts:
                return " ".join(parts)
            return str(d.get("Fans") or d.get("Fan Speed") or "")

        if bfg_ok:
            out.update(
                {
                    "ok": True,
                    "elapsed": summary.get("Elapsed"),
                    "accepted": summary.get("Accepted"),
                    "rejected": summary.get("Rejected"),
                    "hw": summary.get("Hardware Errors"),
                    "mhs_av": summary.get("MHS av") or (sum(mhs) if mhs else None),
                    "temp_max": max(temps) if temps else None,
                    "temp_avg": (sum(temps) / len(temps)) if temps else None,
                    "temps": temps,
                    "fan_avg": (sum(fans) / len(fans)) if fans else None,
                    "fans": fans[:8],
                    "devs": [
                        {
                            "id": d.get("ID"),
                            "status": d.get("Status"),
                            "enabled": d.get("Enabled"),
                            "temp": _board_temp(d),
                            "mhs": d.get("MHS av") or d.get("MHS 5s"),
                            "fans": _board_fans(d),
                        }
                        for d in devs
                    ],
                    "pools": [
                        {
                            "id": p.get("POOL"),
                            "priority": p.get("Priority"),
                            "status": p.get("Status"),
                            "stratum_active": bool(p.get("Stratum Active")),
                            "url": p.get("URL"),
                            "user": p.get("User"),
                            "accepted": p.get("Accepted"),
                            "rejected": p.get("Rejected"),
                            "last_share": p.get("Last Share Time"),
                        }
                        for p in pools
                    ],
                    "working_pool": (
                        {
                            "id": working.get("POOL"),
                            "url": working.get("URL"),
                            "user": working.get("User"),
                            "accepted": working.get("Accepted"),
                            "last_share": working.get("Last Share Time"),
                        }
                        if working
                        else None
                    ),
                }
            )

        # JWT extras (best-effort). Also marks online if BFG failed.
        jwt_ok = False
        try:
            setting = self.api("GET", "/mcb/setting")
            status = self.api("GET", "/mcb/status")
            http_pools = self.api("GET", "/mcb/pools")
            jwt_ok = True
            out["ok"] = True
            out["setting"] = setting if isinstance(setting, dict) else None
            out["status"] = status if isinstance(status, dict) else None
            out["http_pools"] = http_pools if isinstance(http_pools, list) else http_pools
            if isinstance(setting, dict):
                plan = setting.get("manualPowerplan") or ""
                try:
                    mhz, mv, fa, fb, pv = parse_plan(plan)
                    out["plan"] = {
                        "raw": plan,
                        "mhz": mhz,
                        "mv": mv,
                        "fan_a": fa,
                        "fan_b": fb,
                        "pv": pv,
                    }
                except Exception:
                    out["plan"] = {"raw": plan}
                out["tempcontrol"] = setting.get("tempcontrol")
                out["manual"] = setting.get("manual")
                out["ledcontrol"] = setting.get("ledcontrol")
            # When BFG failed, synthesize minimal pool/hash fields from JWT
            if not bfg_ok and isinstance(http_pools, list):
                out["pools"] = [
                    {
                        "id": i,
                        "priority": p.get("pool-priority", i),
                        "status": "Alive" if p.get("active") or i == 0 else "Alive",
                        "stratum_active": bool(p.get("active")),
                        "url": p.get("url"),
                        "user": p.get("user"),
                        "accepted": None,
                        "rejected": None,
                        "last_share": None,
                    }
                    for i, p in enumerate(http_pools)
                    if isinstance(p, dict)
                ]
                active = next(
                    (p for p in http_pools if isinstance(p, dict) and p.get("active")),
                    http_pools[0] if http_pools else None,
                )
                if isinstance(active, dict):
                    out["working_pool"] = {
                        "id": active.get("pool-priority", 0),
                        "url": active.get("url"),
                        "user": active.get("user"),
                        "accepted": None,
                        "last_share": None,
                    }
            if not bfg_ok and isinstance(status, dict):
                # status often has hashrate-ish fields depending on fw
                for k in ("hashrate", "Hash Rate", "mhs", "MHS"):
                    if status.get(k) is not None and out.get("mhs_av") is None:
                        try:
                            out["mhs_av"] = float(status[k])
                        except Exception:
                            pass
        except Exception as e:
            out["jwt_error"] = f"{type(e).__name__}: {e}"

        if not bfg_ok and not jwt_ok:
            out["ok"] = False
            out["error"] = out.get("bfg_error") or out.get("jwt_error") or "unreachable"

        return out

    def set_fan_bias(self, fan: int) -> dict[str, Any]:
        fan = max(0, min(100, int(fan)))
        s = self.api("GET", "/mcb/setting")
        if not isinstance(s, dict):
            raise RuntimeError(f"bad setting: {s!r}")
        plan = s.get("manualPowerplan") or ""
        mhz, mv, _fa, _fb, pv = parse_plan(plan)
        new_plan = build_plan(mhz, mv, fan, fan, pv)
        s["manual"] = True
        s["manualPowerplan"] = new_plan
        # keep tempcontrol as-is (safer)
        self.api("PUT", "/mcb/setting", s)
        return {"ok": True, "plan": new_plan, "fan": fan}

    def set_tempcontrol(self, enabled: bool) -> dict[str, Any]:
        s = self.api("GET", "/mcb/setting")
        if not isinstance(s, dict):
            raise RuntimeError(f"bad setting: {s!r}")
        s["tempcontrol"] = bool(enabled)
        self.api("PUT", "/mcb/setting", s)
        return {"ok": True, "tempcontrol": bool(enabled)}

    def set_plan(
        self,
        *,
        mhz: int | None = None,
        mv: int | None = None,
        fan: int | None = None,
        pv: int | None = None,
        manual: bool | None = True,
        tempcontrol: bool | None = None,
    ) -> dict[str, Any]:
        s = self.api("GET", "/mcb/setting")
        if not isinstance(s, dict):
            raise RuntimeError(f"bad setting: {s!r}")
        cur_mhz, cur_mv, fa, fb, cur_pv = parse_plan(s.get("manualPowerplan") or "")
        new_plan = build_plan(
            cur_mhz if mhz is None else int(mhz),
            cur_mv if mv is None else int(mv),
            fa if fan is None else int(fan),
            fb if fan is None else int(fan),
            cur_pv if pv is None else int(pv),
        )
        if manual is not None:
            s["manual"] = bool(manual)
        if tempcontrol is not None:
            s["tempcontrol"] = bool(tempcontrol)
        s["manualPowerplan"] = new_plan
        self.api("PUT", "/mcb/setting", s)
        return {"ok": True, "plan": new_plan, "setting": s}

    def get_http_pools(self) -> list[dict[str, Any]]:
        raw = self.api("GET", "/mcb/pools")
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            data = raw.get("data") or raw.get("pools")
            if isinstance(data, list):
                return data
        raise RuntimeError(f"unexpected pools shape: {type(raw)}")

    def put_http_pools(self, pools: list[dict[str, Any]]) -> Any:
        return self.api("PUT", "/mcb/pools", pools)

    def add_pool(self, url: str, user: str, password: str = "x") -> Any:
        return self.api("PUT", "/mcb/newpool", {"url": url, "user": user, "pass": password})

    def del_pool(self, pool_obj: dict[str, Any]) -> Any:
        return self.api("PUT", "/mcb/delpool", pool_obj)

    @staticmethod
    def split_stratum_user(user: str) -> tuple[str, str]:
        """Return (payout_address, worker). Worker may be empty."""
        u = (user or "").strip()
        if "." not in u:
            return u, ""
        addr, worker = u.split(".", 1)
        return addr.strip(), worker.strip()

    def current_stratum_user(self) -> str:
        """Best-effort current user from working pool / first Alive / first pool."""
        try:
            pools = list(self.bfg("pools").get("POOLS") or [])
        except Exception:
            pools = []
        # newest last-share Alive
        best = None
        best_last = -1.0
        for p in pools:
            if str(p.get("Status")) != "Alive":
                continue
            try:
                last = float(p.get("Last Share Time") or 0)
            except Exception:
                last = 0.0
            if last >= best_last:
                best_last = last
                best = p
        if best and best.get("User"):
            return str(best.get("User"))
        for p in pools:
            if p.get("User"):
                return str(p.get("User"))
        # HTTP fallback
        try:
            for p in self.get_http_pools():
                if p.get("user"):
                    return str(p.get("user"))
        except Exception:
            pass
        return ""

    def add_pool_smart(
        self,
        *,
        url: str,
        payout: str = "",
        user: str = "",
        password: str = "x",
        keep_worker: bool = True,
        worker_override: str = "",
        make_preferred: bool = False,
        soft_restart: bool = False,
    ) -> dict[str, Any]:
        """Add a pool; optionally keep worker from current stratum user.

        If ``user`` is provided, it is used as-is.
        Else build ``{payout}.{worker}`` (worker from current user or override).
        """
        url = (url or "").strip()
        if not url:
            raise RuntimeError("url required")
        if not url.startswith("stratum"):
            # allow host:port shorthand
            if "://" not in url:
                url = f"stratum+tcp://{url}"

        final_user = (user or "").strip()
        kept_worker = ""
        if not final_user:
            payout = (payout or "").strip()
            if not payout:
                raise RuntimeError("payout address or full user required")
            cur = self.current_stratum_user()
            _addr, cur_worker = self.split_stratum_user(cur)
            kept_worker = (worker_override or cur_worker or "").strip()
            if keep_worker and kept_worker:
                final_user = f"{payout}.{kept_worker}"
            else:
                final_user = payout

        result = self.add_pool(url, final_user, password or "x")
        pools = self.get_http_pools()
        restart = None
        if make_preferred:
            # move matching url to front
            pools = self._reorder_http_pools_url_first(pools, url)
            self.put_http_pools(pools)
            pools = self.get_http_pools()
            if soft_restart:
                restart = self.soft_restart()
                self.wait_until_up(90)
        return {
            "ok": True,
            "user": final_user,
            "worker_kept": kept_worker,
            "url": url,
            "result": result,
            "pools": pools,
            "restart": restart,
        }

    def _reorder_http_pools_url_first(
        self, pools: list[dict[str, Any]], url: str
    ) -> list[dict[str, Any]]:
        url_n = url.strip().lower()
        items = [dict(p) for p in pools]
        match_i = next(
            (i for i, p in enumerate(items) if str(p.get("url") or "").strip().lower() == url_n),
            None,
        )
        if match_i is None:
            # sometimes host:port vs full — match by endswith port path
            match_i = next(
                (
                    i
                    for i, p in enumerate(items)
                    if url_n in str(p.get("url") or "").strip().lower()
                    or str(p.get("url") or "").strip().lower() in url_n
                ),
                None,
            )
        if match_i is None:
            raise RuntimeError(f"pool url not found after add: {url}")
        pref = items.pop(match_i)
        ordered = [pref] + items
        out = []
        for i, p in enumerate(ordered):
            q = dict(p)
            q["pool-priority"] = i
            q["dragid"] = i
            q["active"] = i == 0
            q.setdefault("legal", True)
            out.append(q)
        return out

    def del_pool_by_url(self, url: str) -> dict[str, Any]:
        url_n = (url or "").strip().lower()
        pools = self.get_http_pools()
        match = next(
            (p for p in pools if str(p.get("url") or "").strip().lower() == url_n),
            None,
        )
        if match is None:
            match = next(
                (
                    p
                    for p in pools
                    if url_n in str(p.get("url") or "").strip().lower()
                    or str(p.get("url") or "").strip().lower() in url_n
                ),
                None,
            )
        if match is None:
            raise RuntimeError(f"no pool matching url: {url}")
        res = self.del_pool(match)
        return {"ok": True, "deleted": match, "result": res, "pools": self.get_http_pools()}

    def set_pool_order(self, order: list[int] | list[str], soft_restart: bool = False) -> dict[str, Any]:
        """Reorder pools by index list [0,2,1] or by URL list."""
        pools = self.get_http_pools()
        if not order:
            raise RuntimeError("order required")
        if all(isinstance(x, int) or (isinstance(x, str) and str(x).isdigit()) for x in order):
            idxs = [int(x) for x in order]
            if sorted(idxs) != list(range(len(pools))):
                # allow partial — treat as new priority order of those indices, rest append
                seen = set()
                ordered_items = []
                for i in idxs:
                    if 0 <= i < len(pools) and i not in seen:
                        ordered_items.append(dict(pools[i]))
                        seen.add(i)
                for i, p in enumerate(pools):
                    if i not in seen:
                        ordered_items.append(dict(p))
            else:
                ordered_items = [dict(pools[i]) for i in idxs]
        else:
            # URLs — preferred order first, then any remaining pools
            urls = [str(x).strip().lower() for x in order]
            remaining = [dict(p) for p in pools]
            ordered_items = []
            for u in urls:
                hit_i = next(
                    (
                        i
                        for i, p in enumerate(remaining)
                        if str(p.get("url") or "").strip().lower() == u
                        or u in str(p.get("url") or "").strip().lower()
                        or str(p.get("url") or "").strip().lower() in u
                    ),
                    None,
                )
                if hit_i is not None:
                    ordered_items.append(remaining.pop(hit_i))
            ordered_items.extend(remaining)

        out = []
        for i, p in enumerate(ordered_items):
            q = dict(p)
            q["pool-priority"] = i
            q["dragid"] = i
            q["active"] = i == 0
            q.setdefault("legal", True)
            out.append(q)
        put_res = self.put_http_pools(out)
        restart = None
        if soft_restart:
            restart = self.soft_restart()
            self.wait_until_up(90)
        return {"ok": True, "pools": self.get_http_pools(), "put": put_res, "restart": restart}

    def failback_preferred(self, preferred: int = 0, soft_restart: bool = True) -> dict[str, Any]:
        pools = self.get_http_pools()
        if preferred < 0 or preferred >= len(pools):
            raise RuntimeError("preferred out of range")
        items = [dict(p) for p in pools]
        pref = items.pop(preferred)
        ordered = [pref] + items
        out = []
        for i, p in enumerate(ordered):
            q = dict(p)
            q["pool-priority"] = i
            q["dragid"] = i
            q["active"] = i == 0
            q.setdefault("legal", True)
            out.append(q)
        put_res = self.put_http_pools(out)
        restart_res = None
        if soft_restart:
            restart_res = self.soft_restart()
            self.wait_until_up(90)
        return {"ok": True, "pools": out, "put": put_res, "restart": restart_res}

    def soft_restart(self, timeout: float = 8.0) -> str:
        with self._lock:
            if self._token is None:
                self.login()
            assert self._token is not None
            req = urllib.request.Request(
                self.host() + "/mcb/restart",
                headers={"Authorization": self._token, "Accept": "*/*"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    _ = r.read()
                    return f"restart HTTP {getattr(r, 'status', 200)}"
            except Exception as e:
                msg = str(e).lower()
                if any(x in msg for x in ("closed", "reset", "timed out", "timeout")):
                    return f"restart requested ({type(e).__name__})"
                raise

    def wait_until_up(self, timeout_s: float = 120.0, poll_s: float = 5.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                with self._lock:
                    self._token = None
                self.login()
                self.api("GET", "/mcb/setting")
                return True
            except Exception:
                time.sleep(poll_s)
        return False
