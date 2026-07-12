# PiWallet store pilot — docs repo handoff

Full pilot status: `~/piwalletsv-infra/PILOT.md` (backend + infra).
Ops checklist: [`docs/store/operator.md`](docs/store/operator.md).

## This repo (`PiWallet`, branch `store-dev`)

MkDocs site and store checkout UI for dev/prod.

### Dev URLs

- https://dev.piwalletsv.com
- Store API (configured at publish): https://store.dev.piwalletsv.com

### Done (local)

- BSV checkout page: `docs/store/checkout-bsv.md`, `docs/assets/store-checkout-bsv.js`
- Email verify landing: `docs/store/verify-email.md`, `docs/assets/store-verify-email.js`
- Pending BSV / order status / operator pages updated
- `mkdocs.yml` nav + cache-busted scripts
- Buy button redirects to `/store/checkout-bsv/?sku=...`

### Next

1. Backend SES DNS + secrets (see infra `PILOT.md`)
2. Publish dev site:
   ```bash
   AWS_PROFILE=terraform-admin ./scripts/publish.sh site --env dev
   ```
3. Browser-test full BSV flow on dev

## New chat starter

```
Continue PiWallet store pilot (docs). Read PiWallet/PILOT.md and piwalletsv-infra/PILOT.md.
Branch: store-dev. Next: publish dev site and browser-test BSV checkout.
```
