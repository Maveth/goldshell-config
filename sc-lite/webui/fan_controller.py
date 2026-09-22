#!/usr/bin/env python3
"""Background auto fan-kick for webui.

Stock SC Lite ``fanctrl`` walks duty back toward ~85 C after a kick (must re-pulse).
``tempcontrol=false`` does **not** stop that walk (verified 2026-09-22) — keep the
flag on for safety; re-pulse either way.
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable

# threading used for FanController daemon loop

# Built-in profiles (also overridable via miners.json "profiles")
BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "steps-default": {
        "label": "Steps 70/80/85 → fan 70/80/90",
        "mode": "steps",
        "cooldown_s": 120,
        "poll_s": 4.0,
        "board": "max",
        "force_tempcontrol_on": True,
        "abort_c": 90.0,
        "steps": [
            {"temp": 70, "fan": 70},
            {"temp": 80, "fan": 80},
            {"temp": 85, "fan": 90},
        ],
    },
    "steps-aggressive": {
        "label": "Steps 65/75/82 → fan 75/85/95",
        "mode": "steps",
        "cooldown_s": 90,
        "poll_s": 4.0,
        "board": "max",
        "force_tempcontrol_on": True,
        "abort_c": 90.0,
        "steps": [
            {"temp": 65, "fan": 75},
            {"temp": 75, "fan": 85},
            {"temp": 82, "fan": 95},
        ],
    },
    "single-80": {
        "label": "Single: ≥80°C kick fan 90",
        "mode": "single",
        "on_temp": 80,
        "kick_fan": 90,
        "cooldown_s": 120,
        "poll_s": 4.0,
        "board": "max",
        "force_tempcontrol_on": True,
        "abort_c": 90.0,
    },
    "smooth": {
        "label": "Smooth ramp (experimental)",
        "mode": "smooth",
        "smooth_min_temp": 65,
        "smooth_max_temp": 85,
        "smooth_min_fan": 40,
        "smooth_max_fan": 95,
        "smooth_apply_interval_s": 15,
        "smooth_history_weight": 2.0,
        "smooth_instant_weight": 1.0,
        "poll_s": 4.0,
        "board": "max",
        # OFF does not stop stock walk — keep ON (2026-09-22 SC Lite finding)
        "force_tempcontrol_on": True,
        "abort_c": 92.0,
    },
}


def merge_profiles(custom: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out = {k: dict(v) for k, v in BUILTIN_PROFILES.items()}
    if isinstance(custom, dict):
        for k, v in custom.items():
            if isinstance(v, dict):
                base = dict(out.get(k) or {})
                base.update(v)
                out[k] = base
    return out


def target_fan(profile: dict[str, Any], temp: float, history: list[float]) -> int | None:
    mode = (profile.get("mode") or "steps").lower()
    if mode == "single":
        if temp >= float(profile.get("on_temp", 80)):
            return int(profile.get("kick_fan", 90))
        return None
    if mode == "steps":
        chosen = None
        for step in profile.get("steps") or []:
            if temp >= float(step.get("temp", 999)):
                chosen = int(step.get("fan", 70))
        return chosen
    if mode == "smooth":
        t0 = float(profile.get("smooth_min_temp", 65))
        t1 = float(profile.get("smooth_max_temp", 85))
        f0 = float(profile.get("smooth_min_fan", 40))
        f1 = float(profile.get("smooth_max_fan", 95))
        if temp <= t0:
            instant = f0
        elif temp >= t1:
            instant = f1
        else:
            instant = f0 + (temp - t0) / max(1e-6, t1 - t0) * (f1 - f0)
        history.insert(0, instant)
        del history[20:]
        n = len(history)
        weights = list(range(n, 0, -1))
        avg = sum(v * w for v, w in zip(history, weights)) / sum(weights)
        hw = float(profile.get("smooth_history_weight", 2))
        iw = float(profile.get("smooth_instant_weight", 1))
        blended = (avg * hw + instant * iw) / max(1e-6, hw + iw)
        return int(round(max(1, min(100, blended))))
    return None


class FanController:
    """Per-miner auto fan kick loop (daemon thread)."""

    def __init__(
        self,
        get_clients: Callable[[], dict[str, Any]],
        get_registry: Callable[[], dict[str, Any]],
        save_registry: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.get_clients = get_clients
        self.get_registry = get_registry
        self.save_registry = save_registry
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        # mid -> runtime state
        self.state: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="fan-controller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def status_blob(self) -> dict[str, Any]:
        with self._lock:
            return {k: dict(v) for k, v in self.state.items()}

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick_all()
            except Exception:
                traceback.print_exc()
            # short sleep; each miner has its own poll cadence via last_poll
            self._stop.wait(1.0)

    def _tick_all(self) -> None:
        reg = self.get_registry()
        profiles = merge_profiles(reg.get("profiles"))
        defaults = reg.get("fan_defaults") or {}
        default_profile = defaults.get("profile") or "steps-default"
        clients = self.get_clients()
        now = time.time()

        for mid, client in clients.items():
            # find miner row
            row = next(
                (m for m in (reg.get("miners") or []) if (m.get("id") or m.get("ip")) == mid),
                {},
            )
            fc = dict(row.get("fan_control") or {})
            enabled = bool(fc.get("enabled", defaults.get("enabled_default", False)))
            profile_name = fc.get("profile") or default_profile
            profile = profiles.get(profile_name) or profiles["steps-default"]
            offset = int(fc.get("fan_offset") or 0)
            poll_s = float(profile.get("poll_s") or 4.0)

            with self._lock:
                st = self.state.setdefault(
                    mid,
                    {
                        "enabled": enabled,
                        "profile": profile_name,
                        "last_status": "init",
                        "last_kick_ts": 0.0,
                        "last_applied_fan": None,
                        "last_temp": None,
                        "last_poll": 0.0,
                        "kick_count": 0,
                        "history": [],
                        "error": "",
                    },
                )
                st["enabled"] = enabled
                st["profile"] = profile_name

            if not enabled:
                with self._lock:
                    st["last_status"] = "OFF"
                continue
            if now - float(st.get("last_poll") or 0) < poll_s:
                continue

            try:
                self._tick_one(mid, client, profile, offset, st)
            except Exception as e:
                with self._lock:
                    st["error"] = f"{type(e).__name__}: {e}"
                    st["last_status"] = f"ERROR {e}"
                    st["last_poll"] = now

    def _tick_one(self, mid: str, client: Any, profile: dict[str, Any], offset: int, st: dict) -> None:
        now = time.time()
        snap = client.snapshot()
        temp = snap.get("temp_max")
        st["last_poll"] = now
        st["last_temp"] = temp
        st["error"] = snap.get("jwt_error") or snap.get("error") or ""

        if temp is None:
            st["last_status"] = "NO_TEMP"
            return

        abort_c = float(profile.get("abort_c", 90))
        desired = target_fan(profile, float(temp), st.setdefault("history", []))
        if desired is not None:
            desired = max(1, min(100, int(desired) + offset))

        mode = (profile.get("mode") or "steps").lower()
        cooldown = float(
            profile.get("smooth_apply_interval_s")
            if mode == "smooth"
            else profile.get("cooldown_s", 120)
        )
        in_cooldown = st.get("last_kick_ts", 0) > 0 and (now - st["last_kick_ts"]) < cooldown

        if float(temp) >= abort_c:
            fan = max(desired or 0, int(profile.get("kick_fan", 90)), 80)
            client.set_fan_bias(fan)
            # also force tempcontrol on for safety abort path if profile wants
            if profile.get("force_tempcontrol_on", True):
                try:
                    client.set_tempcontrol(True)
                except Exception:
                    pass
            st["last_kick_ts"] = now
            st["last_applied_fan"] = fan
            st["kick_count"] = int(st.get("kick_count") or 0) + 1
            st["last_status"] = f"ABORT temp={temp} fan={fan}"
            return

        if desired is None:
            st["last_status"] = f"IDLE_COOL temp={temp}"
            return
        if in_cooldown:
            left = int(cooldown - (now - st["last_kick_ts"]))
            st["last_status"] = f"COOLDOWN {left}s fan={st.get('last_applied_fan')} temp={temp}"
            return

        # With tempcontrol ON must re-pulse even if same fan
        same = st.get("last_applied_fan") == desired
        force_tc = bool(profile.get("force_tempcontrol_on", True))
        if same and mode == "smooth":
            st["last_status"] = f"SMOOTH hold={desired} temp={temp}"
            st["last_kick_ts"] = now
            return
        if same and not force_tc:
            st["last_status"] = f"HOLD fan={desired} temp={temp}"
            return

        # apply
        if force_tc:
            try:
                client.set_tempcontrol(True)
            except Exception:
                pass
        client.set_fan_bias(int(desired))
        st["last_kick_ts"] = now
        st["last_applied_fan"] = desired
        st["kick_count"] = int(st.get("kick_count") or 0) + 1
        why = "REPULSE" if same else mode.upper()
        st["last_status"] = f"{why} fan={desired} temp={temp}"
