# HS Box Python helpers

Auto-login JWT tools adapted for **Goldshell HS Box**.

Same stock HTTP API as SC Lite (`/user/login`, `/mcb/setting`, `/mcb/cgminer`, `/dbg/*`), with one important difference: the `manualPowerplan` string uses **decimal volts** and often **omits `PV`**.

Example HS Box plan:

```text
750 MHz 0.41 V 50 RPM 50 RPM
```

vs SC Lite:

```text
625 MHz 9100 V 40 RPM 40 RPM PV 9400
```

`parse_plan` / `build_plan` in this tree round-trip MHz/V as strings and only mutate fan ints.

**Model notes:** [`../README.md`](../README.md)  
**SC Lite walkthrough (shared JWT / safety ideas):** [`../../sc-lite/CONNECT_AND_FANS.md`](../../sc-lite/CONNECT_AND_FANS.md)

## Credit

- **Hersh-23** — live HS Box verification (login, snapshot, fan-kick) and this `hs-box/python` tree  
- Adapted from MaVeTh / Mechanic **SC Lite** helpers in `sc-lite/python/` (left unmodified)

## How to run and test

### 1. One-time setup

```bash
cd hs-box/python
pip install -r requirements.txt   # or: pip install pycryptodome

export SCLITE_IP='192.168.x.x'
export SCLITE_PASSWORD='your-miner-password'   # often factory 123456789 — change it
```

Windows PowerShell:

```powershell
cd hs-box\python
pip install -r requirements.txt

$env:SCLITE_IP='192.168.x.x'
$env:SCLITE_PASSWORD='your-miner-password'
# password can also go in sclite_temp_manager.json -> miner.password
```

(Env var names stay `SCLITE_*` for drop-in familiarity with the SC Lite scripts.)

### 2. Sanity check (read-only)

```powershell
python sclite_snapshot.py
```

You should see a float-V plan (no `PV` is normal), per-board temps, fans, and hashrate.  
If login fails, fix `SCLITE_IP` / password before anything else.

### 3. Manual fan kick test

```powershell
python sclite_set_fan.py 70
python sclite_snapshot.py
```

Fans should jump within a few seconds. **Only the RPM fields change** — clock/voltage stay as reported.  
Optional restore to stock auto:

```powershell
python sclite_restore_auto.py
```

### 4. Run the temp manager

```powershell
copy sclite_temp_manager.example.json sclite_temp_manager.json
python sclite_temp_manager.py --config sclite_temp_manager.json
```

#### Modes (`control.mode`)

| Mode | Role | tempcontrol |
|------|------|-------------|
| **`single`** | **Basic** — temp ≥ `on_temp` → kick to `kick_fan` | Keep **ON** (safer) |
| **`steps`** | Ladder of thresholds; re-pulses every `cooldown_s` while in-zone | Keep **ON** |
| **`smooth`** | Continuous ramp (**experimental** on SC Lite; treat as untested on HS Box) | Prefer **OFF** |

```powershell
python sclite_temp_manager.py --config sclite_temp_manager.steps.example.json
python sclite_temp_manager.py --config sclite_temp_manager.smooth.example.json
```

**Interactive keys:** `m` cycle mode · `[` `]` on_temp · `{` `}` kick_fan · `p` pause · `k` force · `r` restore · `s` save · `q` quit

### Safety while testing

- Prefer fan-only edits (leave MHz / V alone)
- Keep `tempcontrol` on unless watching closely
- Abort **90°C** by default
- Don’t leave `tempcontrol` off tests unattended

---

## Command cheat sheet

```bash
python sclite_snapshot.py
python sclite_set_fan.py 70
python sclite_restore_auto.py
python sclite_watch.py
python sclite_temp_manager.py --config sclite_temp_manager.json
python sclite_temp_manager.py --config sclite_temp_manager.steps.example.json

# DANGEROUS: tempcontrol OFF + fan kick with auto-abort restore
python sclite_tempcontrol_test.py --fan 70 --abort-c 88 --max-seconds 90
```

CLI: `--mode single|steps|smooth`, `--on-temp`, `--kick-fan`, `--cooldown`, `--poll`, `--abort-c`, `--board`, `--no-ui`, `--once`.
