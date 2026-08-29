# goldshell-config

Notes and tooling for tweaking **Goldshell Blake2b** miners (SC Lite first).

So far the **SC Lite** (fw **2.2.0**) has been the friendliest: stock web API can **reclock** and **kick fans** without custom firmware or SSH.

**HS Box** uses the same HTTP/JWT control plane; fan kicks are **confirmed** on a live unit (**Hersh-23**). Its powerplan string differs (float V, often no `PV`) — use [`hs-box/python/`](hs-box/python/), not the SC Lite helpers.

The SC5-Pro has been more annoying/sensitive. If you make progress on any Blake2b Goldshell, PRs welcome — goal is a shared dump of Blake mining control-plane hacks.

## Models

| Path | What |
|------|------|
| [`sc-lite/`](sc-lite/) | **SC Lite** — verified reclock + fan/temp tools (fw 2.2.0) |
| [`hs-box/`](hs-box/) | **HS Box** — fan API + helpers **confirmed** (Hersh-23); different plan grammar |

## SC Lite

| Path | What |
|------|------|
| [`sc-lite/CONNECT_AND_FANS.md`](sc-lite/CONNECT_AND_FANS.md) | **Start here** — connect, JWT auth, fan kicks, safety |
| [`sc-lite/README.md`](sc-lite/README.md) | API map / dbg notes |
| [`sc-lite/miner-profile`](sc-lite/miner-profile) | Bash reclock profiles (browser JWT) |
| [`sc-lite/miner-health`](sc-lite/miner-health) / [`miner-runtime`](sc-lite/miner-runtime) | Bash status helpers |
| [`sc-lite/python/`](sc-lite/python/) | Auto-login Python tools + **temp manager** (fan kick when hot) |

### Fan control (verified — SC Lite)

Powerplan string shape:

```text
<MHz> MHz <mV> V <fanA> RPM <fanB> RPM PV <pv>
```

- The `RPM` fields are **not** literal fan RPM — they bias/kick all fans together.
- With `tempcontrol=true` (default), `fanctrl` walks fans back toward ~**85 °C**; a kick is a **pulse** (~10–20s peak, ~1–3 min elevated), not a lock.
- `tempcontrol` on/off is API-exposed; the **85 °C target itself is not** editable via `/mcb/setting`.
- No per-fan API on stock fw 2.2.0.
- No network SSH on the unit we tested (`:80` + `:4028` open; 22/23 closed).

## HS Box

| Path | What |
|------|------|
| [`hs-box/README.md`](hs-box/README.md) | Status, dialect, credit |
| [`hs-box/python/`](hs-box/python/) | HS Box helpers (float V / optional PV) |

Example plan: `750 MHz 0.41 V 50 RPM 50 RPM` — change **only** the RPM fields.

Credits: original reclock tooling — **BitcoinMechanic**. SC Lite fan/temp Python — **MaVeTh**. HS Box live verification + `hs-box/python` — **Hersh-23**.
