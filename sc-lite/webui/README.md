# SC Lite Control (fleet web UI)

Interactive fleet + single-miner control plane for Goldshell SC Lite.
More ops than the stock web UI: fans, pools, failback, soft restart, multi-select, auto fan-kick.

## Dependencies (self-contained)

This folder is **standalone**:

| Needs | Notes |
|-------|--------|
| Python 3.10+ | stdlib HTTP server |
| `pycryptodome` | JWT login AES — install via `../python/requirements.txt` |
| `miner_client.py` / `fan_controller.py` | **shipped here** — does **not** import your lab paths or NAS code |

**Not included in git:** `miners.json` (your IPs/passwords). Copy from `miners.example.json`.

## Run

```powershell
cd sc-lite\webui
pip install -r ..\python\requirements.txt
copy miners.example.json miners.json
# edit miners.json — set real IP + password (never commit this file)

python server.py
# → http://127.0.0.1:8787  (listens on 0.0.0.0 by default — LAN reachable)
```

Env overrides:

```text
SCLITE_WEBUI_HOST=0.0.0.0
SCLITE_WEBUI_PORT=8787
SCLITE_WEBUI_MINERS=C:\path\to\miners.json
```

**Security:** no login on the webui itself — anyone who can reach `:8787` can control configured miners. Use firewall / bind `127.0.0.1` if needed.

## Features

### Fleet
- Card per miner: online, H/s, temp, fans, uptime, **working pool**
- Sticky-failover warning when P0 Alive but work on another pool
- **Fan −5 / +5** on cards + fleet (nudges plan bias; updates offset for auto)
- **Auto fan control** checkbox + profile select (steps / single / smooth) — background re-kick loop (tempcontrol walks fans back otherwise)
- Multi-select: kick fans, tempcontrol, failback→P0, soft restart
- **Batch add pool** — URL + payout; **keeps each miner’s worker** (`address.worker`), pass default `x`
- **Batch order** — set pool indexes (`1,0`), promote URL to P0, remove URL
- Add / remove miners in local registry

### Single miner
- Live boards / temps / fans
- Fan bias kick + tempcontrol toggle + plan fields
- Pool table (who is working via last-share)
- Add / delete pool slots
- Failback preferred (PUT `/mcb/pools` + soft restart)
- Soft restart

## Stack
- Python stdlib `ThreadingHTTPServer`
- `miner_client.py` — per-miner JWT + BFG `:4028` (no global token clash)
- Static SPA (`static/`)

Uses the same Goldshell APIs as `sclite_common.py` / `sclite_pool_failback.py`.
