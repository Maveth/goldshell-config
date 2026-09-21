#!/usr/bin/env python3
"""Local Goldshell SC Lite control plane (fleet + single).

  cd sc-lite/webui
  copy miners.example.json miners.json   # edit IPs/passwords
  python server.py
  open http://127.0.0.1:8787
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
REGISTRY_PATH = Path(os.environ.get("SCLITE_WEBUI_MINERS", str(HERE / "miners.json")))
sys.path.insert(0, str(HERE))

from fan_controller import FanController, merge_profiles  # noqa: E402
from miner_client import MinerClient  # noqa: E402
from probe import probe_miner  # noqa: E402

_clients: dict[str, MinerClient] = {}
_lock = threading.RLock()
_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()
_fan_ctrl: FanController | None = None


def load_registry_doc() -> dict[str, Any]:
    if not REGISTRY_PATH.is_file():
        example = HERE / "miners.example.json"
        if example.is_file():
            return json.loads(example.read_text(encoding="utf-8"))
        return {"miners": [], "fan_defaults": {"profile": "steps-default", "enabled_default": False}}
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def load_registry() -> list[dict[str, Any]]:
    return list(load_registry_doc().get("miners") or [])


def save_registry_doc(doc: dict[str, Any]) -> None:
    REGISTRY_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def save_registry(miners: list[dict[str, Any]]) -> None:
    doc = load_registry_doc()
    doc["miners"] = miners
    save_registry_doc(doc)


def sync_clients() -> dict[str, MinerClient]:
    with _lock:
        rows = load_registry()
        want: dict[str, MinerClient] = {}
        for row in rows:
            if row.get("demo"):
                continue  # demo rows are synthetic; not real clients
            ip = (row.get("ip") or "").strip()
            if not ip:
                continue
            mid = (row.get("id") or ip).strip()
            pw = row.get("password") or os.environ.get("SCLITE_PASSWORD") or ""
            name = row.get("name") or mid
            existing = _clients.get(mid)
            if (
                existing
                and existing.ip == ip
                and existing.password == pw
                and existing.name == name
            ):
                want[mid] = existing
            else:
                want[mid] = MinerClient(ip=ip, password=pw, name=name, id=mid)
        _clients.clear()
        _clients.update(want)
        return dict(_clients)


def _demo_snapshot(mid: str, name: str, ip: str) -> dict[str, Any]:
    """Fake miner card data for UI layout testing only."""
    import random
    import time as _t

    seed = sum(ord(c) for c in mid)
    random.seed(seed + int(_t.time() // 10))
    temp = 68 + (seed % 7) + random.random() * 2
    fan = 1500 + (seed % 200)
    mhs = 4_200_000 + seed * 1000 + random.random() * 50_000
    return {
        "id": mid,
        "name": name,
        "ip": ip,
        "ok": True,
        "demo": True,
        "ts": _t.time(),
        "elapsed": 3600 + seed,
        "accepted": 100 + seed % 50,
        "rejected": 0,
        "hw": seed % 3,
        "mhs_av": mhs,
        "temp_max": temp,
        "temp_avg": temp - 1,
        "fan_avg": fan,
        "fans": [fan, fan - 20, fan - 10, fan],
        "working_pool": {
            "id": seed % 2,
            "url": f"stratum+tcp://192.168.0.143:{29506 if seed % 2 == 0 else 29129}",
            "user": f"bc1qdemo{seed % 99:02d}.Demo{seed % 9}",
            "accepted": 40 + seed % 20,
            "last_share": _t.time() - random.random() * 30,
        },
        "pools": [
            {
                "id": 0,
                "priority": 0,
                "status": "Alive",
                "stratum_active": seed % 2 == 0,
                "url": "stratum+tcp://192.168.0.143:29506",
                "user": f"bc1qdemo{seed % 99:02d}.Demo{seed % 9}",
                "accepted": 40,
                "rejected": 0,
                "last_share": _t.time() - 10,
            },
            {
                "id": 1,
                "priority": 1,
                "status": "Alive",
                "stratum_active": seed % 2 == 1,
                "url": "stratum+tcp://192.168.0.143:29129",
                "user": f"bc1qdemo{seed % 99:02d}.Demo{seed % 9}_sv1",
                "accepted": 12,
                "rejected": 0,
                "last_share": _t.time() - 40,
            },
        ],
        "devs": [
            {
                "id": i,
                "status": "Alive",
                "enabled": "Y",
                "temp": temp - i * 0.4,
                "mhs": mhs / 4,
                "fans": f"{fan} {fan-15} {fan-10} {fan}",
            }
            for i in range(4)
        ],
        "plan": {"raw": "625 MHz 9100 V 70 RPM 70 RPM PV 9400", "mhz": 625, "mv": 9100, "fan_a": 70, "fan_b": 70, "pv": 9400},
        "tempcontrol": True,
    }


def demo_miner_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    if not doc.get("demo"):
        return []
    return [
        {
            "id": "demo-alpha",
            "name": "Demo Alpha",
            "ip": "192.168.0.201",
            "demo": True,
            "fan_control": {"enabled": False, "profile": "steps-default", "fan_offset": 0},
            "snapshot": _demo_snapshot("demo-alpha", "Demo Alpha", "192.168.0.201"),
            "fan_runtime": {"enabled": False, "last_status": "OFF (demo)"},
        },
        {
            "id": "demo-bravo",
            "name": "Demo Bravo",
            "ip": "192.168.0.203",
            "demo": True,
            "fan_control": {"enabled": True, "profile": "steps-aggressive", "fan_offset": 0},
            "snapshot": _demo_snapshot("demo-bravo", "Demo Bravo", "192.168.0.203"),
            "fan_runtime": {
                "enabled": True,
                "profile": "steps-aggressive",
                "last_status": "STEPS fan=75 temp=71.2",
                "last_applied_fan": 75,
                "last_temp": 71.2,
            },
        },
    ]


def get_client(mid: str) -> MinerClient:
    sync_clients()
    with _lock:
        c = _clients.get(mid)
    if not c:
        raise KeyError(f"unknown miner id: {mid}")
    return c


def json_response(handler: SimpleHTTPRequestHandler, code: int, obj: Any) -> None:
    raw = json.dumps(obj, default=str).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def read_json(handler: SimpleHTTPRequestHandler) -> Any:
    n = int(handler.headers.get("Content-Length") or 0)
    if n <= 0:
        return {}
    return json.loads(handler.rfile.read(n))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[webui] " + (fmt % args) + "\n")

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)
        try:
            if path == "/api/health":
                return json_response(self, 200, {"ok": True})
            if path == "/api/miners":
                clients = sync_clients()
                doc = load_registry_doc()
                fan_defaults = doc.get("fan_defaults") or {}
                profiles = merge_profiles(doc.get("profiles"))
                fan_status = _fan_ctrl.status_blob() if _fan_ctrl else {}
                rows = []
                for mid, c in clients.items():
                    snap = None
                    with _cache_lock:
                        snap = _cache.get(mid)
                    mrow = next(
                        (
                            m
                            for m in (doc.get("miners") or [])
                            if (m.get("id") or m.get("ip")) == mid
                        ),
                        {},
                    )
                    rows.append(
                        {
                            "id": mid,
                            "name": c.name,
                            "ip": c.ip,
                            "snapshot": snap,
                            "fan_control": mrow.get("fan_control")
                            or {
                                "enabled": bool(fan_defaults.get("enabled_default")),
                                "profile": fan_defaults.get("profile") or "steps-default",
                                "fan_offset": 0,
                            },
                            "fan_runtime": fan_status.get(mid),
                        }
                    )
                rows = rows + demo_miner_rows(doc)
                return json_response(
                    self,
                    200,
                    {
                        "miners": rows,
                        "demo": bool(doc.get("demo")),
                        "fan_defaults": fan_defaults,
                        "profiles": {
                            k: {
                                "label": v.get("label") or k,
                                **{kk: vv for kk, vv in v.items() if kk != "label"},
                            }
                            for k, v in profiles.items()
                        },
                    },
                )
            if path == "/api/fan/status":
                doc = load_registry_doc()
                return json_response(
                    self,
                    200,
                    {
                        "runtime": _fan_ctrl.status_blob() if _fan_ctrl else {},
                        "fan_defaults": doc.get("fan_defaults") or {},
                        "profiles": list(merge_profiles(doc.get("profiles")).keys()),
                    },
                )
            if path.startswith("/api/miners/") and path.endswith("/snapshot"):
                mid = path[len("/api/miners/") : -len("/snapshot")]
                if str(mid).startswith("demo-"):
                    row = next(
                        (r for r in demo_miner_rows(load_registry_doc()) if r["id"] == mid),
                        None,
                    )
                    if not row:
                        return json_response(
                            self, 404, {"ok": False, "error": "demo off or unknown"}
                        )
                    return json_response(self, 200, row["snapshot"])
                c = get_client(mid)
                snap = c.snapshot()
                with _cache_lock:
                    _cache[mid] = snap
                return json_response(self, 200, snap)
            if path.startswith("/api/miners/") and path.endswith("/pools"):
                mid = path[len("/api/miners/") : -len("/pools")]
                c = get_client(mid)
                return json_response(self, 200, {"pools": c.get_http_pools()})
            if path == "/api/fleet/refresh":
                # refresh all snapshots (blocking; ok for small fleets)
                clients = sync_clients()
                out = {}
                for mid, c in clients.items():
                    try:
                        snap = c.snapshot()
                    except Exception as e:
                        snap = {
                            "id": mid,
                            "name": c.name,
                            "ip": c.ip,
                            "ok": False,
                            "error": f"{type(e).__name__}: {e}",
                        }
                    with _cache_lock:
                        _cache[mid] = snap
                    out[mid] = snap
                for drow in demo_miner_rows(load_registry_doc()):
                    out[drow["id"]] = drow["snapshot"]
                return json_response(self, 200, {"miners": out})
            # static
            if path == "/":
                self.path = "/index.html"
            return super().do_GET()
        except KeyError as e:
            return json_response(self, 404, {"ok": False, "error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return json_response(
                self, 500, {"ok": False, "error": f"{type(e).__name__}: {e}"}
            )

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path
        try:
            body = read_json(self)
            if path == "/api/miners":
                # add miner to registry — real path rejects duplicate IPs
                miners = load_registry()
                mid = (body.get("id") or body.get("ip") or "").strip()
                ip = (body.get("ip") or "").strip()
                if not ip or not mid:
                    return json_response(self, 400, {"ok": False, "error": "id and ip required"})
                if any((m.get("ip") or "").strip() == ip for m in miners):
                    return json_response(
                        self, 400, {"ok": False, "error": f"duplicate IP not allowed: {ip}"}
                    )
                if any((m.get("id") or "") == mid for m in miners):
                    return json_response(
                        self, 400, {"ok": False, "error": f"duplicate id not allowed: {mid}"}
                    )
                miners.append(
                    {
                        "id": mid,
                        "name": body.get("name") or mid,
                        "ip": ip,
                        "password": body.get("password") or "",
                        "fan_control": {
                            "enabled": False,
                            "profile": (load_registry_doc().get("fan_defaults") or {}).get(
                                "profile", "steps-default"
                            ),
                            "fan_offset": 0,
                        },
                    }
                )
                save_registry(miners)
                sync_clients()
                return json_response(self, 200, {"ok": True, "miners": miners})

            if path.startswith("/api/miners/") and "/action/" in path:
                # /api/miners/{id}/action/{name}
                rest = path[len("/api/miners/") :]
                mid, _, action = rest.partition("/action/")
                c = get_client(mid)
                return json_response(self, 200, _run_action(c, action, body))

            if path == "/api/settings/demo":
                doc = load_registry_doc()
                doc["demo"] = bool(body.get("demo"))
                save_registry_doc(doc)
                return json_response(self, 200, {"ok": True, "demo": doc["demo"]})

            if path == "/api/probe":
                ip = str(body.get("ip") or "").strip()
                if not ip:
                    return json_response(self, 400, {"ok": False, "error": "ip required"})
                pw = str(body.get("password") or "")
                try_common = bool(body.get("try_common_passwords", True))
                add = bool(body.get("add_to_registry", False))
                result = probe_miner(ip, password=pw, try_common_passwords=try_common)
                if add and result.get("ok") and pw:
                    # register using suggested id
                    ident = result.get("identity") or {}
                    model = (ident.get("model") or "miner").replace(" ", "-").lower()
                    mid = str(body.get("id") or f"{model}-{ip.split('.')[-1]}")
                    miners = load_registry()
                    if any((m.get("ip") or "").strip() == ip for m in miners):
                        result["registry"] = {"added": False, "error": "duplicate IP"}
                    else:
                        profile = ident.get("suggested_profile") or "steps-default"
                        # map hardware profile to fan profile default
                        fan_prof = "steps-default"
                        miners.append(
                            {
                                "id": mid,
                                "name": body.get("name") or ident.get("model") or mid,
                                "ip": ip,
                                "password": pw,
                                "hardware_profile": profile,
                                "fan_control": {
                                    "enabled": False,
                                    "profile": fan_prof,
                                    "fan_offset": 0,
                                },
                            }
                        )
                        save_registry(miners)
                        sync_clients()
                        result["registry"] = {"added": True, "id": mid}
                return json_response(self, 200, result)

            if path == "/api/fleet/action":
                action = (body.get("action") or "").strip()
                ids = body.get("ids") or list(sync_clients().keys())
                # never send hardware actions to demo ids
                ids = [i for i in ids if not str(i).startswith("demo-")]
                results = {}
                for mid in ids:
                    try:
                        c = get_client(mid)
                        results[mid] = _run_action(c, action, body)
                    except Exception as e:
                        results[mid] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                return json_response(self, 200, {"ok": True, "results": results})

            if path == "/api/fan/defaults":
                doc = load_registry_doc()
                fd = dict(doc.get("fan_defaults") or {})
                if "profile" in body:
                    fd["profile"] = str(body.get("profile") or "steps-default")
                if "enabled_default" in body:
                    fd["enabled_default"] = bool(body.get("enabled_default"))
                doc["fan_defaults"] = fd
                # optional: apply enabled/profile to all miners
                if body.get("apply_to_all"):
                    for m in doc.get("miners") or []:
                        fc = dict(m.get("fan_control") or {})
                        if "profile" in body:
                            fc["profile"] = fd["profile"]
                        if body.get("set_enabled") is not None:
                            fc["enabled"] = bool(body.get("set_enabled"))
                        m["fan_control"] = fc
                save_registry_doc(doc)
                return json_response(self, 200, {"ok": True, "fan_defaults": fd, "miners": doc.get("miners")})

            if path.startswith("/api/miners/") and path.endswith("/fan_control"):
                mid = path[len("/api/miners/") : -len("/fan_control")]
                if str(mid).startswith("demo-"):
                    return json_response(self, 200, {"ok": True, "demo": True})
                doc = load_registry_doc()
                found = False
                for m in doc.get("miners") or []:
                    if (m.get("id") or m.get("ip")) == mid:
                        fc = dict(m.get("fan_control") or {})
                        if "enabled" in body:
                            fc["enabled"] = bool(body.get("enabled"))
                        if "profile" in body:
                            fc["profile"] = str(body.get("profile"))
                        if "fan_offset" in body:
                            fc["fan_offset"] = int(body.get("fan_offset") or 0)
                        m["fan_control"] = fc
                        found = True
                        break
                if not found:
                    return json_response(self, 404, {"ok": False, "error": "miner not found"})
                save_registry_doc(doc)
                return json_response(self, 200, {"ok": True, "miners": doc.get("miners")})

            if path.startswith("/api/miners/") and path.endswith("/fan_nudge"):
                mid = path[len("/api/miners/") : -len("/fan_nudge")]
                if str(mid).startswith("demo-"):
                    return json_response(self, 200, {"ok": True, "demo": True, "fan": 70})
                c = get_client(mid)
                delta = int(body.get("delta") or 0)
                # read current plan fan or use body.base
                base = body.get("fan")
                if base is None:
                    snap = c.snapshot()
                    plan = (snap.get("plan") or {})
                    base = plan.get("fan_a") or 70
                new_fan = max(20, min(100, int(base) + delta))
                res = c.set_fan_bias(new_fan)
                # also bump offset so auto controller tracks preference
                doc = load_registry_doc()
                for m in doc.get("miners") or []:
                    if (m.get("id") or m.get("ip")) == mid:
                        fc = dict(m.get("fan_control") or {})
                        fc["fan_offset"] = int(fc.get("fan_offset") or 0) + delta
                        # clamp offset
                        fc["fan_offset"] = max(-40, min(40, int(fc["fan_offset"])))
                        m["fan_control"] = fc
                        break
                save_registry_doc(doc)
                return json_response(self, 200, {"ok": True, "fan": new_fan, "result": res})

            return json_response(self, 404, {"ok": False, "error": "not found"})
        except KeyError as e:
            return json_response(self, 404, {"ok": False, "error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return json_response(
                self, 500, {"ok": False, "error": f"{type(e).__name__}: {e}"}
            )

    def do_DELETE(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path
        try:
            if path.startswith("/api/miners/"):
                mid = path[len("/api/miners/") :].strip("/")
                miners = [
                    m
                    for m in load_registry()
                    if (m.get("id") or m.get("ip")) != mid
                ]
                save_registry(miners)
                sync_clients()
                with _cache_lock:
                    _cache.pop(mid, None)
                return json_response(self, 200, {"ok": True, "miners": miners})
            return json_response(self, 404, {"ok": False, "error": "not found"})
        except Exception as e:
            return json_response(
                self, 500, {"ok": False, "error": f"{type(e).__name__}: {e}"}
            )


def _run_action(c: MinerClient, action: str, body: dict[str, Any]) -> dict[str, Any]:
    if action == "fan":
        return c.set_fan_bias(int(body.get("fan", 70)))
    if action == "fan_nudge":
        delta = int(body.get("delta") or 0)
        base = body.get("fan")
        if base is None:
            snap = c.snapshot()
            base = (snap.get("plan") or {}).get("fan_a") or 70
        new_fan = max(20, min(100, int(base) + delta))
        return {"ok": True, "fan": new_fan, **c.set_fan_bias(new_fan)}
    if action == "tempcontrol":
        return c.set_tempcontrol(bool(body.get("enabled", True)))
    if action == "plan":
        return c.set_plan(
            mhz=body.get("mhz"),
            mv=body.get("mv"),
            fan=body.get("fan"),
            pv=body.get("pv"),
            manual=body.get("manual", True),
            tempcontrol=body.get("tempcontrol"),
        )
    if action == "failback":
        return c.failback_preferred(
            preferred=int(body.get("preferred", 0)),
            soft_restart=bool(body.get("soft_restart", True)),
        )
    if action == "restart":
        msg = c.soft_restart()
        up = c.wait_until_up(90)
        return {"ok": True, "restart": msg, "up": up}
    if action == "add_pool":
        # Smart add: payout + keep worker, or full user
        if body.get("payout") or body.get("keep_worker") is not None or body.get("make_preferred"):
            return c.add_pool_smart(
                url=str(body.get("url") or ""),
                payout=str(body.get("payout") or ""),
                user=str(body.get("user") or ""),
                password=str(body.get("pass") or "x"),
                keep_worker=bool(body.get("keep_worker", True)),
                worker_override=str(body.get("worker") or ""),
                make_preferred=bool(body.get("make_preferred", False)),
                soft_restart=bool(body.get("soft_restart", False)),
            )
        return {
            "ok": True,
            "result": c.add_pool(
                str(body.get("url") or ""),
                str(body.get("user") or ""),
                str(body.get("pass") or "x"),
            ),
            "pools": c.get_http_pools(),
        }
    if action == "del_pool":
        if body.get("url"):
            return c.del_pool_by_url(str(body.get("url")))
        pool = body.get("pool")
        if not isinstance(pool, dict):
            raise RuntimeError("pool object or url required")
        return {"ok": True, "result": c.del_pool(pool), "pools": c.get_http_pools()}
    if action == "set_pools":
        pools = body.get("pools")
        if not isinstance(pools, list):
            raise RuntimeError("pools list required")
        return {"ok": True, "result": c.put_http_pools(pools), "pools": c.get_http_pools()}
    if action == "set_pool_order":
        order = body.get("order") or body.get("urls") or body.get("indexes")
        if not isinstance(order, list):
            raise RuntimeError("order list required (indexes or urls)")
        return c.set_pool_order(order, soft_restart=bool(body.get("soft_restart", False)))
    if action == "make_preferred":
        url = str(body.get("url") or "")
        if not url:
            raise RuntimeError("url required")
        pools = c._reorder_http_pools_url_first(c.get_http_pools(), url)
        put = c.put_http_pools(pools)
        restart = None
        if body.get("soft_restart", True):
            restart = c.soft_restart()
            c.wait_until_up(90)
        return {"ok": True, "pools": c.get_http_pools(), "put": put, "restart": restart}
    if action == "snapshot":
        snap = c.snapshot()
        with _cache_lock:
            _cache[c.id] = snap
        return snap
    raise RuntimeError(f"unknown action: {action}")


def main() -> None:
    global _fan_ctrl
    if not REGISTRY_PATH.is_file():
        example = HERE / "miners.example.json"
        if example.is_file():
            REGISTRY_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"created {REGISTRY_PATH} from example — edit passwords")
    # ensure fan_defaults exist
    doc = load_registry_doc()
    if "fan_defaults" not in doc:
        doc["fan_defaults"] = {"profile": "steps-default", "enabled_default": False}
        save_registry_doc(doc)
    sync_clients()
    _fan_ctrl = FanController(get_clients=sync_clients, get_registry=load_registry_doc)
    _fan_ctrl.start()
    host = os.environ.get("SCLITE_WEBUI_HOST", "0.0.0.0")
    port = int(os.environ.get("SCLITE_WEBUI_PORT", "8787"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"SC Lite webui → http://{host}:{port}")
    print(f"  local:   http://127.0.0.1:{port}")
    print(f"  lan:     http://<this-pc-ip>:{port}")
    print(f"registry → {REGISTRY_PATH}")
    print("fan controller: running (enable per miner in UI)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("bye")
        if _fan_ctrl:
            _fan_ctrl.stop()


if __name__ == "__main__":
    main()
