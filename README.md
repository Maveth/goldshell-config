# goldshell-config (MaVeTh fork)

Fork of [BitcoinMechanic/goldshell-config](https://github.com/BitcoinMechanic/goldshell-config) for **Goldshell Blake2b** control-plane notes.

Upstream proved the SC Lite can be **reclocked** via the stock web API.  
This fork documents what we verified in the **MaVeTh TN4 / BIP-110 lab** on a live **Goldshell SC Lite (fw 2.2.0)**: fans, tempcontrol, auth, ports, and safety.

> Not firmware. Not a shell exploit. Stock HTTP + BFGMiner API only.

## How-to: connect + control fans

**Start here:** [`sc-lite/CONNECT_AND_FANS.md`](sc-lite/CONNECT_AND_FANS.md)

**Run & test the Python tools / temp manager:** [`sc-lite/python/README.md`](sc-lite/python/README.md#how-to-run-and-test)

Covers ports, JWT login (browser or auto AES), powerplan fan kicks, how long fans stay up in auto mode, the interactive temp manager, and an abort-safe `tempcontrol` off test.

These helpers only talk to the miner over LAN — they are not tied to a BIP-110 checkout. A local working copy (e.g. `O:\HSlite`) is fine; keep this repo as the canonical source.

## Other boxes (staging)

| Path | What |
|------|------|
| [`sc-lite/HS_BOX_NOTES.md`](sc-lite/HS_BOX_NOTES.md) | **HS Box** powerplan dialect from a community report — **unconfirmed**. Reference parse/build only; **default Python helpers stay SC Lite** until we capture a live `manualPowerplan`. |

## Findings so far (SC Lite fw 2.2.0)

### Open / closed ports

| Port | State | What it is / how we use it |
|------|-------|----------------------------|
| **80** | **Open** | Stock Yotta MC web UI. Main control plane: `/mcb/*`, `/user/login`, `/dbg/*`. |
| **4028** | **Open** | Classic **BFGMiner / intminer** JSON API (no JWT). Great for quick `summary` / `pools` / `devs` / `config` reads. |
| 22 | Closed | No SSH |
| 23 | Closed | No telnet |
| 2222 | Closed | No alt-SSH |
| 443 | Closed | No HTTPS UI on our unit |

**There is no network shell.** Writes go through HTTP `PUT /mcb/setting` (JWT). The box persists under `/usr/config/…` itself.

### What we’re using today

| Tool / surface | Role |
|----------------|------|
| `GET /user/login?…&cipher=true` | Auto JWT (AES-CBC, key `!!!!!!!!!!!!!!!!`, zero IV, ZeroPadding → hex) |
| `GET/PUT /mcb/setting` | Clock / fan-bias powerplan, `manual`, `tempcontrol`, `ledcontrol` |
| `GET /mcb/status` | Model / firmware (`Goldshell-SCLITE`, `2.2.0`) |
| `GET /mcb/pools` | Stratum URL / worker |
| `GET /mcb/cgminer?cgminercmd=devs` | Per-board temp, fan RPM string, hashrate |
| `GET /dbg/minerinfo` | Voltage / clock / fans (JWT) |
| `GET /dbg/icinfo` | Per-chip / **CPB** board map |
| `GET /dbg/fanctrllog` | Proves `target_temp:85` + duty step-up/down |
| `GET /dbg/minerhistory` | Algo/plan/pool change log (internal encoding) |
| `GET /dbg/psinfo` | Process list (`intminer`, `minerd`, `fanctrl`, local `/bin/login`) |
| TCP `:4028` | Unauthenticated miner API reads; write cmds exist but `Access: N` |
| Upstream bash (`miner-profile` etc.) | Reclock profiles (browser JWT) |
| `sc-lite/python/*` | Auto-login helpers, abort-safe `tempcontrol` test, **temp manager** (kick fans when hot) |

### Lab known fact: ~3s Stratum flap is NORMAL

Goldshell `intminer` often opens/closes DATUM Stratum about every **~3 seconds** in logs. **That is expected — not a DATUM failure.** Judge health by DATUM client row (Subbed + username), then **DiffA / hashrate**, not by the flap lines.

### Behavior findings

1. **Powerplan string** shape:  
   `<MHz> MHz <mV> V <fanA> RPM <fanB> RPM PV <pv>`  
   Example stock: `625 MHz 9100 V 40 RPM 40 RPM PV 9400`
2. **Internal encoding** (from `/dbg/minerhistory`):  
   `intchains_qomo:vfff=<pv>:<MHz>:<fanA>:<fanB>:<mV>` + `algo=blake2b(SC)`  
   Driver name: **`intchains_qomo`**.
3. **Fan “RPM” fields are not literal RPM.** Live fans run ~1000–1800. Those fields are a **shared duty bias / kick** for all fans together. **No per-fan API.**
4. **Fans do not stay pinned high** with `tempcontrol=true`. `fanctrl` walks duty back toward holding the hot board near **~85°C**. Peak blast ~10–20s; clearly elevated ~1–3 minutes.
5. **`tempcontrol` boolean is API-exposed.** The **`target_temp` value (85) is not** editable via `/mcb/setting` (only visible in `fanctrllog`).
6. **`tempcontrol=false` + fan kick** cooled boards in a timed test (peak ~83.4°C over 90s) but live RPM still drifted some — not a perfect hard lock. Always restore `tempcontrol=true` with an abort watchdog.
7. Enabling **`manual=true`** can briefly bump reported chip voltage (we saw **9000 ↔ 9330 mV**) even when the plan still said `9100 V`. Re-check `/dbg/minerinfo` after PUTs.
8. Hot board (often board 0 / **CPB0** in `icinfo`) is the limiter; cooler boards can look fine while board 0 sits on the 85°C target.
9. Runtime process picture: `intminer -c /usr/config/bfgminer/bfgminer.json`, plus `minerd` / `xminerd`, `fanctrl`, busybox `ntpd`. Debug dumps shell out to `/backup/minerd/trash/…` from the web backend — still not a remote shell for us.
10. `:4028` `devdetails` reported Target ~89°C / Cutoff ~95°C (informational). Do **not** treat cutoff as your abort line — abort earlier (we used ≥88°C).
11. Hash method on `:4028` `coin` showed **`blake2b`** while pointed at our DATUM stratum.
12. Live algo setting is **single-algo**: `blake2b(SC)` only. Tutorial JSON still lists HNS pool links (shared UI leftover) — not proof this unit can switch algos.

### Extra API surface (mapped, mostly unused by us)

| Endpoint | Notes |
|----------|-------|
| `/mcb/algosetting` | `{"algos":[{"name":"blake2b(SC)","id":0}],"algo_select":0}` |
| `/mcb/newpool`, `/mcb/delpool`, `/mcb/resultpool` | Pool add/remove/reorder API present |
| `/mcb/ip` | DHCP (`useDHCP`/`useAuto` true on our unit) |
| `/mcb/wifisetting` | `exist:false` — no WiFi hardware path here |
| `/mcb/cmossetting` | Present but `enable:false` / no userkey |
| `/mcb/rgbsetting` | Empty on this unit |
| `/mcb/ledcontrol` via setting | Boolean LED toggle |
| `/cpb/hshistory` | Hashrate history array for UI charts |
| `/user/updatepd` | Password change |
| `/mcb/restart` | Soft restart — dangerous if poked casually |
| `/mcb/facrst` | **Factory reset** — dangerous |
| `/mcb/uploadimage` | Firmware/image upload path |

`:4028` write-ish commands (`addpool`, `setconfig`, `save`, `restart`, `privileged`, `pgaset`, …) **exist** but returned **`Access: N`**. Use `:80` + JWT for control; `:4028` for monitoring.

### Still unknown / not done

- Editing `target_temp` without firmware / on-box file access
- Privileged `:4028` writes (`Access: N` so far)
- Per-fan / per-board independent fan PWM
- SC5 Pro (upstream: more annoying/sensitive)
- Whether `PV` / `vfff` experiments are safe
- Braiins-style per-chip voltage tooling — not in this stock API

## Lab context (why we care)

We’re running BIP-110 / Blake2b work against DATUM on TN4. The SC Lite is pointed at local DATUM stratum and used as a real ASIC under test. Tuning fans/clocks from the LAN (without cracking open the box) helps thermal noise and flap while we iterate pool/coinbase paths.

## Layout

```
sc-lite/
  CONNECT_AND_FANS.md # start here: connect + fan control writeup
  README.md           # detailed API map, dbg, safety
  miner-health        # upstream bash (needs browser JWT)
  miner-profile       # upstream bash reclock profiles
  miner-runtime       # upstream bash voltage/clock dump
  sclite-miner.conf   # env template
  python/             # MaVeTh helpers (auto-login)
```

## Credit

Original SC Lite tooling and reclock discovery: **BitcoinMechanic**.  
Lab verification / fan + tempcontrol notes / auto-login helpers: **MaVeTh**.

If you learn more on SC5 Pro or other Blake2b Goldshells, PRs welcome upstream and here.
