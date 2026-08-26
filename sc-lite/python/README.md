# MaVeTh SC Lite Python helpers

Auto-login JWT tools for firmware 2.2.0.

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

# DANGEROUS: tempcontrol OFF + fan kick with auto-abort restore
# Default: abort >= 88C, max 90s, poll 3s
python sclite_tempcontrol_test.py --fan 70 --abort-c 88 --max-seconds 90
```

`sclite_tempcontrol_test.py` always forces `tempcontrol=true` on abort, timeout, Ctrl+C, or error.
