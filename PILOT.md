# PiWallet store pilot — docs repo handoff

Full pilot status: `~/piwalletsv-infra/PILOT.md` (backend + infra).
Ops detail: [`docs/store/operator.md`](docs/store/operator.md).

## This repo (`PiWallet`, branch `store-dev`)

MkDocs site and store checkout UI for dev/prod.

### Dev URLs

- https://dev.piwalletsv.com
- Store API (configured at publish): https://store.dev.piwalletsv.com

### Done

- BSV checkout + email verify + pending / order status / operator pages
- Donate page + header Donate link
- Dev site published; **pilot browser pass passing** (see infra `PILOT.md`)
- Docs cleanup: GitHub Releases as SoT, companion official URL, etc.

### Next

1. ~~Publish + browser-test BSV / donate / operator on dev~~ — done.
2. **Commit + push** `store-dev` (large dirty tree).
3. Prod cutover with infra (publish `--env prod` once `store.piwalletsv.com` exists).

## New chat starter

```
Continue PiWallet store pilot (docs). Read PiWallet/PILOT.md and piwalletsv-infra/PILOT.md.
Branch: store-dev. Pilot browser pass DONE. Next: commit/push, then prod publish.
```
