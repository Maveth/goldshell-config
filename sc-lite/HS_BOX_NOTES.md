# Goldshell HS Box notes (different hardware)

**Status: UNCONFIRMED community report — not wired into the default Python helpers yet.**

**HS Box ≠ SC Lite ≠ SC Pro.** These are different Goldshell products (different boards/firmware lineages), even if they share a similar Yotta-style web UI and Blake2b-class hashing. Do not assume SC Lite timings, powerplan tokens, ports, or dbg layout apply unchanged.

| Model | Role in this repo |
|-------|-------------------|
| **SC Lite** | Verified target of `sc-lite/` helpers (fw 2.2.0 lab unit) |
| **HS Box** | Separate machine — community tip only so far |
| **SC Pro / SC5 Pro** | Separate again — upstream notes it as harder/more sensitive |

Someone reported that **after adapting powerplan parse/build**, fan-style tools worked on an **HS Box**. We have **not** validated a live HS Box `manualPowerplan` ourselves. This file stages that tip until confirmed on real hardware.
## Reported powerplan dialect

| | SC Lite (confirmed) | HS Box (reported, unconfirmed) |
|--|---------------------|--------------------------------|
| Example | `625 MHz 9100 V 40 RPM 40 RPM PV 9400` | `850 MHz 0.440 V 50 RPM 50 RPM` |
| V field | Integer-style (e.g. `9100`) | Float volts (e.g. `0.440`) |
| `PV …` | Present | Often **omitted** |
| Fans | Same `N RPM N RPM` bias fields | Same idea |

Related on-box history encoding we have seen on HS Box dbg:

```text
intchains_qomo:vfff=0.440000:850:50:50
intchains_qomo:algo=blake2b(SC)
```

That suggests MHz / fan fields still exist; voltage scale differs from SC Lite’s `9100`-style token.

## Suggested parse/build (reference only)

Do **not** replace SC Lite helpers until a live HS Box `GET /mcb/setting` → `manualPowerplan` is captured and round-tripped.

```python
def parse_plan(plan: str) -> tuple[str, str, int, int, str | None]:
    m = re.match(
        r"([\d.]+)\s*MHz\s+([\d.]+)\s*V\s+(\d+)\s*RPM\s+(\d+)\s*RPM(?:\s+PV\s+([\d.]+))?",
        plan or "",
    )
    if not m:
        raise RuntimeError(f"cannot parse powerplan: {plan!r}")
    mhz, mv, fan_a, fan_b, pv = m.groups()
    return mhz, mv, int(fan_a), int(fan_b), pv


def build_plan(mhz: str, mv: str, fan_a: int, fan_b: int, pv: str | None = None) -> str:
    plan = f"{mhz} MHz {mv} V {fan_a} RPM {fan_b} RPM"
    if pv is not None:
        plan += f" PV {pv}"
    return plan
```

Design note when confirming: keep MHz/V as **strings** so `0.440` round-trips; only change fan ints in the manager.

## Confirm checklist

When someone has an HS Box on the LAN:

1. `GET /mcb/status` → model string  
2. `GET /mcb/setting` → exact `manualPowerplan` + `powerplans[]`  
3. Paste into an issue / this file  
4. Dry-run parse → build → compare equal  
5. Only then optionally add `model=` detection or a `--box hs|sc-lite` flag to the helpers  

## Auth / ports

Assume same Yotta-style JWT + `:80` / `:4028` until proven otherwise. Re-verify SSH closed, dbg paths, and `tempcontrol` behavior per model — do not assume SC Lite fan pulse timings match HS Box.
