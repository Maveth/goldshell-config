#!/usr/bin/env python3
"""Watch fans/temps over time (no setting changes)."""
from __future__ import annotations

import argparse
import time

import sclite_common as sc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=210)
    ap.add_argument("--every", type=int, default=30)
    args = ap.parse_args()

    sc.login()
    setting = sc.get_setting()
    print(
        "watching (no writes) "
        f"manual={setting.get('manual')} tc={setting.get('tempcontrol')} "
        f"plan={setting.get('manualPowerplan')}"
    )
    print(f"{'t_s':>5}  {'maxT':>5}  {'minT':>5}  fans(board0)")
    t0 = time.time()
    next_t = 0
    while True:
        elapsed = time.time() - t0
        if elapsed >= next_t:
            boards = sc.board_snapshot()
            fans0 = boards["boards"][0]["fans"] if boards["boards"] else "?"
            print(
                f"{int(elapsed):5d}  {boards.get('max_t')!s:>5}  "
                f"{boards.get('min_t')!s:>5}  {fans0}"
            )
            next_t += args.every
        if elapsed >= args.seconds:
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
