# SC Lite Python helpers

Auto-login JWT tools for firmware **2.2.0**.

Full walkthrough: [`../CONNECT_AND_FANS.md`](../CONNECT_AND_FANS.md)

## Setup

```bash
cd sc-lite/python
pip install -r requirements.txt
export SCLITE_IP=192.168.x.x
export SCLITE_PASSWORD='your-miner-password'
```

PowerShell:

```powershell
$env:SCLITE_IP='192.168.x.x'
$env:SCLITE_PASSWORD='your-miner-password'
pip install -r requirements.txt
```

## Run / test

```bash
# 1) sanity (read-only)
python sclite_snapshot.py

# 2) manual fan kick (keep MHz/V/PV)
python sclite_set_fan.py 70
python sclite_snapshot.py

# 3) restore stock auto
python sclite_restore_auto.py

# 4) temp manager TUI — re-kick when hot
cp sclite_temp_manager.example.json sclite_temp_manager.json
python sclite_temp_manager.py --config sclite_temp_manager.json
```

### Temp manager keys

| Key | Action |
|-----|--------|
| `[` / `]` | `on_temp` ±0.5 °C |
| `{` / `}` | `kick_fan` ±5 |
| `p` | pause / resume |
| `k` | force kick |
| `r` | restore stock auto |
| `s` | save config |
| `q` | quit |

Quick tests: press `k`; or lower `on_temp` with `[` under live board temp. Headless: `--no-ui --once`.

### Safety

- Keep `tempcontrol` on unless you use the abort-safe test script.
- Default abort in the manager example is **90 °C**.
- `sclite_tempcontrol_test.py` forces `tempcontrol=true` on abort/timeout/Ctrl+C — still risky; don’t leave unattended.
