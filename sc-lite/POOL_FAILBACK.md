# SC Lite pool failback (sticky failover)

**Single-miner tool.** Talks to one Goldshell SC Lite over LAN.  
Does **not** touch your pool software, DATUM gateways, or Bitcoin node.

## Problem

Goldshell’s built-in **Failover** strategy:

1. Pool 0 dies → miner moves to pool 1  
2. Pool 0 comes back **Alive**  
3. Miner often **keeps hashing on pool 1** forever  

There is no reliable keep-alive failback to priority 0.  
BFG/cgminer TCP API (`:4028`) exposes `switchpool` / `poolpriority`, but on SC Lite firmware **2.2.0** those writes are **`Access: N`**.

## What works

| Step | API | Auth |
|------|-----|------|
| See Alive / who has recent shares | TCP `:4028` `pools` / `summary` | none |
| Reorder preferred pool + `active` flags | `PUT /mcb/pools` | JWT (login password) |
| Drop sticky stratum session | `GET /mcb/restart` (soft restart) | JWT |

**`PUT` alone is not enough** — the backup stratum session stays up. Soft restart after the PUT is required.

## How we decide “needs failback”

Do **not** trust `Stratum Active` alone (both pools can show `true`).

1. Preferred pool index (default **0**) must be **`Status=Alive`**  
2. **Working pool** = Alive pool with the **newest `Last Share Time` > 0**  
3. If working ≠ preferred → kick  

Optional watch mode adds a **grace** window so a brief blip doesn’t thrash restarts.

## Script

```text
sc-lite/python/sclite_pool_failback.py
```

Depends on `sclite_common.py` (same folder) and `pycryptodome`.

### Setup

```powershell
cd sc-lite\python
pip install -r requirements.txt

$env:SCLITE_IP = '192.168.0.202'
$env:SCLITE_PASSWORD = 'your-miner-password'   # only needed for --apply
```

### Status only (no password)

```powershell
python sclite_pool_failback.py --once
# or:
python sclite_pool_failback.py --ip 192.168.0.202 --once
```

### Force re-kick on this one miner (recommended recovery)

When pool 0 is Alive again but shares are still landing on pool 1:

```powershell
python sclite_pool_failback.py --once --apply
```

That will:

1. `PUT /mcb/pools` — preferred first, `active=true`; others `active=false`  
2. Soft restart — `GET /mcb/restart`  
3. Wait until the miner answers again, then print pool status  

**Hashing pauses briefly** during soft restart (often ~30–90s).

Force even if detection is unsure:

```powershell
python sclite_pool_failback.py --once --apply --force
```

PUT-only (usually ineffective on this firmware):

```powershell
python sclite_pool_failback.py --once --apply --no-restart
```

### Watch loop (optional)

```powershell
python sclite_pool_failback.py --watch 30 --grace 60 --apply
```

- Poll every **30s**  
- Kick only if the failback condition holds for **60s**  
- Still only one `--ip` miner  

## Pool order

Failover does **not** renumber slots. Indices/priorities stay `0, 1, …`.  
Only `Status` / who receives shares changes. Preferred stays slot 0.

## Add / remove pool slots (related APIs, not in this script yet)

| Action | Endpoint |
|--------|----------|
| List | `GET /mcb/pools` |
| Replace / reorder | `PUT /mcb/pools` |
| Add | `PUT /mcb/newpool` `{url,user,pass}` |
| Delete | `PUT /mcb/delpool` (pool object) |

## Safety

- One miner IP only (`SCLITE_IP` / `--ip`)  
- Default is **dry-run** (no PUT, no restart)  
- Never calls factory reset (`/mcb/facrst`)  
- Soft restart interrupts hashing briefly — use `--grace` in watch mode  
- Do not commit real passwords; use env vars  

## Lab notes (MaVeTh)

Validated on SC Lite @ `192.168.0.202`, firmware path using JWT `/mcb/*`:

1. Stopped preferred stratum gateway → miner went to pool 1 (SV1)  
2. Brought preferred gateway back → pool 0 **Alive**, shares still on pool 1  
3. `PUT /mcb/pools` alone did not move work  
4. Failback detection uses **newest last-share**, not `Stratum Active` alone  
5. Soft restart after PUT returns work to preferred when it is Alive  

## Related

- Fan / temp manager: [`python/README.md`](python/README.md)  
- Connect + auth walkthrough: [`CONNECT_AND_FANS.md`](CONNECT_AND_FANS.md)  
