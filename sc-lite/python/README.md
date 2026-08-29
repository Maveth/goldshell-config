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
python sclite_temp_manager.py --config sclite_temp_manager.json
```

#### Modes (`control.mode`) — pick one

| Mode | Role | tempcontrol |
|------|------|-------------|
| **`single`** | **Basic** — temp ≥ `on_temp` → kick to `kick_fan` | Keep **ON** (safer) |
| **`steps`** | **Advanced but safer** — ladder e.g. ≥60→55, ≥65→60, ≥70→65. Re-pulses every `cooldown_s` while still in that zone (needed because tc ON fades the kick). Drops to a lower step only when temp falls below that step’s threshold. | Keep **ON** |
| **`smooth`** | Continuous ramp (weighted history). **Fiddle** `min_temp/max_temp/min_fan/max_fan`. **Not fully tested yet** (experimental). | Prefer **OFF** so stock `fanctrl` doesn’t fight you; use abort + `restore_auto_on_exit` |
```powershell
python sclite_temp_manager.py --config sclite_temp_manager.steps.example.json
python sclite_temp_manager.py --config sclite_temp_manager.smooth.example.json
python sclite_temp_manager.py --config sclite_temp_manager.json --mode smooth
```

**Interactive keys:** `m` cycle mode · `[` `]` on_temp · `{` `}` kick_fan · `p` pause · `k` force · `r` restore · `s` save · `q` quit

### Safety while testing

- Keep `tempcontrol` on (default)
- Abort **90°C** by default
- Don’t leave `tempcontrol` off tests unattended

### Logging (errors used to vanish)

The interactive UI clears the screen each poll, so crashes looked like a silent stop.
By default the temp manager now appends to **`sclite_temp_manager.log`** (next to your
config). Warnings/errors also go to **stderr**. The UI shows `LAST ERROR:` when set.

```powershell
# default log beside config:
python sclite_temp_manager.py --config sclite_temp_manager.json
Get-Content .\sclite_temp_manager.log -Tail 40

# custom path / disable:
python sclite_temp_manager.py --config sclite_temp_manager.json --log-file O:\logs\fans.log
python sclite_temp_manager.py --config sclite_temp_manager.json --log-file off
```

Uncaught step errors are logged with a full traceback; the loop **keeps running**
(unless `--max-step-errors` is hit, default 50 consecutive).

### Optional: auto soft-restart if PUT wedges

After many `PUT /mcb/setting` applies, the SC Lite API can stop accepting PUTs
(while `GET` still works). Soft restart (`GET /mcb/restart`) usually clears it.

**Default is OFF.** To enable in config:

```json
"safety": {
  "put_fail_restart_enabled": true,
  "put_fail_restart_after_min": 5,
  "put_fail_restart_cooldown_min": 15,
  "put_fail_restart_wait_s": 120
}
```

Or CLI:

```powershell
python sclite_temp_manager.py --config sclite_temp_manager.json --put-fail-restart --put-fail-restart-after-min 5
```

Never uses `/mcb/facrst`. Accepts unattended reboots when enabled.

---

## Command cheat sheet

```bash
python sclite_snapshot.py
python sclite_set_fan.py 70
python sclite_restore_auto.py
python sclite_watch.py
python sclite_temp_manager.py --config sclite_temp_manager.json
python sclite_temp_manager.py --config sclite_temp_manager.steps.example.json
python sclite_temp_manager.py --config sclite_temp_manager.smooth.example.json

# DANGEROUS: tempcontrol OFF + fan kick with auto-abort restore
python sclite_tempcontrol_test.py --fan 70 --abort-c 88 --max-seconds 90
```

CLI: `--mode single|steps|smooth`, `--on-temp`, `--kick-fan`, `--cooldown`, `--poll`, `--abort-c`, `--board`, `--put-fail-restart`, `--put-fail-restart-after-min`, `--no-ui`, `--once`.
