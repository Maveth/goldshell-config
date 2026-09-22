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
# → http://127.0.0.1:8787 by default (dev)
```

### NAS (docker)

```bash
cd /mnt/Alexandria/local/bip110-lab/sclite-webui
docker compose up -d --build
# → http://192.168.0.143:8790   (host network, port 8790)
```

Env overrides:

```text
SCLITE_WEBUI_HOST=0.0.0.0
SCLITE_WEBUI_PORT=8790          # NAS compose default
SCLITE_WEBUI_MINERS=/data/miners.json
```

**Security:** no login on the webui itself — anyone who can reach `:8787` can control configured miners. Use firewall / bind `127.0.0.1` if needed.

## Features

### Fleet / Batch / Settings
- Fleet cards: H/s, temp, fans, pool, auto-fan, Fan ±  
- Batch: add pool (keep worker), order, remove/promote URL  
- Settings: auto-fan profiles, add miner, demo miners  
- **Setup / Probe:** learn model/fw/plan dialect/ports/pools/**board count** from an unknown box; **Copy GitHub issue markdown** (no passwords) for `sc-lite` / `hs-box` / `sc-box` / `sc5-pro` / `sc5-pro-ii` / unknown captures
- **Model table + multi-board parser:** SC5 Pro II (4 boards / 4 fans) and friends — adapted from [ProductGuy’s goldshell-box-tools](https://github.com/crProductGuy/goldshell-box-tools-productguy) (MIT); see `ATTRIBUTION.md` and `fixtures/sc5proii/`
- **Soft watchdog (stub):** unreachable / share-stall / board-absent → soft restart; **dry_run by default**; no smart-plug power cycle yet (`watchdog_defaults` / per-miner `watchdog` in `miners.json`; status at `/api/watchdog/status`)

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
