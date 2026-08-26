#!/usr/bin/env python3
"""
tempcontrol OFF + fan kick with ACTIVE abort/restore.

CRITICAL safety:
  - Forces tempcontrol=true on abort, timeout, Ctrl+C, or error.
  - Refuses to start if already at/above abort temp.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

import sclite_common as sc

_restore_needed = False
_original: dict | None = None


def emergency_restore(reason: str) -> None:
    global _restore_needed
    print(f"\n!!! EMERGENCY RESTORE: {reason}", flush=True)
    try:
        sc.login()
        cur = sc.get_setting()
        payload = dict(cur)
        if _original:
            payload["manualPowerplan"] = _original.get(
                "manualPowerplan", payload.get("manualPowerplan")
            )
            payload["manual"] = _original.get("manual", False)
            payload["select"] = _original.get("select", 0)
        payload["tempcontrol"] = True
        try:
            mhz, mv, _a, _b, pv = sc.parse_plan(str(payload.get("manualPowerplan")))
            payload["manual"] = True
            payload["manualPowerplan"] = sc.build_plan(mhz, mv, 80, 80, pv)
        except Exception:
            pass
        sc.put_setting(payload)
        time.sleep(1)
        after = sc.get_setting()
        sc.print_snapshot("RESTORED")
        if after.get("tempcontrol") is True:
            print("OK: tempcontrol is TRUE again", flush=True)
            _restore_needed = False
        else:
            payload2 = dict(after)
            payload2["tempcontrol"] = True
            sc.put_setting(payload2)
            after2 = sc.get_setting()
            print("retry tc=", after2.get("tempcontrol"), flush=True)
            _restore_needed = after2.get("tempcontrol") is not True
    except Exception as e:
        print(f"FATAL: restore failed: {e}", flush=True)
        _restore_needed = True
        raise


def on_signal(signum, _frame) -> None:
    emergency_restore(f"signal {signum}")
    sys.exit(2)


def main() -> None:
    global _restore_needed, _original

    ap = argparse.ArgumentParser()
    ap.add_argument("--fan", type=int, default=70)
    ap.add_argument("--abort-c", type=float, default=88.0)
    ap.add_argument("--max-seconds", type=int, default=90)
    ap.add_argument("--poll", type=float, default=3.0)
    args = ap.parse_args()

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)

    print("=== tempcontrol OFF test (auto-abort) ===")
    print(
        f"fan={args.fan} abort_c={args.abort_c} "
        f"max_s={args.max_seconds} poll={args.poll}"
    )

    sc.login()
    before = sc.get_setting()
    _original = dict(before)
    boards0 = sc.print_snapshot("BEFORE")["boards"]
    if boards0.get("max_t") is not None and boards0["max_t"] >= args.abort_c:
        print(f"REFUSING: already hot maxT={boards0['max_t']}")
        sys.exit(1)

    mhz, mv, _a, _b, pv = sc.parse_plan(str(before.get("manualPowerplan")))
    kick = sc.build_plan(mhz, mv, args.fan, args.fan, pv)
    payload = dict(before)
    payload["tempcontrol"] = False
    payload["manual"] = True
    payload["manualPowerplan"] = kick
    payload["select"] = 0
    print(f"APPLY tc=FALSE plan={kick}", flush=True)
    sc.put_setting(payload)
    _restore_needed = True
    time.sleep(1)
    mid = sc.get_setting()
    sc.print_snapshot("ARMED")
    if mid.get("tempcontrol") is not False:
        emergency_restore("tc did not disable")
        sys.exit(1)

    t0 = time.time()
    peak = boards0.get("max_t") or 0.0
    try:
        while True:
            elapsed = time.time() - t0
            if elapsed >= args.max_seconds:
                emergency_restore(f"max duration {args.max_seconds}s")
                break
            boards = sc.board_snapshot()
            setting = sc.get_setting()
            mt = boards.get("max_t")
            if mt is not None:
                peak = max(peak, mt)
            fans0 = boards["boards"][0]["fans"] if boards["boards"] else "?"
            print(
                f"t={elapsed:5.1f}s maxT={mt} peak={peak:.1f} "
                f"tc={setting.get('tempcontrol')} fans0={fans0}",
                flush=True,
            )
            if mt is not None and mt >= args.abort_c:
                emergency_restore(f"maxT {mt} >= abort {args.abort_c}")
                break
            time.sleep(args.poll)
    except Exception as e:
        emergency_restore(f"exception: {e}")
        raise
    finally:
        if _restore_needed:
            emergency_restore("finally-guard")

    final = sc.get_setting()
    sc.print_snapshot("FINAL")
    if final.get("tempcontrol") is not True:
        print("CRITICAL: ended with tempcontrol != true", file=sys.stderr)
        sys.exit(3)
    print(f"DONE safe. peak_maxT={peak:.1f}C")


if __name__ == "__main__":
    main()
