#!/usr/bin/env python3
"""
SC Lite temperature manager — kick fans when a board is hot.

Design (v1):
  - Poll board temps / fans over JWT HTTP API
  - If watched temp >= on_temp, PUT fan fields to kick_fan (keep MHz/V/PV)
  - Enforce cooldown_s between kicks (fans fade in auto mode after ~1–3 min)
  - Interactive TUI: live temps/fans; adjust on_temp / kick_fan on the fly
  - Abort if temp >= abort_c; optional restore-auto on exit

Example:
  set SCLITE_IP=192.168.0.202
  python sclite_temp_manager.py --config sclite_temp_manager.example.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sclite_common as sc

try:
    import msvcrt  # Windows
except ImportError:
    msvcrt = None  # type: ignore


DEFAULTS = {
    "miner": {"ip": "", "password": ""},
    "control": {
        "on_temp": 80.5,
        "kick_fan": 70,
        "cooldown_s": 45,
        "poll_s": 3.0,
        "board": "max",  # "max" or 0..3
        "force_tempcontrol_on": True,
    },
    "safety": {
        "abort_c": 90.0,
        "restore_auto_on_exit": False,
    },
    "ui": {"interactive": True},
}


def deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Settings:
    on_temp: float = 80.5
    kick_fan: int = 70
    cooldown_s: float = 45.0
    poll_s: float = 3.0
    board: str | int = "max"
    force_tempcontrol_on: bool = True
    abort_c: float = 90.0
    restore_auto_on_exit: bool = False
    interactive: bool = True
    paused: bool = False
    last_kick_ts: float = 0.0
    last_status: str = "boot"
    kick_count: int = 0
    messages: list[str] = field(default_factory=list)

    def note(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.messages.append(f"[{ts}] {msg}")
        self.messages = self.messages[-8:]


def load_config(path: Path | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy via json
    if path is None:
        return cfg
    data = json.loads(path.read_text(encoding="utf-8"))
    return deep_merge(cfg, data)


def settings_from_config(cfg: dict) -> Settings:
    c = cfg["control"]
    s = cfg["safety"]
    u = cfg["ui"]
    board: str | int = c.get("board", "max")
    if board != "max":
        board = int(board)
    return Settings(
        on_temp=float(c["on_temp"]),
        kick_fan=int(c["kick_fan"]),
        cooldown_s=float(c["cooldown_s"]),
        poll_s=float(c["poll_s"]),
        board=board,
        force_tempcontrol_on=bool(c.get("force_tempcontrol_on", True)),
        abort_c=float(s["abort_c"]),
        restore_auto_on_exit=bool(s.get("restore_auto_on_exit", False)),
        interactive=bool(u.get("interactive", True)),
    )


def watched_temp(boards: dict, which: str | int) -> tuple[float | None, Any]:
    rows = boards.get("boards") or []
    if not rows:
        return None, None
    if which == "max":
        best = None
        best_t = None
        for b in rows:
            t = b.get("temp")
            if t is None:
                continue
            if best_t is None or t > best_t:
                best_t = t
                best = b
        return best_t, best
    for b in rows:
        if b.get("id") == which or str(b.get("id")) == str(which):
            return b.get("temp"), b
    return None, None


def kick_fans(st: Settings) -> None:
    cur = sc.get_setting()
    mhz, mv, _a, _b, pv = sc.parse_plan(str(cur.get("manualPowerplan")))
    new_plan = sc.build_plan(mhz, mv, st.kick_fan, st.kick_fan, pv)
    payload = dict(cur)
    payload["manual"] = True
    payload["manualPowerplan"] = new_plan
    payload["select"] = 0
    if st.force_tempcontrol_on:
        payload["tempcontrol"] = True
    sc.put_setting(payload)
    st.last_kick_ts = time.time()
    st.kick_count += 1
    st.last_status = f"KICKED fan={st.kick_fan}"
    st.note(f"kick #{st.kick_count} -> {new_plan}")


def restore_auto() -> None:
    cur = sc.get_setting()
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
    sc.put_setting(payload)


def read_key() -> str | None:
    if msvcrt is None:
        return None
    if not msvcrt.kbhit():
        return None
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        msvcrt.getwch()  # swallow arrow prefix
        return None
    return ch


def render(st: Settings, setting: dict, boards: dict, watched: float | None, board_row) -> None:
    # ANSI clear — works in Windows Terminal / modern consoles
    sys.stdout.write("\033[H\033[J")
    cd_left = max(0.0, st.cooldown_s - (time.time() - st.last_kick_ts))
    if st.last_kick_ts <= 0:
        cd_left = 0.0
    pause = "PAUSED" if st.paused else "RUN"
    print("SC Lite temp manager")
    print(f"host={sc.host()}  mode={pause}  status={st.last_status}")
    print(
        f"plan={setting.get('manualPowerplan')}  "
        f"manual={setting.get('manual')}  tc={setting.get('tempcontrol')}"
    )
    print(
        f"on_temp={st.on_temp:.1f}C  kick_fan={st.kick_fan}  "
        f"cooldown={st.cooldown_s:.0f}s (left {cd_left:.0f}s)  "
        f"abort={st.abort_c:.1f}C  board={st.board}  kicks={st.kick_count}"
    )
    print("-" * 72)
    print(f"{'BOARD':<6} {'TEMP':>8} {'FANS':<40} {'TH/s':>8}")
    for b in boards.get("boards") or []:
        mark = ""
        if board_row and b.get("id") == board_row.get("id"):
            mark = " <-- watch"
        print(
            f"{str(b.get('id')):<6} {str(b.get('temp')):>8} "
            f"{str(b.get('fans')):<40} {b.get('hr_ths', 0):8.3f}{mark}"
        )
    print("-" * 72)
    w = f"{watched:.1f}C" if watched is not None else "n/a"
    print(f"watched temp: {w}")
    print(
        "keys: [ / ] on_temp -0.5/+0.5   { / } kick_fan -5/+5   "
        "p pause  k force-kick  r restore-auto  s save-config  q quit"
    )
    if st.messages:
        print("log:")
        for m in st.messages[-5:]:
            print(" ", m)
    sys.stdout.flush()


def save_runtime_config(path: Path, cfg: dict, st: Settings) -> None:
    out = json.loads(json.dumps(cfg))
    out["control"]["on_temp"] = st.on_temp
    out["control"]["kick_fan"] = st.kick_fan
    out["control"]["cooldown_s"] = st.cooldown_s
    out["control"]["poll_s"] = st.poll_s
    out["control"]["board"] = st.board
    out["safety"]["abort_c"] = st.abort_c
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    st.note(f"saved {path}")


def handle_key(ch: str, st: Settings, cfg: dict, cfg_path: Path | None) -> str | None:
    """Return 'quit' to exit, else None."""
    if ch in ("q", "Q"):
        return "quit"
    if ch in ("p", "P"):
        st.paused = not st.paused
        st.note("paused" if st.paused else "resumed")
    elif ch == "[":
        st.on_temp = round(st.on_temp - 0.5, 1)
        st.note(f"on_temp={st.on_temp}")
    elif ch == "]":
        st.on_temp = round(st.on_temp + 0.5, 1)
        st.note(f"on_temp={st.on_temp}")
    elif ch == "{":
        st.kick_fan = max(10, st.kick_fan - 5)
        st.note(f"kick_fan={st.kick_fan}")
    elif ch == "}":
        st.kick_fan = min(100, st.kick_fan + 5)
        st.note(f"kick_fan={st.kick_fan}")
    elif ch in ("k", "K"):
        try:
            kick_fans(st)
        except Exception as e:
            st.note(f"kick failed: {e}")
    elif ch in ("r", "R"):
        try:
            restore_auto()
            st.note("restored auto/stock plan")
            st.last_status = "RESTORED_AUTO"
        except Exception as e:
            st.note(f"restore failed: {e}")
    elif ch in ("s", "S"):
        dest = cfg_path or Path("sclite_temp_manager.runtime.json")
        try:
            save_runtime_config(dest, cfg, st)
        except Exception as e:
            st.note(f"save failed: {e}")
    return None


def control_step(st: Settings) -> str:
    """One poll/control iteration. Returns 'ok' or 'abort'."""
    setting = sc.get_setting()
    boards = sc.board_snapshot()
    watched, row = watched_temp(boards, st.board)

    if watched is not None and watched >= st.abort_c:
        st.last_status = f"ABORT {watched}>={st.abort_c}"
        st.note(st.last_status)
        # emergency: kick high + ensure tempcontrol on
        try:
            saved_fan = st.kick_fan
            st.kick_fan = max(st.kick_fan, 80)
            st.force_tempcontrol_on = True
            kick_fans(st)
            st.kick_fan = saved_fan
        except Exception as e:
            st.note(f"abort kick failed: {e}")
        if st.interactive:
            render(st, setting, boards, watched, row)
        else:
            print(st.last_status)
        return "abort"

    if st.paused:
        st.last_status = "PAUSED"
        return "ok"

    now = time.time()
    in_cooldown = st.last_kick_ts > 0 and (now - st.last_kick_ts) < st.cooldown_s
    if watched is not None and watched >= st.on_temp and not in_cooldown:
        try:
            kick_fans(st)
        except Exception as e:
            st.note(f"auto kick failed: {e}")
            st.last_status = f"ERROR {e}"
    elif in_cooldown:
        st.last_status = "COOLDOWN"
    elif watched is not None and watched < st.on_temp:
        st.last_status = "IDLE_COOL"
    else:
        st.last_status = "IDLE"

    # Refresh setting after possible PUT so UI/log show the new plan
    try:
        setting = sc.get_setting()
        boards = sc.board_snapshot()
        watched, row = watched_temp(boards, st.board)
    except Exception:
        pass

    if st.interactive:
        render(st, setting, boards, watched, row)
    else:
        fans0 = (boards.get("boards") or [{}])[0].get("fans")
        print(
            f"t={time.strftime('%H:%M:%S')} watched={watched} "
            f"on={st.on_temp} fans0={fans0} status={st.last_status} "
            f"paused={st.paused} kicks={st.kick_count}"
        )

    return "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description="SC Lite fan kick temp manager")
    ap.add_argument(
        "--config",
        type=Path,
        default=None,
        help="JSON config (see sclite_temp_manager.example.json)",
    )
    ap.add_argument("--on-temp", type=float, default=None)
    ap.add_argument("--kick-fan", type=int, default=None)
    ap.add_argument("--cooldown", type=float, default=None)
    ap.add_argument("--poll", type=float, default=None)
    ap.add_argument("--abort-c", type=float, default=None)
    ap.add_argument("--board", default=None, help="'max' or board id 0..3")
    ap.add_argument("--no-ui", action="store_true", help="headless log mode")
    ap.add_argument(
        "--once",
        action="store_true",
        help="single poll/control step then exit",
    )
    args = ap.parse_args()

    cfg = load_config(args.config)
    miner = cfg.get("miner") or {}
    ip = miner.get("ip") or os.environ.get("SCLITE_IP") or ""
    password = miner.get("password") or os.environ.get("SCLITE_PASSWORD") or ""
    if ip:
        sc.configure(ip=ip, password=password if password else None)
    elif password:
        sc.configure(password=password)

    st = settings_from_config(cfg)
    if args.on_temp is not None:
        st.on_temp = args.on_temp
    if args.kick_fan is not None:
        st.kick_fan = args.kick_fan
    if args.cooldown is not None:
        st.cooldown_s = args.cooldown
    if args.poll is not None:
        st.poll_s = args.poll
    if args.abort_c is not None:
        st.abort_c = args.abort_c
    if args.board is not None:
        st.board = args.board if args.board == "max" else int(args.board)
    if args.no_ui:
        st.interactive = False

    if st.abort_c <= st.on_temp:
        print(
            f"WARNING: abort_c ({st.abort_c}) <= on_temp ({st.on_temp}); "
            "raising abort_c to on_temp+5",
            file=sys.stderr,
        )
        st.abort_c = st.on_temp + 5.0

    print(
        f"connecting {sc.host()} on_temp={st.on_temp} kick_fan={st.kick_fan} "
        f"cooldown={st.cooldown_s}s abort={st.abort_c}"
    )
    sc.login()
    st.note("logged in")

    exit_code = 0
    try:
        while True:
            # drain keys during wait for snappy UI
            deadline = time.time() + st.poll_s
            while True:
                if st.interactive:
                    ch = read_key()
                    if ch:
                        action = handle_key(ch, st, cfg, args.config)
                        if action == "quit":
                            raise KeyboardInterrupt
                if args.once or time.time() >= deadline:
                    break
                time.sleep(0.05)

            result = control_step(st)
            if result == "abort":
                exit_code = 2
                break
            if args.once:
                break
    except KeyboardInterrupt:
        st.note("exit requested")
        if st.interactive:
            print("\nexiting…")
    finally:
        if st.restore_auto_on_exit:
            try:
                restore_auto()
                print("restored auto/stock on exit")
            except Exception as e:
                print(f"restore on exit failed: {e}", file=sys.stderr)
                exit_code = max(exit_code, 1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
