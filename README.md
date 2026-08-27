# goldshell-config

Notes and tooling for tweaking **Goldshell Blake2b** miners (SC Lite first).

So far the **SC Lite** (fw **2.2.0**) has been the friendliest: stock web API can **reclock** and **kick fans** without custom firmware or SSH.

The SC5-Pro has been more annoying/sensitive. If you make progress on any Blake2b Goldshell, PRs welcome — goal is a shared dump of Blake mining control-plane hacks.

## SC Lite

| Path | What |
|------|------|
| [`sc-lite/CONNECT_AND_FANS.md`](sc-lite/CONNECT_AND_FANS.md) | **Start here** — connect, JWT auth, fan kicks, safety |
| [`sc-lite/README.md`](sc-lite/README.md) | API map / dbg notes |
| [`sc-lite/miner-profile`](sc-lite/miner-profile) | Bash reclock profiles (browser JWT) |
| [`sc-lite/miner-health`](sc-lite/miner-health) / [`miner-runtime`](sc-lite/miner-runtime) | Bash status helpers |
| [`sc-lite/python/`](sc-lite/python/) | Auto-login Python tools + **temp manager** (fan kick when hot) |

## Other boxes

| Path | What |
|------|------|
| [\sc-lite/HS_BOX_NOTES.md\](sc-lite/HS_BOX_NOTES.md) | HS Box dialect (**unconfirmed**) — not in default helpers yet |

### Fan control (verified)

Powerplan string shape:

```text
<MHz> MHz <mV> V <fanA> RPM <fanB> RPM PV <pv>
```

- The `RPM` fields are **not** literal fan RPM — they bias/kick all fans together.
- With `tempcontrol=true` (default), `fanctrl` walks fans back toward ~**85 °C**; a kick is a **pulse** (~10–20s peak, ~1–3 min elevated), not a lock.
- `tempcontrol` on/off is API-exposed; the **85 °C target itself is not** editable via `/mcb/setting`.
- No per-fan API on stock fw 2.2.0.
- No network SSH on the unit we tested (`:80` + `:4028` open; 22/23 closed).

Credits: original reclock tooling — **BitcoinMechanic**. Fan/tempcontrol verification + Python helpers — contributors welcome.
