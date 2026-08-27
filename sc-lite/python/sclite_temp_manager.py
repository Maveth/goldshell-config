#!/usr/bin/env python3
"""
SC Lite temperature manager — kick / ramp fans when boards are hot.

Modes (config control.mode):
  single  — BASIC: if temp >= on_temp → kick_fan (tempcontrol ON is fine)
  steps   — ADVANCED but safer: stepped thresholds with tempcontrol ON
            e.g. >=60→55, >=65→60, >=70→65 (highest match wins)
  smooth  — continuous ramp; intended for tempcontrol OFF so stock fanctrl
            does not fight you. Linear temp→fan map + weighted history blend.
            Fiddle smooth.* ranges to taste. Riskier — keep abort_c set.
            *** NOT fully tested yet — treat as experimental. ***

Example:
  set SCLITE_IP=192.168.0.202
  python sclite_temp_manager.py --config sclite_temp_manager.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
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
        "mode": "single",  # single | steps | smooth
        "on_temp": 80.5,
        "kick_fan": 70,
        "cooldown_s": 45,
        "poll_s": 3.0,
        "board": "max",
        "force_tempcontrol_on": True,
        # steps: highest matching temp threshold wins
        "steps": [
            {"temp": 60, "fan": 55},
            {"temp": 65, "fan": 60},
            {"temp": 70, "fan": 65},
        ],
        # smooth: map [min_temp..max_temp] → [min_fan..max_fan], then blend
        "smooth": {
            "min_temp": 60,
            "max_temp": 85,
            "min_fan": 40,
            "max_fan": 80,
            "history_len": 6,
            "history_weight": 3,
            "instant_weight": 1,
            "apply_interval_s": 5,
        },
    },
    "safety": {
        "abort_c": 90.0,
        "restore_auto_on_exit": False,
        # Opt-in: if PUT /mcb/setting keeps failing (GET often still works),
        # soft-restart via GET /mcb/restart after N minutes of sustained failure.
        # Default OFF — enable only when you accept unattended reboots.
        "put_fail_restart_enabled": False,
        "put_fail_restart_after_min": 5.0,
        "put_fail_restart_cooldown_min": 15.0,
        "put_fail_restart_wait_s": 120.0,
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
    mode: str = "single"
    on_temp: float = 80.5
    kick_fan: int = 70
    cooldown_s: float = 45.0
    poll_s: float = 3.0
    board: str | int = "max"
    force_tempcontrol_on: bool = True
    steps: list[tuple[float, int]] = field(default_factory=list)
    smooth_min_temp: float = 60.0
    smooth_max_temp: float = 85.0
    smooth_min_fan: int = 40
    smooth_max_fan: int = 80
    smooth_history_len: int = 6
    smooth_history_weight: float = 3.0
    smooth_instant_weight: float = 1.0
    smooth_apply_interval_s: float = 5.0
    abort_c: float = 90.0
    restore_auto_on_exit: bool = False
    put_fail_restart_enabled: bool = False
    put_fail_restart_after_min: float = 5.0
    put_fail_restart_cooldown_min: float = 15.0
    put_fail_restart_wait_s: float = 120.0
    interactive: bool = True
    paused: bool = False
    last_kick_ts: float = 0.0
    last_applied_fan: int | None = None
    kick_count: int = 0
    last_status: str = "boot"
    messages: list[str] = field(default_factory=list)
    fan_history: deque[float] = field(default_factory=deque)
    # Runtime: first PUT failure in current streak; last soft-restart time
    put_fail_since: float | None = None
    last_restart_ts: float = 0.0
    restart_count: int = 0

    def note(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.messages.append(f"[{ts}] {msg}")
        self.messages = self.messages[-8:]


def load_config(path: Path | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
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
    mode = str(c.get("mode", "single")).lower().strip()
    if mode not in ("single", "steps", "smooth"):
        raise SystemExit(f"unknown control.mode={mode!r} (use single|steps|smooth)")

    steps_raw = c.get("steps") or []
    steps: list[tuple[float, int]] = []
    for item in steps_raw:
        steps.append((float(item["temp"]), int(item["fan"])))
    steps.sort(key=lambda x: x[0])  # ascending by temp

    sm = c.get("smooth") or {}
    hist_len = max(1, int(sm.get("history_len", 6)))
    st = Settings(
        mode=mode,
        on_temp=float(c.get("on_temp", 80.5)),
        kick_fan=int(c.get("kick_fan", 70)),
        cooldown_s=float(c.get("cooldown_s", 45)),
        poll_s=float(c.get("poll_s", 3.0)),
        board=board,
        force_tempcontrol_on=bool(c.get("force_tempcontrol_on", True)),
        steps=steps,
        smooth_min_temp=float(sm.get("min_temp", 60)),
        smooth_max_temp=float(sm.get("max_temp", 85)),
        smooth_min_fan=int(sm.get("min_fan", 40)),
        smooth_max_fan=int(sm.get("max_fan", 80)),
        smooth_history_len=hist_len,
        smooth_history_weight=float(sm.get("history_weight", 3)),
        smooth_instant_weight=float(sm.get("instant_weight", 1)),
        smooth_apply_interval_s=float(sm.get("apply_interval_s", 5)),
        abort_c=float(s["abort_c"]),
        restore_auto_on_exit=bool(s.get("restore_auto_on_exit", False)),
        put_fail_restart_enabled=bool(s.get("put_fail_restart_enabled", False)),
        put_fail_restart_after_min=float(s.get("put_fail_restart_after_min", 5.0)),
        put_fail_restart_cooldown_min=float(
            s.get("put_fail_restart_cooldown_min", 15.0)
        ),
        put_fail_restart_wait_s=float(s.get("put_fail_restart_wait_s", 120.0)),
        interactive=bool(u.get("interactive", True)),
        fan_history=deque(maxlen=hist_len),
    )
    return st


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


def target_fan_for_temp(st: Settings, temp: float) -> int | None:
    """Return desired fan field, or None = no change / below control range."""
    if st.mode == "single":
        if temp >= st.on_temp:
            return st.kick_fan
        return None

    if st.mode == "steps":
        chosen: int | None = None
        for thr, fan in st.steps:
            if temp >= thr:
                chosen = fan
        return chosen

    if st.mode == "smooth":
        # Fiddle smooth.min_temp/max_temp/min_fan/max_fan to taste.
        if temp <= st.smooth_min_temp:
            instant = float(st.smooth_min_fan)
        elif temp >= st.smooth_max_temp:
            instant = float(st.smooth_max_fan)
        else:
            span_t = max(1e-6, st.smooth_max_temp - st.smooth_min_temp)
            span_f = st.smooth_max_fan - st.smooth_min_fan
            instant = st.smooth_min_fan + (temp - st.smooth_min_temp) / span_t * span_f

        # Weighted history (newest heaviest), like community IPMI ramp:
        # avg = sum(hist[i] * (n-i)) / sum(1..n); blend = (avg*Hw + instant*Iw)/(Hw+Iw)
        st.fan_history.appendleft(instant)
        n = len(st.fan_history)
        weights = list(range(n, 0, -1))  # newest index 0 gets weight n
        wsum = sum(weights)
        avg = sum(v * w for v, w in zip(st.fan_history, weights)) / wsum
        hw = st.smooth_history_weight
        iw = st.smooth_instant_weight
        blended = (avg * hw + instant * iw) / max(1e-6, hw + iw)
        return int(round(max(1, min(100, blended))))

    return None


def apply_fan(st: Settings, fan: int, why: str) -> None:
    cur = sc.get_setting()
    mhz, mv, _a, _b, pv = sc.parse_plan(str(cur.get("manualPowerplan")))
    new_plan = sc.build_plan(mhz, mv, fan, fan, pv)
    payload = dict(cur)
    payload["manual"] = True
    payload["manualPowerplan"] = new_plan
    payload["select"] = 0
    # Explicit: smooth usually wants tc OFF; single/steps usually ON.
    payload["tempcontrol"] = bool(st.force_tempcontrol_on)
    sc.put_setting(payload)
    st.put_fail_since = None  # PUT worked again
    st.last_kick_ts = time.time()
    st.last_applied_fan = fan
    st.kick_count += 1
    st.last_status = f"{why} fan={fan}"
    st.note(f"#{st.kick_count} {why} -> {new_plan}")


def mark_put_fail(st: Settings, err: Exception | BaseException) -> None:
    if st.put_fail_since is None:
        st.put_fail_since = time.time()
    st.note(f"apply failed: {err}")
    st.last_status = f"ERROR {err}"


def maybe_auto_restart(st: Settings) -> bool:
    """If PUT has failed long enough, soft-restart the miner (opt-in).

    Returns True if a restart was attempted (caller should skip normal render
    / treat this poll as recovery). Uses GET /mcb/restart — works even when
    PUT is wedged. Never calls /mcb/facrst.
    """
    if not st.put_fail_restart_enabled:
        return False
    if st.put_fail_since is None:
        return False
    elapsed_min = (time.time() - st.put_fail_since) / 60.0
    if elapsed_min < st.put_fail_restart_after_min:
        return False
    if st.last_restart_ts > 0:
        since_restart = (time.time() - st.last_restart_ts) / 60.0
        if since_restart < st.put_fail_restart_cooldown_min:
            left = st.put_fail_restart_cooldown_min - since_restart
            st.last_status = f"PUT_FAIL restart_cd {left:.0f}m"
            return False

    st.note(
        f"PUT failed for {elapsed_min:.1f}m — soft restart "
        f"(after_min={st.put_fail_restart_after_min:g})"
    )
    st.last_status = "SOFT_RESTART"
    print(
        f"\n[{time.strftime('%H:%M:%S')}] PUT wedged ~{elapsed_min:.1f}m — "
        f"soft restart via GET /mcb/restart …",
        flush=True,
    )
    try:
        msg = sc.soft_restart()
        st.note(msg)
        print(f"  {msg}", flush=True)
    except Exception as e:
        st.note(f"soft_restart failed: {e}")
        st.last_status = f"RESTART_FAIL {e}"
        st.last_restart_ts = time.time()  # backoff even on failure
        print(f"  soft_restart failed: {e}", flush=True)
        return True

    st.last_restart_ts = time.time()
    st.restart_count += 1
    print(
        f"  waiting up to {st.put_fail_restart_wait_s:.0f}s for miner …",
        flush=True,
    )
    ok = sc.wait_until_up(timeout_s=st.put_fail_restart_wait_s)
    if ok:
        st.note(f"miner up after soft restart #{st.restart_count}")
        st.put_fail_since = None
        st.last_applied_fan = None  # force re-apply after reboot
        st.last_status = "RESTARTED_OK"
        print("  miner back up — will re-apply fans next cycle", flush=True)
    else:
        st.note("miner did not come back in time after soft restart")
        st.last_status = "RESTART_TIMEOUT"
        print("  miner did not come back in time", flush=True)
    return True


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
        msvcrt.getwch()
        return None
    return ch


def render(
    st: Settings,
    setting: dict,
    boards: dict,
    watched: float | None,
    board_row,
    desired: int | None,
) -> None:
    sys.stdout.write("\033[H\033[J")
    interval = (
        st.smooth_apply_interval_s if st.mode == "smooth" else st.cooldown_s
    )
    cd_left = 0.0
    if st.last_kick_ts > 0:
        cd_left = max(0.0, interval - (time.time() - st.last_kick_ts))
    pause = "PAUSED" if st.paused else "RUN"
    print("SC Lite temp manager")
    tc_hint = {
        "single": "basic (tc ON ok)",
        "steps": "advanced/safer (tc ON ok)",
        "smooth": "ramp — prefer tc OFF",
    }.get(st.mode, "")
    print(
        f"host={sc.host()}  ctrl={st.mode} [{tc_hint}]  {pause}  "
        f"status={st.last_status}"
    )
    print(
        f"plan={setting.get('manualPowerplan')}  "
        f"manual={setting.get('manual')}  tc={setting.get('tempcontrol')}"
    )
    if st.mode == "single":
        print(
            f"on_temp={st.on_temp:.1f}C  kick_fan={st.kick_fan}  "
            f"cooldown={st.cooldown_s:.0f}s (left {cd_left:.0f}s)"
        )
    elif st.mode == "steps":
        step_s = " ".join(f"{t:g}→{f}" for t, f in st.steps)
        print(f"steps: {step_s}  cooldown={st.cooldown_s:.0f}s (left {cd_left:.0f}s)")
    else:
        print(
            f"smooth: temp {st.smooth_min_temp:g}..{st.smooth_max_temp:g}C → "
            f"fan {st.smooth_min_fan}..{st.smooth_max_fan}  "
            f"blend hist*{st.smooth_history_weight:g}+inst*{st.smooth_instant_weight:g}  "
            f"apply every {st.smooth_apply_interval_s:g}s (left {cd_left:.0f}s)"
        )
    print(
        f"abort={st.abort_c:.1f}C  board={st.board}  applies={st.kick_count}  "
        f"desired={desired if desired is not None else '-'}  "
        f"last={st.last_applied_fan if st.last_applied_fan is not None else '-'}"
    )
    if st.put_fail_restart_enabled:
        fail_s = ""
        if st.put_fail_since is not None:
            fail_m = (time.time() - st.put_fail_since) / 60.0
            fail_s = f"  put_fail={fail_m:.1f}m/{st.put_fail_restart_after_min:g}m"
        print(
            f"put_fail_restart=ON after {st.put_fail_restart_after_min:g}m  "
            f"cooldown={st.put_fail_restart_cooldown_min:g}m  "
            f"restarts={st.restart_count}{fail_s}"
        )
    print("-" * 72)
    print(f"{'BOARD':<6} {'TEMP':>8} {'FANS':<40} {'TH/s':>8}")
    for b in boards.get("boards") or []:
        mark = " <-- watch" if board_row and b.get("id") == board_row.get("id") else ""
        print(
            f"{str(b.get('id')):<6} {str(b.get('temp')):>8} "
            f"{str(b.get('fans')):<40} {b.get('hr_ths', 0):8.3f}{mark}"
        )
    print("-" * 72)
    w = f"{watched:.1f}C" if watched is not None else "n/a"
    print(f"watched temp: {w}")
    print(
        "keys: m cycle-mode   [ ] on_temp (single)   { } kick_fan (single)   "
        "p pause  k force  r restore  s save  q quit"
    )
    if st.messages:
        print("log:")
        for m in st.messages[-5:]:
            print(" ", m)
    sys.stdout.flush()


def save_runtime_config(path: Path, cfg: dict, st: Settings) -> None:
    out = json.loads(json.dumps(cfg))
    out["control"]["mode"] = st.mode
    out["control"]["on_temp"] = st.on_temp
    out["control"]["kick_fan"] = st.kick_fan
    out["control"]["cooldown_s"] = st.cooldown_s
    out["control"]["poll_s"] = st.poll_s
    out["control"]["board"] = st.board
    out["control"]["steps"] = [{"temp": t, "fan": f} for t, f in st.steps]
    out["control"]["smooth"] = {
        "min_temp": st.smooth_min_temp,
        "max_temp": st.smooth_max_temp,
        "min_fan": st.smooth_min_fan,
        "max_fan": st.smooth_max_fan,
        "history_len": st.smooth_history_len,
        "history_weight": st.smooth_history_weight,
        "instant_weight": st.smooth_instant_weight,
        "apply_interval_s": st.smooth_apply_interval_s,
    }
    out["safety"]["abort_c"] = st.abort_c
    out["safety"]["restore_auto_on_exit"] = st.restore_auto_on_exit
    out["safety"]["put_fail_restart_enabled"] = st.put_fail_restart_enabled
    out["safety"]["put_fail_restart_after_min"] = st.put_fail_restart_after_min
    out["safety"]["put_fail_restart_cooldown_min"] = (
        st.put_fail_restart_cooldown_min
    )
    out["safety"]["put_fail_restart_wait_s"] = st.put_fail_restart_wait_s
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    st.note(f"saved {path}")


def handle_key(ch: str, st: Settings, cfg: dict, cfg_path: Path | None) -> str | None:
    if ch in ("q", "Q"):
        return "quit"
    if ch in ("p", "P"):
        st.paused = not st.paused
        st.note("paused" if st.paused else "resumed")
    elif ch in ("m", "M"):
        order = ["single", "steps", "smooth"]
        i = order.index(st.mode) if st.mode in order else 0
        st.mode = order[(i + 1) % len(order)]
        st.note(f"mode={st.mode}")
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
            fan = st.last_applied_fan or st.kick_fan
            if st.mode == "steps" and st.steps:
                fan = st.steps[-1][1]
            apply_fan(st, fan, "FORCE")
        except Exception as e:
            mark_put_fail(st, e)
            maybe_auto_restart(st)
    elif ch in ("r", "R"):
        try:
            restore_auto()
            st.put_fail_since = None
            st.note("restored auto/stock plan")
            st.last_status = "RESTORED_AUTO"
            st.last_applied_fan = None
        except Exception as e:
            mark_put_fail(st, e)
            maybe_auto_restart(st)
    elif ch in ("s", "S"):
        dest = cfg_path or Path("sclite_temp_manager.runtime.json")
        try:
            save_runtime_config(dest, cfg, st)
        except Exception as e:
            st.note(f"save failed: {e}")
    return None


def control_step(st: Settings) -> str:
    try:
        setting = sc.get_setting()
        boards = sc.board_snapshot()
    except Exception as e:
        # Miner may be mid-reboot after soft restart, or briefly unreachable.
        st.last_status = f"API_DOWN {e}"
        st.note(st.last_status)
        if st.put_fail_since is None:
            # Treat total API loss like a PUT wedge for restart purposes only
            # if we already had PUT problems; otherwise just wait.
            pass
        if st.put_fail_since is not None and maybe_auto_restart(st):
            return "restarted"
        if not st.interactive:
            print(
                f"t={time.strftime('%H:%M:%S')} status={st.last_status}",
                flush=True,
            )
        return "ok"

    watched, row = watched_temp(boards, st.board)
    desired: int | None = None
    if watched is not None:
        desired = target_fan_for_temp(st, watched)

    if watched is not None and watched >= st.abort_c:
        st.last_status = f"ABORT {watched}>={st.abort_c}"
        st.note(st.last_status)
        try:
            apply_fan(st, max(st.kick_fan, st.smooth_max_fan, 80), "ABORT")
        except Exception as e:
            mark_put_fail(st, e)
            maybe_auto_restart(st)
        if st.interactive:
            render(st, setting, boards, watched, row, desired)
        else:
            print(st.last_status)
        return "abort"

    if st.paused:
        st.last_status = "PAUSED"
        if st.interactive:
            render(st, setting, boards, watched, row, desired)
        return "ok"

    now = time.time()
    interval = (
        st.smooth_apply_interval_s if st.mode == "smooth" else st.cooldown_s
    )
    in_cooldown = st.last_kick_ts > 0 and (now - st.last_kick_ts) < interval

    if desired is not None and not in_cooldown:
        # With tempcontrol ON, a kick is only a pulse (~1–3 min live fans).
        # single/steps must RE-APPLY after cooldown while still in-zone,
        # otherwise we HOLD forever and never re-pulse (looks "stuck in zone 2").
        # When tc is OFF the plan sticks — skip redundant PUTs if unchanged.
        same = st.last_applied_fan == desired
        if same and st.mode == "smooth":
            st.last_status = f"SMOOTH hold={desired}"
            st.last_kick_ts = now
        elif same and not st.force_tempcontrol_on:
            st.last_status = f"HOLD fan={desired}"
        else:
            try:
                why = st.mode.upper()
                if same:
                    why = f"{why}_REPULSE"
                apply_fan(st, desired, why)
            except Exception as e:
                mark_put_fail(st, e)
                if maybe_auto_restart(st):
                    return "restarted"
    elif in_cooldown:
        st.last_status = "COOLDOWN"
    elif desired is None:
        # Below all step thresholds / below on_temp — clear latch so a
        # later rise re-enters cleanly; optional: could restore_auto here.
        st.last_status = "IDLE_COOL"
        if st.last_applied_fan is not None and not in_cooldown:
            # Allow next zone entry to always PUT even if same fan number
            st.last_applied_fan = None
    else:
        st.last_status = "IDLE"

    # Timer-based restart even if we are not applying this cycle
    # (e.g. still in ERROR streak / waiting for threshold).
    if st.put_fail_since is not None and maybe_auto_restart(st):
        return "restarted"

    try:
        setting = sc.get_setting()
        boards = sc.board_snapshot()
        watched, row = watched_temp(boards, st.board)
        if watched is not None:
            desired = target_fan_for_temp(st, watched)
    except Exception:
        pass

    if st.interactive:
        render(st, setting, boards, watched, row, desired)
    else:
        fans0 = (boards.get("boards") or [{}])[0].get("fans")
        print(
            f"t={time.strftime('%H:%M:%S')} mode={st.mode} watched={watched} "
            f"desired={desired} fans0={fans0} status={st.last_status} "
            f"applies={st.kick_count}"
        )
    return "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description="SC Lite fan / temp manager")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument(
        "--mode",
        choices=["single", "steps", "smooth"],
        default=None,
        help="override control.mode",
    )
    ap.add_argument("--on-temp", type=float, default=None)
    ap.add_argument("--kick-fan", type=int, default=None)
    ap.add_argument("--cooldown", type=float, default=None)
    ap.add_argument("--poll", type=float, default=None)
    ap.add_argument("--abort-c", type=float, default=None)
    ap.add_argument("--board", default=None)
    ap.add_argument(
        "--put-fail-restart",
        action="store_true",
        help="enable soft restart after sustained PUT failures (default off)",
    )
    ap.add_argument(
        "--put-fail-restart-after-min",
        type=float,
        default=None,
        help="minutes of PUT failure before soft restart (default 5)",
    )
    ap.add_argument("--no-ui", action="store_true")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    miner = cfg.get("miner") or {}
    ip = miner.get("ip") or os.environ.get("SCLITE_IP") or ""
    password = miner.get("password") or os.environ.get("SCLITE_PASSWORD") or ""
    if ip and "x.x" not in ip:
        sc.configure(ip=ip, password=password if password else None)
    elif password:
        sc.configure(password=password)

    st = settings_from_config(cfg)
    if args.mode:
        st.mode = args.mode
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
    if args.put_fail_restart:
        st.put_fail_restart_enabled = True
    if args.put_fail_restart_after_min is not None:
        st.put_fail_restart_after_min = args.put_fail_restart_after_min
        st.put_fail_restart_enabled = True  # implying enable when threshold set
    if args.no_ui:
        st.interactive = False

    if st.abort_c <= (
        st.on_temp if st.mode == "single" else st.smooth_max_temp
    ):
        print(
            f"WARNING: abort_c ({st.abort_c}) is low vs control range; "
            "raising abort_c",
            file=sys.stderr,
        )
        st.abort_c = max(st.abort_c, st.on_temp + 5, st.smooth_max_temp + 5)

    print(
        f"connecting {sc.host()} mode={st.mode} abort={st.abort_c} "
        f"poll={st.poll_s}s"
    )
    if st.put_fail_restart_enabled:
        print(
            f"put_fail_restart=ON after {st.put_fail_restart_after_min:g}m "
            f"(cooldown {st.put_fail_restart_cooldown_min:g}m, "
            f"wait {st.put_fail_restart_wait_s:g}s) — GET /mcb/restart only",
            flush=True,
        )
    if st.mode == "smooth" and st.force_tempcontrol_on:
        print(
            "NOTE: smooth mode works best with tempcontrol OFF "
            "(set force_tempcontrol_on=false). Stock fanctrl fights continuous ramps.",
            file=sys.stderr,
        )
    if st.mode in ("single", "steps") and not st.force_tempcontrol_on:
        print(
            "NOTE: single/steps are safer with tempcontrol ON "
            "(force_tempcontrol_on=true).",
            file=sys.stderr,
        )
    sc.login()
    st.note("logged in")

    exit_code = 0
    try:
        while True:
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
