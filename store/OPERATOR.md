# Dev store — operator checklist

Complete these steps after deploying the `store-dev` Terraform stack.

## 1. ACM cert SAN (if new)

Adding `store.dev.piwalletsv.com` to the shared cert forces a rotation:

```bash
cd piwalletsv-infra
terraform apply   # with enable_acm_validation_wait = false first if needed
terraform output acm_validation_records
```

Publish any **new** validation CNAMEs at Namecheap. When they resolve:

```bash
# terraform.tfvars: enable_acm_validation_wait = true
terraform apply
```

## 2. DNS

```bash
terraform output store_dev_api_domain_name
```

Create CNAME: `store.dev.piwalletsv.com` → value from output.

## 3. SSM parameters (Terraform creates placeholders)

In AWS Console → Systems Manager → Parameter Store (us-east-1), set **SecureString** values:

| Parameter | Value |
|-----------|--------|
| `/piwalletsv/store/dev/stripe_secret_key` | `sk_test_…` |
| `/piwalletsv/store/dev/stripe_webhook_secret` | `whsec_…` |
| `/piwalletsv/store/dev/admin_api_key` | random secret for mark-paid |
| `/piwalletsv/store/dev/bsv_receive_address` | your BSV receive address |

Re-run `terraform apply` or update Lambda env if parameters change outside Terraform.

## 4. Stripe Dashboard (test mode)

1. **Products** — Full kit + Case only; note **Price IDs**.
2. Update [`PiWallet/store/catalog/products.dev.json`](../PiWallet/store/catalog/products.dev.json) with test Price IDs; redeploy Lambda zip.
3. **Developers → Webhooks** — endpoint:
   `https://store.dev.piwalletsv.com/v1/webhooks/stripe`
   Events: `checkout.session.completed`
4. Copy signing secret → SSM `stripe_webhook_secret`.

## 5. Publish docs (dev)

From `piwalletsv-infra`:

```bash
./scripts/publish.sh site --env dev
```

Or from PiWallet:

```bash
./publish.sh docs --env dev
```

## 6. End-to-end tests

**Card:** Purchase page → Buy with card → Stripe test card `4242 4242 4242 4242` → success page. Order status should become `paid` (fulfillment disabled on dev).

**BSV:** Pay with BSV → pending page → confirm payment manually → mark paid:

```bash
curl -X POST "https://store.dev.piwalletsv.com/v1/admin/orders/{ORDER_ID}/mark-paid" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: YOUR_ADMIN_KEY" \
  -d '{"txid":"optional-memo"}'
```

Verify order `GET /v1/orders/{id}` returns `"status":"paid"` and no shipment was created (`FULFILLMENT_ENABLED=false`).
