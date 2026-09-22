#!/usr/bin/env python3
"""Soft-restart watchdog stub for fleet miners (no smart-plug power cycle yet).

Rules adapted from ``gbox/watchdog.py`` in crProductGuy/goldshell-box-tools-productguy
(MIT License) — see ``ATTRIBUTION.md``. This port keeps:

* unreachable window
* accepted-share stall window
* optional board-absent signature (model.absent_signature)
* min gap between restarts + daily restart cap
* dry_run default (log would-restart only)

Power-cycle / Kasa / holds are intentionally omitted for now.
"""
from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from typing import Any, Callable


def is_absent_sample(snap: dict[str, Any], profile: dict[str, Any] | None) -> bool:
    """Controller answers but hashboard looks gone (ProductGuy SC-BOX signature).

    Only meaningful when ``profile['absent_signature']`` is True.
    """
    if not profile or not profile.get("absent_signature"):
        return False
    if not snap.get("ok"):
        return False
    # clock 0 + no useful temps
    clock = None
    plan = snap.get("plan") or {}
    if isinstance(plan, dict) and plan.get("mhz") is not None:
        try:
            clock = float(plan.get("mhz"))
        except Exception:
            clock = None
    # boards / temps
    temps = snap.get("temps") or []
    temp_max = snap.get("temp_max")
    mhs = snap.get("mhs_av")
    try:
        mhs_f = float(mhs) if mhs is not None else 0.0
    except Exception:
        mhs_f = 0.0
    no_temp = (temp_max is None and not temps) or (
        temp_max is not None and float(temp_max) <= 0
    )
    if clock is not None and clock <= 0 and no_temp and mhs_f <= 0:
        return True
    # also treat zero hash + zero temp as absent-ish when signature enabled
    if mhs_f <= 0 and no_temp and (clock is None or clock <= 0):
        return True
    return False


class SoftWatchdog:
    """Per-miner soft-restart judge (pure logic; injectable clock)."""

    def __init__(
        self,
        *,
        interval_s: float = 30.0,
        stall_minutes: float = 5.0,
        unreachable_minutes: float = 2.0,
        absent_minutes: float = 2.0,
        min_gap_minutes: float = 10.0,
        max_restarts_per_day: int = 6,
        dry_run: bool = True,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.interval = float(interval_s)
        self.stall_rows = max(2, round(stall_minutes * 60 / self.interval))
        self.err_rows = max(1, round(unreachable_minutes * 60 / self.interval))
        self.absent_rows = (
            max(2, round(absent_minutes * 60 / self.interval)) if absent_minutes else 0
        )
        self.min_gap = min_gap_minutes * 60
        self.max_restarts = int(max_restarts_per_day)
        self.dry_run = bool(dry_run)
        self._clock = clock
        self._rows: deque[tuple[float, bool, Any, bool]] = deque(
            maxlen=max(self.stall_rows * 2, 8)
        )
        self._restart_times: deque[float] = deque()
        self.last_restart: float | None = None
        self.last_reason: str | None = None
        self.last_action: str | None = None
        self._capped_logged = False

    def observe(
        self,
        ok: bool,
        accepted: Any,
        *,
        absent: bool = False,
        t: float | None = None,
    ) -> None:
        t = self._clock() if t is None else t
        self._rows.append((t, bool(ok), accepted, bool(ok and absent)))

    def restarts_today(self) -> int:
        cutoff = self._clock() - 86400
        while self._restart_times and self._restart_times[0] < cutoff:
            self._restart_times.popleft()
        return len(self._restart_times)

    def diagnose(self) -> str | None:
        now = self._clock()
        floor = (self.last_restart + self.min_gap) if self.last_restart else float("-inf")
        rows = list(self._rows)
        if not rows or rows[-1][0] <= floor or now - rows[-1][0] > 2 * self.interval:
            return None
        # unreachable
        err = [r for r in rows if r[0] >= now - self.err_rows * self.interval]
        if len(err) >= self.err_rows and all(not r[1] for r in err[-self.err_rows :]):
            return "unreachable"
        # absent (controller up, board gone)
        if self.absent_rows:
            abs_rows = [r for r in rows if r[0] >= now - self.absent_rows * self.interval]
            if len(abs_rows) >= self.absent_rows and all(
                r[1] and r[3] for r in abs_rows[-self.absent_rows :]
            ):
                return "absent"
        # stalled accepted counter
        good = [r for r in rows if r[0] >= now - self.stall_rows * self.interval and r[1]]
        if len(good) >= self.stall_rows:
            window = good[-self.stall_rows :]
            accs = [r[2] for r in window]
            if all(a is not None for a in accs) and len(set(accs)) == 1:
                return "stalled"
        return None

    def check(self) -> dict[str, Any]:
        """Return action decision; caller performs soft_restart when action=='restart'."""
        reason = self.diagnose()
        if not reason:
            return {"action": None, "reason": None, "dry_run": self.dry_run}
        if self.restarts_today() >= self.max_restarts:
            if not self._capped_logged:
                self._capped_logged = True
                self.last_action = "capped"
            return {
                "action": "capped",
                "reason": reason,
                "dry_run": self.dry_run,
                "restarts_today": self.restarts_today(),
            }
        self._capped_logged = False
        self.last_reason = reason
        if self.dry_run:
            self.last_action = "would_restart"
            # still advance gap so we don't spam every poll
            self.last_restart = self._clock()
            return {"action": "would_restart", "reason": reason, "dry_run": True}
        self.last_restart = self._clock()
        self._restart_times.append(self.last_restart)
        self.last_action = "restart"
        return {"action": "restart", "reason": reason, "dry_run": False}

    def status(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "last_reason": self.last_reason,
            "last_action": self.last_action,
            "last_restart": self.last_restart,
            "restarts_today": self.restarts_today(),
            "samples": len(self._rows),
            "interval_s": self.interval,
        }


class SoftWatchdogController:
    """Background poller: snapshot → SoftWatchdog → optional soft_restart."""

    def __init__(
        self,
        get_clients: Callable[[], dict[str, Any]],
        get_registry_doc: Callable[[], dict[str, Any]],
        get_profile: Callable[[str | None], dict[str, Any]],
        snapshot_fn: Callable[[Any], dict[str, Any]],
        poll_s: float = 30.0,
    ) -> None:
        self._get_clients = get_clients
        self._get_registry_doc = get_registry_doc
        self._get_profile = get_profile
        self._snapshot_fn = snapshot_fn
        self.poll_s = float(poll_s)
        self._dogs: dict[str, SoftWatchdog] = {}
        self._runtime: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="soft-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def runtime(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._runtime.items()}

    def _cfg_for(self, mid: str, row: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
        wd = dict(defaults or {})
        per = row.get("watchdog") if isinstance(row.get("watchdog"), dict) else {}
        wd.update(per or {})
        return wd

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                traceback.print_exc()
            self._stop.wait(self.poll_s)

    def _tick(self) -> None:
        doc = self._get_registry_doc() or {}
        rows = {
            (r.get("id") or r.get("ip")): r
            for r in (doc.get("miners") or [])
            if not r.get("demo")
        }
        clients = self._get_clients()
        doc_defaults = dict(doc.get("watchdog_defaults") or {})
        for mid, client in list(clients.items()):
            row = rows.get(mid) or {}
            cfg = self._cfg_for(mid, row, doc_defaults)
            if not cfg.get("enabled"):
                with self._lock:
                    self._runtime[mid] = {
                        "enabled": False,
                        "last_status": "disabled",
                    }
                continue
            dry = bool(cfg.get("dry_run", True))
            interval = float(cfg.get("poll_s") or self.poll_s)
            dog = self._dogs.get(mid)
            if dog is None or dog.dry_run != dry or abs(dog.interval - interval) > 0.1:
                dog = SoftWatchdog(
                    interval_s=interval,
                    stall_minutes=float(cfg.get("stall_minutes", 5)),
                    unreachable_minutes=float(cfg.get("unreachable_minutes", 2)),
                    absent_minutes=float(cfg.get("absent_minutes", 2)),
                    min_gap_minutes=float(cfg.get("min_gap_minutes", 10)),
                    max_restarts_per_day=int(cfg.get("max_restarts_per_day", 6)),
                    dry_run=dry,
                )
                self._dogs[mid] = dog
            try:
                snap = self._snapshot_fn(client)
            except Exception as e:
                snap = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            model = None
            st = snap.get("status") if isinstance(snap.get("status"), dict) else None
            if isinstance(st, dict):
                model = st.get("model")
            # also from setting-less identity if we stash it — optional
            profile = self._get_profile(model if isinstance(model, str) else None)
            ok = bool(snap.get("ok"))
            accepted = snap.get("accepted")
            try:
                mhs = float(snap.get("mhs_av") or 0)
            except Exception:
                mhs = 0.0
            hashing = ok and mhs > 0
            absent = is_absent_sample(snap, profile) if ok else False
            dog.observe(ok, accepted, absent=absent)
            decision = dog.check()
            action = decision.get("action")
            note = None
            if action == "restart":
                try:
                    note = client.soft_restart()
                except Exception as e:
                    note = f"restart failed: {type(e).__name__}: {e}"
                    decision = {**decision, "action": "restart_failed", "error": note}
            elif action == "would_restart":
                note = f"dry_run would soft-restart ({decision.get('reason')})"
            with self._lock:
                self._runtime[mid] = {
                    "enabled": True,
                    "dry_run": dry,
                    "ok": ok,
                    "hashing": hashing,
                    "absent": absent,
                    "accepted": accepted,
                    "mhs_av": snap.get("mhs_av"),
                    "decision": decision,
                    "watchdog": dog.status(),
                    "note": note,
                    "profile_id": profile.get("profile_id"),
                    "model": model,
                    "ts": time.time(),
                }
