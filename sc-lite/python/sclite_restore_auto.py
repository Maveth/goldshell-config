#!/usr/bin/env python3
"""Restore manual=false and level-0 stock powerplan; keep tempcontrol=true."""
from __future__ import annotations

import time

import sclite_common as sc


def main() -> None:
    sc.login()
    cur = sc.get_setting()
    sc.print_snapshot("BEFORE")
    stock = None
    for p in cur.get("powerplans") or []:
        if p.get("level") == 0:
            stock = p.get("info")
            break
    if not stock:
        stock = cur.get("manualPowerplan")
    payload = dict(cur)
    payload["manual"] = False
    payload["manualPowerplan"] = stock
    payload["tempcontrol"] = True
    payload["select"] = 0
    print(f"RESTORE auto plan={stock}")
    sc.put_setting(payload)
    time.sleep(5)
    sc.print_snapshot("AFTER")


if __name__ == "__main__":
    main()
