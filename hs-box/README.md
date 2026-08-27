# Goldshell HS Box

**Different hardware from SC Lite and SC Pro / SC5 Pro.**

SC Lite tools live in [`../sc-lite/`](../sc-lite/). Do not assume those scripts or powerplan tokens apply unchanged.

## Status

| Item | State |
|------|--------|
| Fan field adjust via `PUT /mcb/setting` | **Confirmed** (community — Hersh): fans adjust fine with the same HTTP approach |
| Clock / voltage changes | **Not requested** — ASICs are easy to hurt; leave MHz/V alone unless you accept the risk |
| Default `sc-lite/python` helpers | Still **SC Lite** plan grammar until we finish the capture list below |
| Powerplan string dialect (float V / optional PV) | **Likely** from reports + dbg history; still want a pasted live `manualPowerplan` |

## Confirmed so far

- Fan bias/kick through the stock web API works on HS Box (same idea as SC Lite: only change the `RPM` fields; keep clock/voltage untouched).
- Operators coming from GPUs are right to be cautious: **do not** treat ASIC overclock / undervolt like a GPU tweak, especially with Blake2b hardware prices up.

## Please capture (non-invasive — same class of probes as SC Lite)

Safe LAN reads / one careful fan-only PUT. **No MHz/V experiments.**

### 1. Identity
```bash
curl -s http://<IP>/mcb/status
```
Paste full JSON (`model`, `firmware`, `hardware`, `mcbversion`).

### 2. Settings / powerplan (most important)
After JWT login (browser `#/debug` token, or adapted login script):

```bash
curl -s -H "Authorization: <JWT>" http://<IP>/mcb/setting
```

Paste:
- exact `manualPowerplan`
- full `powerplans[]` (stock / idle levels)
- `manual`, `tempcontrol`, `select`

### 3. Live boards
```bash
curl -s -H "Authorization: <JWT>" "http://<IP>/mcb/cgminer?cgminercmd=devs"
```
Or `:4028` if open: `{"command":"devs"}` / `summary` / `config`.

Note temps, fan RPM strings, hashrate.

### 4. Ports (read-only)
From a PC on the same LAN: is **22** open? **80**? **4028**? **443**?  
(`Test-NetConnection` / `nc` / `nmap -p 22,80,443,4028 <IP>`)

### 5. Optional dbg (JWT; read-only)
If `/dbg/*` works after unlock:
- `/dbg/minerinfo` — voltage/clock/fans as reported
- `/dbg/fanctrllog` — any `target_temp` line
- `/dbg/minerhistory` — one `ALGOCHG` / plan line
- `/dbg/psinfo` — confirm `intminer` / no sshd

### 6. Fan-only smoke (optional, still non-invasive)
1. Snapshot setting + fans/temps  
2. Raise **only** the two RPM fields (leave MHz/V/PV exactly as reported)  
3. Wait ~10s, snapshot again  
4. Restore prior plan or stock auto  

Do **not** change clock or voltage for this checklist.

## Reported powerplan dialect (pending paste confirmation)

| | SC Lite (confirmed in `sc-lite/`) | HS Box (reported) |
|--|----------------------------------|-------------------|
| Example | `625 MHz 9100 V 40 RPM 40 RPM PV 9400` | `850 MHz 0.440 V 50 RPM 50 RPM` |
| V field | Integer-style (e.g. `9100`) | Float volts (e.g. `0.440`) |
| `PV …` | Present | Often **omitted** |

Dbg history seen on an HS Box:

```text
intchains_qomo:vfff=0.440000:850:50:50
intchains_qomo:algo=blake2b(SC)
```

## Suggested parse/build (reference only — not default code)

Keep MHz/V as strings so floats round-trip; only mutate fan ints:

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

Wire into helpers only after steps 1–2 above are pasted and round-tripped.

## Out of scope (for now)

- Overclock / undervolt / PV experiments  
- UART / SSH unlock (optional for others; not required for fan HTTP control)  
- Assuming SC Lite temp-manager timings match HS Box  
