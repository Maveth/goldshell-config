# Attribution

## crProductGuy / goldshell-box-tools-productguy

Portions of this webui were adapted from:

**https://github.com/crProductGuy/goldshell-box-tools-productguy**  
MIT License — Copyright (c) ProductGuy / contributors

| Our file | Stolen / adapted from | What |
|---|---|---|
| `models.py` | `gbox/models.py` | Model capability table (SC-BOX, SC Lite, **SC5 Pro / Pro II** rows, plan dialects, board_source, fan_target, absent_signature, plan_names) |
| `boards.py` | `gbox/api.py` (`parse_devs4028`, `parse_minerinfo_boards`, `board_totals`) | Multi-board PGA parsing so SC5 (4 boards) and multi-board SC Lite classify correctly |
| `soft_watchdog.py` | `gbox/watchdog.py` (soft-restart rules only) | Unreachable / stall / absent soft-restart judge; **no** Kasa power-cycle yet |
| `fixtures/sc5proii/*` | `tests/fixtures/sc5proii/*` | Sanitized SC5 Pro II capture (fw 2.2.0, 4× PGA) for probe matching / community docs |

ProductGuy’s project is battle-hardened around recoverability (soft restart + optional smart-plug power cycle) and SC5 Pro board visibility. We keep our fleet UI / auto-fan / pool failback; we steal compatibility + recovery basics so the **Setup / Probe** wizard can classify more Goldshells and seed profiles for others.

### Firmware care (also from ProductGuy docs)

- Prefer **one request in flight** to a miner; avoid poll bursts (token race / web backend crash).
- Stock UI Miner-page **Save** on the settings block can clear `manual: true` — prefer our plan/fan APIs when running a manual clock.

Thank you ProductGuy — and btcrealm for the SC5 Pro II traces behind those fixtures.
