# Connect to an SC Lite and control fans

Verified on **Goldshell SC Lite firmware 2.2.0**.  
No SSH. No custom firmware. Stock HTTP API only.

## 1. Reach the miner

1. Put the miner on your LAN (DHCP is fine).
2. Find its IP.
3. Confirm ports from your PC:

| Port | Expected | Use |
|------|----------|-----|
| **80** | Open | Web UI + control API (`/mcb`, `/user`, `/dbg`) |
| **4028** | Open | Optional BFGMiner/intminer **read** API (no JWT) |
| 22 / 23 / 2222 / 443 | Often closed | No network shell / no HTTPS on our unit |

```bash
curl -s http://<MINER_IP>/mcb/status
# {"hardware":"...","model":"Goldshell-SCLITE","firmware":"2.2.0",...}
```

Optional unauthenticated monitor:

```bash
echo '{"command":"summary"}' | nc <MINER_IP> 4028
echo '{"command":"devs"}'    | nc <MINER_IP> 4028
```

Config writes need **port 80 + JWT**.

## 2. Authenticate (JWT)

### Option A — browser token (bash scripts)

1. Open `http://<MINER_IP>/#/debug` and unlock.
2. DevTools → Console → `localStorage.getItem('token')`
3. `export MINER_IP=...` and `export TOKEN=...`

### Option B — auto-login (Python)

```http
GET /user/login?username=admin&password=<hex>&cipher=true
```

Password cipher (stock UI module):

- AES-CBC
- key = `!!!!!!!!!!!!!!!!` (16 `!`) — **this is the cipher key, not the login password**
- IV = 16 zero bytes
- ZeroPadding
- send ciphertext as **hex**

Response field: `"JWT Token"`. Header: `Authorization: <token>`.

Factory web password is often still `123456789` — **change it** on anything beyond a trusted LAN.

```bash
cd sc-lite/python
pip install -r requirements.txt
export SCLITE_IP=192.168.x.x
export SCLITE_PASSWORD='your-miner-password'
python sclite_snapshot.py
```

## 3. Fan knobs

All fan edits go through:

```http
GET/PUT /mcb/setting
Authorization: <JWT>
Content-Type: application/json
```

Powerplan shape:

```text
<MHz> MHz <mV> V <fanA> RPM <fanB> RPM PV <pv>
```

Example stock: `625 MHz 9100 V 40 RPM 40 RPM PV 9400`

| Field | Notes |
|-------|--------|
| MHz / V | Clock / voltage (Mechanic reclock profiles) |
| fanA / fanB | Shared fan **bias/kick** — not per-fan, not literal RPM |
| PV | Leave alone unless you know what you’re doing |
| `manual` | Must be `true` for a custom plan to stick |
| `tempcontrol` | Writable boolean — **does not stop** the ~85 °C `fanctrl` walk (see below) |

**You can** watch one board’s temp and kick **all** fans when it’s hot.  
**You cannot** set `fan0` independently of `fan1/2/3` on stock API.

A kick is a **pulse**: peak ~10–20s, clearly elevated ~1–3 minutes, then auto eases back.
That walk-down continues even when `tempcontrol=false` (verified 2026-09-22 on live
`Goldshell-SCLITE` fw 2.2.0: 60s and 10 min OFF windows still logged `Fans Change …
target_temp:85`). So `tempcontrol` is **not** the on/off for the 85 °C fan loop.
What the flag *does* do (e.g. overheat path under heat) is still unknown — treat
`false` as incompletely characterized, not as “manual fans only.”

## 4. Safe fan kick

```bash
python sclite_set_fan.py 70          # keep MHz/V/PV; set both RPM fields
python sclite_snapshot.py
python sclite_restore_auto.py        # manual=false, stock level-0 plan
```

Or bash: copy JWT, then use / adapt `miner-profile` (clock-oriented).

## 5. Temp manager (auto re-kick)

Because auto mode eases fans down, a watchdog can re-apply fan fields when hot.

| Mode | Role | `tempcontrol` |
|------|------|----------------|
| `single` | **Basic** — one threshold → one kick | Keep **ON** |
| `steps` | **Advanced but safer** — temp ladder (highest match) | Keep **ON** |
| `smooth` | Continuous weighted ramp (**experimental — not fully tested yet**) | Keep **ON** for safety; stock `fanctrl` walk continues either way (OFF does **not** disable it). Fiddle `smooth.min_temp/max_temp/min_fan/max_fan`. Use abort + restore-on-exit. |

```bash
cp sclite_temp_manager.example.json sclite_temp_manager.json
python sclite_temp_manager.py --config sclite_temp_manager.json
python sclite_temp_manager.py --config sclite_temp_manager.steps.example.json
python sclite_temp_manager.py --config sclite_temp_manager.smooth.example.json
```

Keys: `m` cycle mode · `[` `]` on_temp · `{` `}` kick_fan · `p` pause · `k` force · `r` restore · `s` save · `q` quit

See [`python/README.md`](python/README.md).

## 6. `tempcontrol` off (risky / mostly useless for fan control)

`tempcontrol` boolean is writable; **`target_temp` (85) is not** (no `temp_targets` in
`/mcb/setting` on SC Lite).

**Important finding (2026-09-22):** setting `tempcontrol=false` does **not** stop
`/dbg/fanctrllog` `Fans Change` lines or the RPM walk-down toward holding ~85 °C.
Same behavior as ProductGuy/gbox reported on SC-BOX for “flag does not gate fans.”
Do not assume OFF = manual-only fans.

Only flip it with an abort watchdog (see `sclite_tempcontrol_test.py`). Do not leave
it off unattended — overheat-path behavior under heat is still unproven.

## 7. Safety

1. Prefer fan-only edits while learning (leave MHz / V / PV).
2. Keep `tempcontrol=true` unless actively watching.
3. Abort well below firmware cutoff (~95 °C); we used ≥88–90 °C.
4. After PUTs, re-check temps and `/dbg/minerinfo` voltage (manual mode can nudge reported mV).

5. Avoid casually hitting `/mcb/facrst` (factory reset) or `/mcb/restart`.

## Pool sticky failover

If the miner fails over to pool 1 and will not return when pool 0 is back, see
[POOL_FAILBACK.md](POOL_FAILBACK.md) (sclite_pool_failback.py: PUT /mcb/pools + soft restart).

