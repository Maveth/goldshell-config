# fixtures/sc5proii

Sanitized capture of a friend's **Goldshell SC5 Pro II** (hardware `30.50.SA`,
`MCB_V3_3`, firmware `2.2.0`), originally published in:

https://github.com/crProductGuy/goldshell-box-tools-productguy  
`tests/fixtures/sc5proii/` (MIT) — see `../ATTRIBUTION.md` and `PRODUCTGUY_LICENSE.txt`.

| File | Endpoint |
|---|---|
| `mcb_status.json` | `GET /mcb/status` — model string uses Unicode Ⅱ (`Goldshell-SC5ProⅡ`) |
| `mcb_setting.json` | `GET /mcb/setting` — `mv_pv` plan + named levels |
| `api4028_devs.json` | `:4028 {"command":"devs"}` — **4 PGA boards**, 4 fans |
| `api4028_summary.json` | `:4028 {"command":"summary"}` |

Use these when extending the probe or filing "my box looks like SC5" issues.
Pool credentials were never included in the upstream capture.

## Live re-confirm (btcrealm, 2026-09-22)

Same unit family still reports:

- `model`: `Goldshell-SC5ProⅡ` (Unicode Ⅱ)
- `firmware` 2.2.0 / `hardware` 30.50.SA / `MCB_V3_3`
- `:4028` `devs`: **4** PGA, `fan0`–`fan3`, clock 700, voltage **11750** (= plan)
- Plan: `700 MHz 11750 V 30 RPM 30 RPM PV 11900` (`manual=false`, `tempcontrol=true`)
- `/mcb/status` answered even **without** an `Authorization` header on that day
  (still send JWT for `/mcb/setting` and `/dbg/*`)

### Our probe (same day)

`python -c "from probe import probe_miner; …"` against this unit returned:

- **Suggested profile:** `sc5-pro-ii` · known family · needs_community_capture **False**
- 4 boards / 4 fans · hot chip ~90 °C · ~13.8 TH/s · ~3.0 kW DC from 4028 V×I
- Plan levels named Hashrate / Low-power / Idle · `mv_pv` · no `temp_targets`
- `fan_kick_likely` True · `fan_target_adjustable` False · `temp_target_basis` fixed

**Support claim:** SC5 Pro II is supported for **probe / classify / monitor / plan dialect**.
Fan-kick / auto-fan assumed same `mv_pv` path as SC Lite — optional live kick still nice, not required to call the product known.
