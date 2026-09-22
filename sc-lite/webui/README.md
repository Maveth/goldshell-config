# SC Lite Control (fleet web UI)

Interactive fleet + single-miner control plane for Goldshell SC Lite.
More ops than the stock web UI: fans, pools, failback, soft restart, multi-select, auto fan-kick.

## Dependencies (self-contained)

This folder is **standalone**:

| Needs | Notes |
|-------|--------|
| Python 3.10+ | stdlib HTTP server |
| `pycryptodome` | JWT login AES — `pip install -r requirements.txt` |
| `miner_client.py` / `fan_controller.py` | **shipped here** — does **not** import your lab paths or NAS code |

**Not included in git:** `miners.json` (your IPs/passwords). Copy from `miners.example.json`.

### Ubuntu / Debian note (PEP 668)

Modern Ubuntu blocks system-wide `pip` (`externally-managed-environment`).
Use a **venv** (or `apt install python3-pycryptodome`):

```bash
cd sc-lite/webui
sudo apt install -y python3-pip python3-venv   # once
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# deep probe (default) — paced extra reads: Bearer vs raw auth, plan vs voltage,
# /dbg/icinfo chips, fanctrllog snippet, algosetting (~20–30s):
python -c "from probe import probe_miner; print(probe_miner('MINER_IP','PASSWORD')['github_issue_markdown'])"

# faster shallow probe:
python -c "from probe import probe_miner; print(probe_miner('MINER_IP','PASSWORD', deep=False)['github_issue_markdown'])"

# EXPERIMENTAL fan kick (writes then restores plan fan fields; skips if hot >=92C):
python -c "from probe import probe_miner; print(probe_miner('MINER_IP','PASSWORD', experimental_fan_kick=True)['github_issue_markdown'])"
```

**Fan kick is opt-in.** Default probe never changes fans. Kick pulses plan RPM bias (~80), waits ~10s, checks 4028 RPM, restores prior `/mcb/setting`.

**Support levels** (from `models.py` + probe):

| Profile | Level | Notes |
|---|---|---|
| `sc-lite` | `fleet-monitor` | Live-verified; fan kick tested |
| `sc5-pro-ii` | `fleet-monitor` | Probe live-verified; fan kick *likely* (same `mv_pv`), not yet kicked |
| `hs-box` | `fleet-monitor` | Float-V dialect |
| unknown | `probe-only` | File the markdown as an issue |

## Run

```powershell
cd sc-lite\webui
pip install -r requirements.txt
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
