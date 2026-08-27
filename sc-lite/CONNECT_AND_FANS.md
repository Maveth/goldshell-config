# Connect to an SC Lite and control fans

Verified on **Goldshell SC Lite firmware 2.2.0**.  
No SSH. No custom firmware. Stock HTTP API only.

## 1. Reach the miner

1. Put the miner on your LAN (DHCP is fine).
2. Find its IP (router DHCP list, or the miner screen if present).
3. Confirm these ports from your PC:

| Port | Expected | Use |
|------|----------|-----|
| **80** | Open | Web UI + control API (`/mcb`, `/user`, `/dbg`) |
| **4028** | Open | Optional BFGMiner-style **read** API |
| 22 / 23 / 2222 / 443 | Closed on our unit | No network shell / no HTTPS |

Browser check:

```text
http://<MINER_IP>/
http://<MINER_IP>/#/debug
```

Quick status (no login required on our fw):

```bash
curl -s http://<MINER_IP>/mcb/status
# {"hardware":"30.40.SA","model":"Goldshell-SCLITE","mcbversion":"MCB_V4_3","firmware":"2.2.0"}
```

Optional live hashrate/temps without JWT (port 4028):

```bash
echo '{"command":"summary"}' | nc <MINER_IP> 4028
echo '{"command":"devs"}'    | nc <MINER_IP> 4028
```

`:4028` is great for monitoring. **Config writes need port 80 + JWT** (below).

## 2. Authenticate (JWT)

Writes and most `/dbg/*` reads need a JWT.

### Option A — browser token (upstream bash scripts)

1. Open `http://<MINER_IP>/#/debug` and unlock with the miner password.
2. DevTools → Console:

```js
localStorage.getItem('token')
```

3. Export it:

```bash
export MINER_IP='192.168.x.x'
export TOKEN='eyJ…'
```

### Option B — auto-login (MaVeTh Python helpers)

Login request:

```http
GET /user/login?username=admin&password=<hex>&cipher=true
```

Password cipher (stock UI):

- AES-CBC
- key = `!!!!!!!!!!!!!!!!` (16 `!`)
- IV = 16 zero bytes
- ZeroPadding
- send ciphertext as **hex**

Response JSON field: `"JWT Token"`.  
Send it as header `Authorization: <token>` (raw token works).

```powershell
$env:SCLITE_IP='192.168.x.x'
$env:SCLITE_PASSWORD='your-password'   # often factory 123456789 — change it
cd sc-lite/python
pip install pycryptodome
python sclite_snapshot.py
```

## 3. Understand the fan control knobs

Fans are **not** controlled one-by-one over the stock API.

All changes go through:

```http
GET/PUT /mcb/setting
Authorization: <JWT>
Content-Type: application/json
```

Important fields:

| Field | Meaning |
|-------|---------|
| `manualPowerplan` | String: `"625 MHz 9100 V 40 RPM 40 RPM PV 9400"` |
| `manual` | Must be `true` for a custom plan to stick |
| `tempcontrol` | `true` = auto `fanctrl` toward ~**85°C** |
| `select` | Preset level (`0` stock) |

Powerplan shape:

```text
<MHz> MHz <mV> V <fanA> RPM <fanB> RPM PV <pv>
```

Internal encoding (from `/dbg/minerhistory`):

```text
intchains_qomo:vfff=<pv>:<MHz>:<fanA>:<fanB>:<mV>
```

**The `RPM` numbers are not literal fan RPM.**  
Live fans usually run ~1000–1800 RPM. Those fields are a **shared duty bias / kick** for all fans together.

You **can**:
- watch a single board’s temperature
- kick **all** fans when that board is hot

You **cannot** (stock API):
- set `fan0` independently of `fan1/2/3`
- set a permanent fixed RPM while `tempcontrol=true`

## 4. Control fans (safe path)

### Read current state

```bash
# Python helper
python sclite_snapshot.py

# or raw
curl -s -H "Authorization: $TOKEN" http://$MINER_IP/mcb/setting
curl -s -H "Authorization: $TOKEN" "http://$MINER_IP/mcb/cgminer?cgminercmd=devs"
```

Watch board 0 (often hottest / CPB side) especially.

### Kick fans up (keep clock/voltage)

Raise **only** the two RPM fields. Example: `40 → 70`.

```bash
python sclite_set_fan.py 70
```

What to expect with `tempcontrol=true` (normal):

1. Fans spike within a few seconds (e.g. ~1000 → ~1700 RPM).
2. Hot-board temp drops for a while.
3. Auto `fanctrl` steps duty back down toward ~85°C.
4. **Peak** lasts ~**10–20 seconds**.
5. Clearly elevated for roughly **1–3 minutes**, then back near the normal band.

So this is a **pulse / bias**, not “fans locked high.”

### Restore stock auto profile

```bash
python sclite_restore_auto.py
# sets manual=false, level-0 plan, tempcontrol=true
```

### Optional: watch without writing

```bash
python sclite_watch.py --seconds 210 --every 30
```

### Automatic temp manager (recommended for unattended kicks)

Because auto mode eases fans back down after ~1–3 minutes, use a small watchdog that **re-kicks** when the hot board climbs again.

**Step-by-step run & test:** see [`python/README.md`](python/README.md#how-to-run-and-test) (setup → snapshot → manual kick → TUI → test ideas).

Short version:

```bash
cd sc-lite/python
pip install -r requirements.txt
export SCLITE_IP='192.168.x.x'
export SCLITE_PASSWORD='your-miner-password'

python sclite_snapshot.py          # sanity check
cp sclite_temp_manager.example.json sclite_temp_manager.json
python sclite_temp_manager.py --config sclite_temp_manager.json
```

Defaults in the example config: kick to **70** when watched temp ≥ **80.5°C**, cooldown **45s**, abort ≥ **90°C**.

Interactive keys:

| Key | Action |
|-----|--------|
| `[` / `]` | `on_temp` −0.5 / +0.5 °C |
| `{` / `}` | `kick_fan` −5 / +5 |
| `p` | pause / resume control |
| `k` | force kick now (good first test) |
| `r` | restore stock auto plan |
| `s` | save current thresholds back to config |
| `q` | quit |

Quick tests: press `k` to force a kick; or lower `on_temp` with `[` until it is under the live hot-board temp and wait one poll. Headless: `--no-ui --once`.## 5. `tempcontrol` off (advanced / risky)

`tempcontrol` **is** exposed on the API (boolean).  
`target_temp` (**85°C**) is **not** editable via `/mcb/setting`.

Turning `tempcontrol` off can keep a kick more effective for a short window, but you lose the auto thermal ramp. **Do not leave it off unattended.**

Use the abort-safe helper:

```bash
python sclite_tempcontrol_test.py --fan 70 --abort-c 88 --max-seconds 90 --poll 3
```

That script:

- refuses to start if already ≥ abort temp
- sets `tempcontrol=false` + fan kick
- polls every few seconds
- **forces `tempcontrol=true` again** on abort, timeout, Ctrl+C, or error

Our 90s lab run peaked ~83.4°C and restored cleanly. Still treat this as hazardous.

## 6. Safety checklist

1. Prefer fan-only edits (leave MHz / V / PV alone) while learning.
2. Keep `tempcontrol=true` unless you are actively watching.
3. Abort well below firmware cutoff (~95°C). We used **≥88°C**.
4. After any `PUT`, re-check temps **and** `/dbg/minerinfo` voltage (manual mode can nudge reported mV).
5. Do **not** casually hit `/mcb/facrst` (factory reset) or `/mcb/restart`.
6. Change the default web password if the miner is reachable outside a trusted LAN.

## 7. Minimal raw HTTP example (fan kick)

Pseudo-flow:

```text
1) GET /user/login?username=admin&password=<aes-hex>&cipher=true
   -> JWT Token

2) GET /mcb/setting
   -> copy JSON

3) modify:
   manual = true
   manualPowerplan = "<same MHz/V/PV> but higher fanA/fanB"
   (leave tempcontrol true unless you accept the risk)

4) PUT /mcb/setting  with full JSON body

5) GET /mcb/cgminer?cgminercmd=devs
   -> confirm fans/temps moved
```

Working wrappers: `sc-lite/python/sclite_set_fan.py` and friends.

## See also

- [README.md](README.md) — full API map and dbg endpoints
- [../README.md](../README.md) — fork findings summary
- Upstream bash reclock tools: `miner-profile`, `miner-health`, `miner-runtime`
