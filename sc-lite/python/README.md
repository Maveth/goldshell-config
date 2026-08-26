# MaVeTh SC Lite Python helpers

Auto-login JWT tools for firmware 2.2.0.

Full walkthrough (ports, auth, fan kicks, safety):  
[`../CONNECT_AND_FANS.md`](../CONNECT_AND_FANS.md)

These scripts are **not** BIP-110-specific — they only talk to the miner over LAN HTTP.  
Keep them in this repo (or a local working copy such as `O:\HSlite`); your BIP-110 / DATUM tree can stay separate.

## How to run and test

### 1. One-time setup

```bash
cd sc-lite/python
pip install -r requirements.txt   # or: pip install pycryptodome

export SCLITE_IP='192.168.x.x'
export SCLITE_PASSWORD='your-miner-password'   # often factory 123456789 — change it
```

Windows PowerShell:

```powershell
cd sc-lite\python
pip install -r requirements.txt

$env:SCLITE_IP='192.168.0.202'
$env:SCLITE_PASSWORD='your-miner-password'
# password can also go in sclite_temp_manager.json -> miner.password
```

### 2. Sanity check (read-only)

```powershell
python sclite_snapshot.py
```

You should see the powerplan, per-board temps, fans, and hashrate.  
If login fails, fix `SCLITE_IP` / password before anything else.

### 3. Manual fan kick test

```powershell
python sclite_set_fan.py 70
python sclite_snapshot.py
```

Fans should jump within a few seconds (e.g. ~1000 → ~1700 RPM).  
Optional restore to stock auto:

```powershell
python sclite_restore_auto.py
```

### 4. Run the temp manager (main tool)

```powershell
copy sclite_temp_manager.example.json sclite_temp_manager.json
# edit on_temp / kick_fan / cooldown_s if you want
python sclite_temp_manager.py --config sclite_temp_manager.json
```

Example defaults: kick fans to **70** when watched temp ≥ **80.5°C**, cooldown **45s**, abort ≥ **90°C**.

**Interactive keys**

| Key | Action |
|-----|--------|
| `[` / `]` | `on_temp` −0.5 / +0.5 °C |
| `{` / `}` | `kick_fan` −5 / +5 |
| `p` | pause / resume control |
| `k` | force kick now |
| `r` | restore stock auto plan |
| `s` | save current thresholds into the config file |
| `q` | quit |

### 5. Easy ways to test the logic

**A. Force a kick without waiting for heat**  
Start the manager → press **`k`** → fans should spike; status → `KICKED` then `COOLDOWN`.

**B. Threshold test**  
Press **`[`** until `on_temp` is under the current hot-board temp.  
Within one poll (~3s) it should auto-kick (unless still in cooldown).

**C. Headless one-shot**

```powershell
python sclite_temp_manager.py --config sclite_temp_manager.json --no-ui --once
```

Prints one line; kicks if watched temp ≥ `on_temp`.

**D. Edit config, then run**  
Open `sclite_temp_manager.json` and set e.g. `"on_temp": 80.5`, `"kick_fan": 70`, save, start the manager again.

### Safety while testing

- Keep `tempcontrol` on (default in config / `force_tempcontrol_on: true`)
- Abort is **90°C** by default — emergency high kick + exit if hit
- Do not leave `tempcontrol` off tests running unattended
- Press `q` to quit; `r` if you want the stock auto plan back

---

## Command cheat sheet

```bash
python sclite_snapshot.py
python sclite_set_fan.py 70
python sclite_restore_auto.py
python sclite_watch.py
python sclite_temp_manager.py --config sclite_temp_manager.json

# DANGEROUS: tempcontrol OFF + fan kick with auto-abort restore
python sclite_tempcontrol_test.py --fan 70 --abort-c 88 --max-seconds 90
```

`sclite_tempcontrol_test.py` always forces `tempcontrol=true` on abort, timeout, Ctrl+C, or error.

## Temp manager design (v1)

- Watches `board: "max"` (hottest) or a fixed board id `0..3`
- When temp ≥ `on_temp`, PUT fan fields to `kick_fan` (keep MHz / V / PV)
- Forces / leaves `tempcontrol=true`
- `cooldown_s` prevents kick spam while fans are still elevated (~1–3 min fade in auto mode)
- Interactive UI shows live temps/fans and lets you nudge thresholds
- `abort_c` emergency path

CLI overrides also work: `--on-temp`, `--kick-fan`, `--cooldown`, `--poll`, `--abort-c`, `--board`, `--no-ui`, `--once`.
