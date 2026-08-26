# MaVeTh SC Lite Python helpers

Auto-login JWT tools for firmware 2.2.0.

Full walkthrough (ports, auth, fan kicks, safety):  
[`../CONNECT_AND_FANS.md`](../CONNECT_AND_FANS.md)

## Setup

```bash
pip install pycryptodome
export SCLITE_IP=192.168.x.x
export SCLITE_PASSWORD='your-miner-password'   # often factory 123456789
```

On Windows PowerShell:

```powershell
$env:SCLITE_IP='192.168.x.x'
$env:SCLITE_PASSWORD='your-miner-password'
pip install pycryptodome
```

## Commands

```bash
# Live settings + board temps/fans/hashrate
python sclite_snapshot.py

# Set only fan fields (keep MHz/V/PV); enables manual=true
python sclite_set_fan.py 70

# Restore stock auto (manual=false, level-0 plan)
python sclite_restore_auto.py

# Watch fans/temps for a few minutes (no writes)
python sclite_watch.py

# Temp manager: kick fans when hot (interactive TUI + config)
# Copy example config, edit on_temp / kick_fan, then run:
cp sclite_temp_manager.example.json sclite_temp_manager.json
python sclite_temp_manager.py --config sclite_temp_manager.json
# keys: [ ] on_temp  { } kick_fan  p pause  k force-kick  r restore  q quit

# DANGEROUS: tempcontrol OFF + fan kick with auto-abort restore
# Default: abort >= 88C, max 90s, poll 3s
python sclite_tempcontrol_test.py --fan 70 --abort-c 88 --max-seconds 90
```

`sclite_tempcontrol_test.py` always forces `tempcontrol=true` on abort, timeout, Ctrl+C, or error.

### Temp manager design (v1)

- Watches `board: "max"` (hottest) or a fixed board id
- When temp ≥ `on_temp` (default **80.5**), PUT fan fields to `kick_fan` (default **70**)
- Keeps MHz / V / PV unchanged; leaves/forces `tempcontrol=true`
- `cooldown_s` (default **45**) prevents kick spam while fans are still up
- Interactive UI shows live temps/fans and lets you nudge thresholds
- `abort_c` (default **90**) emergency high kick + exit
