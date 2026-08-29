#!/usr/bin/env python3
"""Set powerplan fan fields only; keep MHz/V/PV. Enables manual=true."""
from __future__ import annotations

import argparse
import time

import sclite_common as sc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fan", type=int, help="both RPM fields, e.g. 70")
    ap.add_argument("--wait", type=float, default=8.0)
    args = ap.parse_args()

    sc.login()
    before = sc.print_snapshot("BEFORE")
    cur = before["setting"]
    mhz, mv, _a, _b, pv = sc.parse_plan(str(cur.get("manualPowerplan")))
    new_plan = sc.build_plan(mhz, mv, args.fan, args.fan, pv)
    payload = dict(cur)
    payload["manual"] = True
    payload["manualPowerplan"] = new_plan
    payload["select"] = 0
    print(f"APPLY {cur.get('manualPowerplan')} -> {new_plan}")
    sc.put_setting(payload)
    time.sleep(args.wait)
    sc.print_snapshot("AFTER")


if __name__ == "__main__":
    main()
