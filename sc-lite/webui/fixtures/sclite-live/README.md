# fixtures/sclite-live

Read-only capture from a live **Goldshell SC Lite** (LAN unit), taken
2026-09-22 for ProductGuy / gbox per `docs/capture-request.md`.

## Unit facts (also in `CAPTURE_FACTS.json`)

| Field | Value |
|---|---|
| Model string (`/mcb/status`) | `Goldshell-SCLITE` |
| Firmware | `2.2.0` |
| Hardware | `30.40.SA` |
| MCB | `MCB_V4_3` |
| Boards (`:4028` `devs`) | **4** PGA rows |
| Fans | `fan0`…`fan3` (4 fields) |
| Plan | `625 MHz 9100 V 75 RPM 75 RPM PV 9400` (`mv_pv`) |
| `temp_targets` in `/mcb/setting` | **absent** (no adjustable fan target) |
| `tempcontrol` at capture | `true` |
| Measured voltage on 4028 | **9330** mV (plan says 9100) |
| `/dbg/minerinfo` | **HTTP 200** with `[PGA…]` blocks (JWT; not locked) |
| Auth header that worked | `Authorization: <token>` (**no** `Bearer`) |

## Files

Same set as gbox `docs/capture-request.md`, plus `dbg_fanctrllog.txt`
(Claude specifically asked for it to settle `tempcontrol`).

- `name` in `mcb_setting.json` redacted to `00:11:22:33:44:55`
- No pools / WiFi / syslogs / password / token files

## `tempcontrol` note (capture + follow-up tests)

With `tempcontrol=true`, `dbg_fanctrllog.txt` shows an active duty loop:

```text
Fans Change (fan0: 70 ==> 69) … reason(t:73.1 … target_temp:85)
```

**Follow-up (same unit, 2026-09-22):** `tempcontrol=false` for 60s and for
**10 minutes** (GET-confirmed; abort if board >75°C; max seen 70°C; restored
afterward). **`Fans Change` kept running** with `target_temp:85` the whole
time — the walk-down does **not** stop when the flag is off.

So: the flag-on log alone cannot prove the flag drives the loop (ProductGuy/
Claude were right). On SC Lite, OFF ≠ “manual fans only.” Overheat-path
behavior under heat is still unproven.
