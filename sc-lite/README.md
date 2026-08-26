# SC Lite control notes (fw 2.2.0)

## Requirements

- Goldshell **SC Lite**
- Firmware **2.2.0** (what we tested)
- Network reachability to the miner HTTP UI (`:80`)
- Either:
  - browser JWT (upstream bash scripts), or
  - Python 3 + `pycryptodome` (MaVeTh helpers — auto login)

## Important: there is no network shell

On our unit:

| Port | Result |
|------|--------|
| 22 / 23 / 2222 | Closed |
| 80 | Open — Yotta MC web UI + `/mcb` + `/dbg` |
| 443 | Closed |
| 4028 | Open — BFGMiner/intminer JSON API (mostly read-only) |

`ps` via `/dbg/psinfo` shows Linux + busybox, `intminer -c /usr/config/bfgminer/bfgminer.json`, and a local `/bin/login` (console/UART), **not** sshd.

When Mechanic’s tools “write settings,” they are doing **HTTP `PUT /mcb/setting`**. The box’s `minerd` persists config under `/usr/config/…`. That is not SSH file editing from outside.

## Auth / JWT

### Upstream way (browser)

1. Open `http://<miner>/#/debug` (or login page)
2. Unlock with miner password
3. DevTools → Console → `localStorage.getItem('token')`
4. `export TOKEN='...'` and `export MINER_IP='...'`

Token expires; re-copy as needed.

### Auto-login way (how the cipher works)

Login is:

```http
GET /user/login?username=admin&password=<hex>&cipher=true
```

Password encryption (from stock UI JS module `5c64`):

- AES-CBC
- key = UTF-8 `!!!!!!!!!!!!!!!!` (16 exclamation marks)
- IV = 16 zero bytes
- padding = ZeroPadding
- send **ciphertext as hex** (CryptoJS `ciphertext.toString()`)

Response JSON includes `"JWT Token"`. Send it as:

```http
Authorization: <token>
```

(raw token works; `Bearer <token>` also worked in our probes)

Factory password on many units is still `123456789` — **change it** if the miner is reachable beyond a trusted LAN.

## Settings surface

### `GET/PUT /mcb/setting`

Example stock-ish payload:

```json
{
  "select": 0,
  "tempcontrol": true,
  "ledcontrol": false,
  "manual": false,
  "manualPowerplan": "625 MHz 9100 V 40 RPM 40 RPM PV 9400",
  "powerplans": [
    {"level": 0, "info": "625 MHz 9100 V 40 RPM 40 RPM PV 9400"},
    {"level": 3, "info": "0 MHz 0 V 100 RPM 100 RPM"}
  ],
  "name": "…",
  "version": "v1.0"
}
```

Powerplan string shape:

```text
<MHz> MHz <mV> V <fanA> RPM <fanB> RPM PV <pv>
```

| Field | Meaning (observed) |
|-------|--------------------|
| MHz | Chip clock target (Mechanic reclock) |
| V | Voltage field in plan (chip may report slightly different mV) |
| fanA / fanB RPM | **Not literal RPM** — fan duty bias / kick. Live fans are ~1000–1800 RPM |
| PV | Present in stock strings; leave alone unless you know what you’re doing |
| `manual` | Must be `true` for a custom `manualPowerplan` to stick |
| `tempcontrol` | Enables `fanctrl` closed-loop toward ~**85°C** |
| `select` | Preset level (`0` stock, `3` looks like stop/zeros) |

### Useful reads

| Path | Notes |
|------|-------|
| `/mcb/status` | model / firmware |
| `/mcb/pools` | stratum targets |
| `/mcb/cgminer?cgminercmd=devs` | per-board temp / fans / hashrate |
| `/dbg/minerinfo` | voltage / clock / fans (needs JWT + debug unlock) |
| `/dbg/icinfo` | per-chip map |
| `/dbg/fanctrllog` | shows `target_temp:85` and duty changes |
| `/dbg/psinfo` | process list |

### Port 4028 (no JWT)

JSON newline commands (`version`, `summary`, `pools`, `devs`, `config`, …).  
`config` reports `ConfigFile0: /usr/config/bfgminer/bfgminer.json`.  
Write-ish commands (`setconfig`, `save`, `addpool`, `privileged`) exist but returned **`Access: N`** on our box.

## What we verified (fans + temp)

### Fan kick with `tempcontrol=true`

1. `PUT` `manual=true` and raise only the two RPM fields (keep MHz/V/PV).
2. Live fans spike within seconds (e.g. ~1000 → ~1700 RPM).
3. Temps drop for a bit.
4. `fanctrl` then **steps duty back down** toward holding ~**85°C** on the hot board.
5. Peak blast lasts on the order of **~10–20 seconds**; clearly elevated fan for roughly **1–3 minutes**, then back near the auto band.

So: RPM fields are a **bias / pulse**, not a locked fan speed.

### `tempcontrol=false` test (do this carefully)

We ran a timed test:

- OFF + fan fields 70
- poll every 3s
- abort if any board ≥ **88°C**
- hard restore `tempcontrol=true` on timeout / abort / signal

Results on our unit:

- Peak stayed ~**83.4°C** over 90s (safe)
- Fans still rose after OFF
- Even with OFF, live RPM drifted somewhat (not a perfect hard lock)
- Restore path forced `tempcontrol=true` successfully

**Critical:** never leave `tempcontrol=false` unattended. Always have an automatic restore.

Thermal cutoff reported via 4028 `devdetails` was around **95°C** — still do not rely on that as your abort line.

## Upstream bash scripts

```bash
export MINER_IP='192.168.x.x'
export TOKEN='…'          # from browser localStorage

./miner-health            # plan + boards + optional chip health
./miner-runtime           # voltage/clock from /dbg/minerinfo
./miner-profile status
./miner-profile stock|quiet|ultraquiet
```

`miner-profile` rewrites `manualPowerplan` (clock-oriented profiles from Mechanic).

## MaVeTh Python helpers

See `python/README.md`. These auto-login (AES cipher) so you don’t copy JWT from the browser each time.

## Safety checklist

1. Prefer changing **only fan fields** when testing thermal behavior.
2. Keep `tempcontrol=true` unless you are actively watching.
3. If you disable it: hard time limit + temp abort + restore-on-exit.
4. Watch the **hottest board** (often board 0 / CPB side) — cooler boards can look fine while the hot one sits on the 85°C target.
5. Note: enabling `manual` sometimes briefly bumps reported chip voltage (we saw 9000 ↔ 9330) even when the plan string still said `9100 V`. Re-check `/dbg/minerinfo` after PUTs.
