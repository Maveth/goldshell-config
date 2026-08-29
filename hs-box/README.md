# Goldshell HS Box

**Different hardware from SC Lite and SC Pro / SC5 Pro.**

SC Lite tools live in [`../sc-lite/`](../sc-lite/). Use **[`python/`](python/)** in *this* directory for HS Box ΓÇö same HTTP/JWT flow, different powerplan string grammar.

## Status

| Item | State |
|------|--------|
| Fan field adjust via `PUT /mcb/setting` | **Confirmed** (live HS Box ΓÇö **Hersh-23**) |
| Login / snapshot / fan-kick helpers | **Confirmed** ΓÇö see [`python/`](python/) |
| Powerplan string dialect (float V / optional PV) | **Confirmed** ΓÇö e.g. `750 MHz 0.41 V 50 RPM 50 RPM` |
| Clock / voltage changes | **Not recommended** ΓÇö leave MHz/V alone unless you accept ASIC risk |
| Soft-restart / put-fail recovery | Same idea as SC Lite (`GET /mcb/restart`); not yet wired into this treeΓÇÖs temp manager copy |

## Credit

- **Hersh-23** ΓÇö verified live HS Box: JWT login, snapshot, fan-only kick; authored [`python/`](python/) as a sibling of `sc-lite/python` with HS Box `parse_plan` / `build_plan` (decimal V, optional PV). Upstream fork: https://github.com/Hersh-23/goldshell-config
- **BitcoinMechanic** ΓÇö original SC Lite reclock / control-plane discovery
- **MaVeTh** ΓÇö SC Lite fan/temp docs and Python tooling that Hersh adapted

## Confirmed powerplan dialect

| | SC Lite (`sc-lite/`) | HS Box (`hs-box/python`) |
|--|----------------------|---------------------------|
| Example | `625 MHz 9100 V 40 RPM 40 RPM PV 9400` | `750 MHz 0.41 V 50 RPM 50 RPM` |
| V field | Integer-style (e.g. `9100`) | Float volts (e.g. `0.41`) |
| `PV ΓÇª` | Present | Often **omitted** |

Fan fields are still shared bias/kick (not per-fan RPM). Only change the two `RPM` numbers; round-trip MHz/V/PV exactly as the unit reported.

## Quick start

```powershell
cd hs-box\python
pip install -r requirements.txt
$env:SCLITE_IP='192.168.x.x'          # env name shared with SC Lite helpers
$env:SCLITE_PASSWORD='your-password'
python sclite_snapshot.py
python sclite_set_fan.py 70
```

Full run notes: [`python/README.md`](python/README.md).

## Still useful captures (optional)

Identity / ports / dbg dumps help compare fw revisions across units:

```bash
curl -s http://<IP>/mcb/status
# JWT then:
curl -s -H "Authorization: <JWT>" http://<IP>/mcb/setting
curl -s -H "Authorization: <JWT>" "http://<IP>/mcb/cgminer?cgminercmd=devs"
```

## Out of scope

- Overclock / undervolt / PV experiments  
- UART / SSH unlock (not required for fan HTTP control)  
- Assuming SC Lite temp-manager timings match HS Box exactly  
