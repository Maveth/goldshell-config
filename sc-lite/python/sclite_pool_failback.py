#!/usr/bin/env python3
"""SC Lite pool failback — kick back to preferred pool when it is up again.

Goldshell failover often sticks on pool 1 after pool 0 recovers. BFG :4028
switchpool/poolpriority are Access:N; the web UI uses GET/PUT /mcb/pools.

This tool:
  1) Reads pool status via TCP :4028 (no JWT) — Alive / Stratum Active / last share
  2) If preferred pool is Alive but work is on another pool (newest last-share),
     PUT /mcb/pools to put preferred first, then soft-restart (GET /mcb/restart)
     so the sticky backup stratum session is dropped.

Defaults are safe: dry-run (no PUT/restart). Use --apply to actually kick.
Use --no-restart for PUT-only (usually not enough on Goldshell).

Env:
  SCLITE_IP=192.168.0.202
  SCLITE_PASSWORD=...   (needed only for --apply)

Examples:
  python sclite_pool_failback.py --once
  python sclite_pool_failback.py --once --apply
  python sclite_pool_failback.py --once --apply --force   # kick even if unsure
  python sclite_pool_failback.py --watch 30 --grace 60 --apply --preferred 0

See ../POOL_FAILBACK.md for full notes.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from typing import Any

import sclite_common as sc

DEFAULT_IP = os.environ.get("SCLITE_IP", "192.168.0.202")
BFG_PORT = 4028


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


def _parse_bfg_json(raw: bytes | str) -> dict[str, Any]:
    """Goldshell :4028 often null-terminates or returns slightly broken JSON."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", "replace")
    else:
        text = raw
    text = text.replace("\x00", "").strip()
    if not text:
        raise RuntimeError("empty bfg response")
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    if text[:1] == "{":
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
                    out = json.loads(text[: i + 1])
                    if isinstance(out, dict):
                        return out
                    break
    cleaned = (
        text.replace("NaN", "null")
        .replace("Infinity", "null")
        .replace("-Infinity", "null")
    )
    out = json.loads(cleaned)
    if not isinstance(out, dict):
        raise RuntimeError("bfg response not an object")
    return out


def bfg(cmd: str, parameter: str | None = None, host: str | None = None) -> dict[str, Any]:
    """Read a cgminer-style command from Goldshell :4028.

    Important: replies (especially ``devs``) are often split across several TCP
    segments. Stopping on the first short packet truncates JSON and raises
    JSONDecodeError around char ~1448.
    """
    ip = (host or DEFAULT_IP).replace("http://", "").replace("https://", "").split("/")[0]
    payload: dict[str, Any] = {"command": cmd}
    if parameter is not None:
        payload["parameter"] = parameter
    last_err: Exception | None = None
    for _attempt in range(3):
        try:
            s = socket.create_connection((ip, BFG_PORT), timeout=5)
            s.sendall((json.dumps(payload) + "\n").encode())
            s.settimeout(2.5)
            chunks: list[bytes] = []
            try:
                while True:
                    b = s.recv(65536)
                    if not b:
                        break
                    chunks.append(b)
                    joined = b"".join(chunks)
                    if b"\x00" in joined or _bfg_json_complete(joined):
                        break
            except socket.timeout:
                pass
            except Exception:
                pass
            s.close()
            return _parse_bfg_json(b"".join(chunks))
        except Exception as e:
            last_err = e
            time.sleep(0.2)
    raise RuntimeError(f"bfg {cmd} failed: {last_err}")


def read_bfg_pools(host: str | None = None) -> list[dict[str, Any]]:
    j = bfg("pools", host=host)
    return list(j.get("POOLS") or [])


def read_summary(host: str | None = None) -> dict[str, Any]:
    j = bfg("summary", host=host)
    rows = j.get("SUMMARY") or []
    return rows[0] if rows else {}


def fmt_ago(ts: int | float, now: float | None = None) -> str:
    now = now or time.time()
    try:
        t = float(ts)
    except Exception:
        return "?"
    if t <= 0:
        return "never"
    # Goldshell sometimes uses a skewed epoch; still useful as relative if recent
    age = now - t
    if age < -3600:
        # absurd future/skew — show raw
        return f"ts={int(t)}"
    if age < 0:
        age = 0
    if age < 60:
        return f"{int(age)}s ago"
    if age < 3600:
        return f"{int(age // 60)}m ago"
    return f"{age / 3600:.1f}h ago"


def print_status(pools: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    elapsed = summary.get("Elapsed")
    print(f"uptime={elapsed}s  strategy=Failover  pools={len(pools)}")
    print(
        f"{'P':<3} {'PRI':<4} {'STATUS':<7} {'STRATUM':<8} "
        f"{'ACC':<6} {'LAST_SHARE':<12} URL / USER"
    )
    now = time.time()
    for p in pools:
        active = bool(p.get("Stratum Active"))
        print(
            f"{p.get('POOL')!s:<3} {p.get('Priority')!s:<4} "
            f"{str(p.get('Status')):<7} {'YES' if active else 'no':<8} "
            f"{p.get('Accepted')!s:<6} {fmt_ago(p.get('Last Share Time') or 0, now):<12} "
            f"{p.get('URL')}  {p.get('User')}"
        )


def http_pools() -> list[dict[str, Any]]:
    raw = sc.api("GET", "/mcb/pools")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        data = raw.get("data") or raw.get("pools")
        if isinstance(data, list):
            return data
    raise RuntimeError(f"unexpected /mcb/pools shape: {type(raw)}")


def build_failback_payload(
    pools: list[dict[str, Any]], *, preferred: int
) -> list[dict[str, Any]]:
    """Reorder HTTP pool list so preferred is priority 0 / active."""
    if preferred < 0 or preferred >= len(pools):
        raise ValueError(f"preferred index {preferred} out of range 0..{len(pools)-1}")
    # Work on copies; keep url/user/pass/legal/dragid
    items = [dict(p) for p in pools]
    pref = items.pop(preferred)
    ordered = [pref] + items
    out: list[dict[str, Any]] = []
    for i, p in enumerate(ordered):
        q = dict(p)
        q["pool-priority"] = i
        q["dragid"] = i
        q["active"] = i == 0
        # ensure legal key present
        if "legal" not in q:
            q["legal"] = True
        out.append(q)
    return out


def working_pool_index(bfg_pools: list[dict[str, Any]]) -> int | None:
    """Which pool is actually getting work.

    Goldshell often leaves Stratum Active=true on more than one pool after
    failover. Prefer the Alive pool with the newest Last Share Time (>0).
    """
    candidates: list[tuple[float, int]] = []
    for p in bfg_pools:
        if str(p.get("Status")) != "Alive":
            continue
        try:
            idx = int(p.get("POOL"))
            last = float(p.get("Last Share Time") or 0)
        except Exception:
            continue
        if last > 0:
            candidates.append((last, idx))
    if candidates:
        candidates.sort(reverse=True)  # newest last-share first
        return candidates[0][1]
    # fallback: first Stratum Active
    for p in bfg_pools:
        if p.get("Stratum Active"):
            try:
                return int(p.get("POOL"))
            except Exception:
                return None
    return None


def preferred_needs_failback(bfg_pools: list[dict[str, Any]], preferred: int) -> tuple[bool, str]:
    if preferred < 0 or preferred >= len(bfg_pools):
        return False, "preferred index missing"
    pref = bfg_pools[preferred]
    if str(pref.get("Status")) != "Alive":
        return False, f"preferred not Alive ({pref.get('Status')})"
    working = working_pool_index(bfg_pools)
    if working is None:
        return False, "no working pool (no recent shares)"
    if working == preferred:
        return False, f"already working on preferred P{preferred}"
    # Preferred is up but shares are landing elsewhere
    return True, f"working=P{working} preferred=P{preferred} Alive — failback"


def kick_to_preferred(
    *, preferred: int, dry_run: bool, soft_restart: bool = True, wait_up_s: float = 120.0
) -> None:
    http = http_pools()
    print("HTTP /mcb/pools before:")
    print(json.dumps(http, indent=2))
    # Map preferred BFG index → HTTP entry. Prefer matching by order (usually same).
    if preferred >= len(http):
        raise RuntimeError("HTTP pool list shorter than preferred index")
    payload = build_failback_payload(http, preferred=preferred)
    print("HTTP /mcb/pools payload:")
    print(json.dumps(payload, indent=2))
    if dry_run:
        print("DRY-RUN: not PUTting / not restarting")
        return
    r = sc.api("PUT", "/mcb/pools", payload)
    print("PUT /mcb/pools result:", r)
    if soft_restart:
        # PUT alone does not tear down a sticky backup stratum session.
        print("soft restart via GET /mcb/restart …")
        print(" ", sc.soft_restart())
        print(f"waiting up to {wait_up_s:.0f}s for miner …")
        if sc.wait_until_up(timeout_s=wait_up_s, poll_s=5.0):
            print("miner back up")
        else:
            print("WARN: miner did not answer within wait window")
        time.sleep(3)
    else:
        time.sleep(2)
    print("BFG after:")
    print_status(read_bfg_pools(), read_summary())
    try:
        print("HTTP after:")
        print(json.dumps(http_pools(), indent=2))
    except Exception as e:
        print(f"HTTP after: unavailable ({type(e).__name__}: {e})")


def main() -> None:
    ap = argparse.ArgumentParser(description="SC Lite pool failback to preferred pool")
    ap.add_argument("--ip", default=DEFAULT_IP, help="miner IP (default SCLITE_IP or 192.168.0.202)")
    ap.add_argument("--preferred", type=int, default=0, help="preferred pool index (default 0)")
    ap.add_argument("--once", action="store_true", help="single check (default if no --watch)")
    ap.add_argument("--watch", type=float, default=0, help="poll interval seconds (0=once)")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="actually PUT /mcb/pools to fail back (default: dry-run)",
    )
    ap.add_argument(
        "--grace",
        type=float,
        default=60.0,
        help="seconds preferred must look Alive before kicking (watch mode)",
    )
    ap.add_argument(
        "--no-restart",
        action="store_true",
        help="PUT /mcb/pools only (default also soft-restarts miner)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="PUT+restart even if detection thinks preferred is already working",
    )
    ap.add_argument(
        "--wait-up",
        type=float,
        default=120.0,
        help="seconds to wait for miner after soft restart (default 120)",
    )
    args = ap.parse_args()

    os.environ["SCLITE_IP"] = args.ip
    sc.configure(ip=args.ip)

    dry_run = not args.apply
    do_restart = not args.no_restart
    interval = args.watch if args.watch > 0 else 0
    alive_since: float | None = None

    def do_kick(*, dry: bool) -> None:
        kick_to_preferred(
            preferred=args.preferred,
            dry_run=dry,
            soft_restart=do_restart and not dry,
            wait_up_s=args.wait_up,
        )

    def tick() -> None:
        nonlocal alive_since
        pools = read_bfg_pools(args.ip)
        summary = read_summary(args.ip)
        print_status(pools, summary)
        need, reason = preferred_needs_failback(pools, args.preferred)
        if args.force and not need:
            need, reason = True, f"forced re-kick ({reason})"
        print(f"failback? {need} — {reason}")
        if not need:
            alive_since = None
            return
        now = time.time()
        # For --once, skip grace
        if interval <= 0:
            if dry_run:
                print("Would kick (dry-run). Pass --apply to PUT + soft restart.")
                if os.environ.get("SCLITE_PASSWORD"):
                    sc.configure(ip=args.ip, password=os.environ["SCLITE_PASSWORD"])
                    do_kick(dry=True)
            else:
                if not os.environ.get("SCLITE_PASSWORD"):
                    raise SystemExit("SCLITE_PASSWORD required for --apply")
                sc.configure(ip=args.ip, password=os.environ["SCLITE_PASSWORD"])
                do_kick(dry=False)
            return

        # watch mode grace (force still respects grace unless --once)
        if alive_since is None:
            alive_since = now
            print(f"preferred looks recoverable; grace {args.grace}s …")
            return
        if now - alive_since < args.grace:
            print(f"grace {args.grace - (now - alive_since):.0f}s remaining")
            return
        if dry_run:
            print("Would kick (dry-run). Pass --apply to PUT + soft restart.")
            alive_since = None
            return
        if not os.environ.get("SCLITE_PASSWORD"):
            raise SystemExit("SCLITE_PASSWORD required for --apply")
        sc.configure(ip=args.ip, password=os.environ["SCLITE_PASSWORD"])
        do_kick(dry=False)
        alive_since = None

    if interval <= 0:
        tick()
        return
    print(f"watching every {interval}s  preferred=P{args.preferred}  apply={args.apply}")
    while True:
        try:
            tick()
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
