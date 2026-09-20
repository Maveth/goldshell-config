# SC Lite notes (fw 2.2.0)

**Practical guide:** [`CONNECT_AND_FANS.md`](CONNECT_AND_FANS.md)

## Bash tools (browser JWT)

```bash
export MINER_IP='192.168.x.x'
export TOKEN='…'   # localStorage.getItem('token') on /#/debug

./miner-health
./miner-runtime
./miner-profile status|stock|quiet|ultraquiet
```

## Python tools (auto-login)

See [`python/README.md`](python/README.md).

**Pool failback** (sticky failover → kick back to preferred pool):  
[`POOL_FAILBACK.md`](POOL_FAILBACK.md) · `python/sclite_pool_failback.py`

## Useful HTTP surfaces

| Path | Role |
|------|------|
| `GET /user/login?…&cipher=true` | JWT |
| `GET/PUT /mcb/setting` | powerplan / manual / tempcontrol |
| `GET /mcb/status` | model / firmware |
| `GET /mcb/pools` | stratum pools |
| `PUT /mcb/pools` | reorder / set active (failback) |
| `PUT /mcb/newpool` / `PUT /mcb/delpool` | add / remove pool slots |
| `GET /mcb/restart` | soft restart (not factory reset) |
| `GET /mcb/cgminer?cgminercmd=devs` | temps / fans / hashrate |
| `GET /dbg/minerinfo` | voltage / clock |
| `GET /dbg/fanctrllog` | `target_temp:85` + duty steps |
| `GET /dbg/icinfo` | per-chip / CPB boards |
| TCP `:4028` | read-only miner API (`summary`, `devs`, …); writes often `Access: N` |

Internal powerplan encoding (from `/dbg/minerhistory`):

```text
intchains_qomo:vfff=<pv>:<MHz>:<fanA>:<fanB>:<mV>
```

Live algo on the SC Lite we tested: **`blake2b(SC)`** only.
