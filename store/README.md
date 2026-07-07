# PiWalletSV store API

JSON-only order service for kit/case sales. Card checkout uses **Stripe Checkout**; BSV is manual (operator marks paid).

## Routes

| Method | Path | Auth |
|--------|------|------|
| POST | `/v1/checkout/stripe` | — |
| POST | `/v1/checkout/bsv` | — |
| POST | `/v1/webhooks/stripe` | Stripe signature |
| GET | `/v1/orders/{id}` | — |
| POST | `/v1/admin/orders/{id}/mark-paid` | `X-Admin-Key` |

## Environment

| Variable | Description |
|----------|-------------|
| `TABLE_NAME` | DynamoDB orders table |
| `CATALOG_ENV` | `dev` → `catalog/products.dev.json` |
| `STRIPE_SECRET_KEY` | Stripe secret (test or live) |
| `STRIPE_WEBHOOK_SECRET` | Webhook signing secret |
| `ADMIN_API_KEY` | Protects mark-paid route |
| `BSV_RECEIVE_ADDRESS` | Shown on BSV pending orders |
| `FULFILLMENT_ENABLED` | `false` on dev — log only, no ship |
| `STORE_PUBLIC_URL` | e.g. `https://store.dev.piwalletsv.com` |
| `DOCS_SUCCESS_URL` | Stripe success redirect |
| `DOCS_CANCEL_URL` | Stripe cancel redirect |
| `DOCS_BSV_PENDING_URL` | BSV instructions page base URL |
| `ALLOWED_ORIGIN` | CORS origin (docs site) |

## Catalog

Edit [`catalog/products.dev.json`](catalog/products.dev.json) with real Stripe **test** Price IDs from the Dashboard.

## Lambda package

From repo root:

```bash
pip install -r store/requirements.txt -t /tmp/store-lambda
cp -r store /tmp/store-lambda/
cp store/handler.py /tmp/store-lambda/handler.py
cd /tmp/store-lambda && zip -r ../store-lambda.zip .
```

Handler: `store.handler.lambda_handler`

Package for Lambda (Linux x86_64 wheels — run on any dev machine):

```bash
../piwalletsv-infra/scripts/package-store-lambda.sh "$(pwd)/store" /tmp/store-lambda.zip
```

Terraform in `piwalletsv-infra` builds this zip automatically on apply.

## Tests

```bash
pip install -e ".[dev]"
pytest tests/test_store_api.py -v
```

## Operator setup (dev)

See [`store/OPERATOR.md`](OPERATOR.md) for Stripe Dashboard, DNS, ACM, and SSM steps after `terraform apply`.
