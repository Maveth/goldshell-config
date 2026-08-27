# Goldshell HS Box

**Different hardware from SC Lite and SC Pro / SC5 Pro.**

**Status: UNCONFIRMED community report — no dedicated helpers here yet.**

SC Lite tools live in [`../sc-lite/`](../sc-lite/). Do not assume those scripts or powerplan tokens apply unchanged.

## Reported powerplan dialect (unconfirmed)

| | SC Lite (confirmed in `sc-lite/`) | HS Box (reported) |
|--|----------------------------------|-------------------|
| Example | `625 MHz 9100 V 40 RPM 40 RPM PV 9400` | `850 MHz 0.440 V 50 RPM 50 RPM` |
| V field | Integer-style (e.g. `9100`) | Float volts (e.g. `0.440`) |
| `PV …` | Present | Often **omitted** |
| Fans | `N RPM N RPM` bias fields | Same idea, unconfirmed timings |

Related on-box history encoding seen on an HS Box dbg dump:

```text
intchains_qomo:vfff=0.440000:850:50:50
intchains_qomo:algo=blake2b(SC)
```

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

## Confirm checklist

1. `GET /mcb/status` → model string  
2. `GET /mcb/setting` → exact `manualPowerplan` + `powerplans[]`  
3. Record ports / dbg / `tempcontrol` behavior on that unit  
4. Dry-run parse → build → compare equal  
5. Then add `hs-box/python/` (or shared helpers with a `--box` flag)  

## Auth / ports

Assume same Yotta-style JWT + `:80` / `:4028` until proven otherwise. Re-verify per model.
