#!/usr/bin/env bash
# Deploy the tide-alerts Worker and apply the D1 schema, using the Cloudflare API token.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ~/.config/kitchen-magpie/cloudflare.env; set +a
export CLOUDFLARE_ACCOUNT_ID=f400124b466f991834ee7f05e61ae247
npx -y wrangler@4 d1 execute tide-alerts --remote --file schema.sql
npx -y wrangler@4 deploy
