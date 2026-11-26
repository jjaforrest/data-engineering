#!/usr/bin/env bash
set -euo pipefail

# Ensure we run relative to the repository root (parent of setup/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="${SCRIPT_DIR}/deploy_api.sh"
TEARDOWN_SCRIPT="${SCRIPT_DIR}/teardown_api.sh"

# Verify helper scripts exist
if [[ ! -f "$DEPLOY_SCRIPT" || ! -f "$TEARDOWN_SCRIPT" ]]; then
  echo "Error: deploy_api.sh and teardown_api.sh must exist in $SCRIPT_DIR" >&2
  exit 1
fi

chmod +x "$DEPLOY_SCRIPT" "$TEARDOWN_SCRIPT"

# Isolated practice variables (Key Vault names must be globally unique)
export RG_NAME="${RG_NAME:-rg-api-practice}"
export LOCATION="${LOCATION:-eastus}"
export KV_NAME="${KV_NAME:-kv-api-prac-$RANDOM}"
export ENV_NAME="${ENV_NAME:-cae-api-practice}"
export APP_NAME="${APP_NAME:-ca-api-practice}"
export API_SECRET_VALUE="${API_SECRET_VALUE:-practice-secret-123}"

# Ensure practice resources are always cleaned up, even if a step or smoke test fails
cleanup() {
  echo ""
  echo "==> [Cleanup] Running final teardown on $RG_NAME..."
  "$TEARDOWN_SCRIPT"
}
trap cleanup EXIT

echo "============================================================"
echo "Starting End-to-End Practice Verification"
echo "Resource Group: $RG_NAME | Key Vault: $KV_NAME"
echo "============================================================"

echo ""
echo "==> [Step 1/4] First deploy (creates everything from scratch)"
"$DEPLOY_SCRIPT"

echo ""
echo "==> [Step 2/4] Second deploy (verifies idempotency - changes nothing)"
"$DEPLOY_SCRIPT"

echo ""
echo "==> [Step 3/4] Teardown (destroys RG and handles Key Vault soft-delete)"
"$TEARDOWN_SCRIPT"

echo ""
echo "==> [Step 4/4] Rebuild from zero and run smoke test"
"$DEPLOY_SCRIPT"

REBUILT_URL=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --query "properties.configuration.ingress.fqdn" \
  -o tsv)

echo "Running smoke test against https://${REBUILT_URL}/ ..."
# Retry up to 6 times (30s) in case the container is still warming up
for i in {1..6}; do
  if curl --fail --silent --show-error "https://${REBUILT_URL}/" > /dev/null; then
    echo "Smoke test PASSED on https://${REBUILT_URL}"
    exit 0
  fi
  echo "    Attempt $i/6 failed; waiting 5s for container readiness..."
  sleep 5
done

echo "Error: Smoke test FAILED on https://${REBUILT_URL}" >&2
exit 1