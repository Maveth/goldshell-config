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
