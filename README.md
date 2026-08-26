# goldshell-config (MaVeTh fork)

Fork of [BitcoinMechanic/goldshell-config](https://github.com/BitcoinMechanic/goldshell-config) for **Goldshell Blake2b** control-plane notes.

Upstream proved the SC Lite can be **reclocked** via the stock web API.  
This fork documents what we verified in the **MaVeTh TN4 / BIP-110 lab** on a live **Goldshell SC Lite (fw 2.2.0)**: fans, tempcontrol, auth, ports, and safety.

> Not firmware. Not a shell exploit. Stock HTTP + BFGMiner API only.

## What’s useful

| Area | Status |
|------|--------|
| Reclock via `PUT /mcb/setting` | Works (Mechanic) |
| Fan duty bias via powerplan `RPM` fields | **Works** (verified) |
| Fans stay pinned high | **No** — auto `fanctrl` walks them back toward `target_temp≈85°C` |
| `tempcontrol` on/off via API | **Exposed** (boolean) |
| `target_temp` (85°C) editable via API | **Not exposed** |
| Network SSH / telnet | **Closed** on our unit |
| Open BFGMiner API `:4028` | Read OK; privileged writes `Access: N` |
| Auto JWT login (no browser copy) | Works — AES password cipher |

## Lab context (why we care)

We’re running BIP-110 / Blake2b work against DATUM on TN4. The SC Lite is pointed at local DATUM stratum and used as a real ASIC under test. Tuning fans/clocks from the LAN (without cracking open the box) helps thermal noise and flap while we iterate pool/coinbase paths.

## Layout

```
sc-lite/
  README.md           # how-to, API map, safety
  miner-health        # upstream bash (needs browser JWT)
  miner-profile       # upstream bash reclock profiles
  miner-runtime       # upstream bash voltage/clock dump
  sclite-miner.conf   # env template
  python/             # MaVeTh helpers (auto-login)
```

## Credit

Original SC Lite tooling and reclock discovery: **BitcoinMechanic**.  
Lab verification / fan + tempcontrol notes / auto-login helpers: **MaVeTh**.

If you learn more on SC5 Pro or other Blake2b Goldshells, PRs welcome upstream and here.
