#!/usr/bin/env bash
set -euo pipefail

# Configuration (override via environment variables for practice/staging runs)
RG_NAME="${RG_NAME:-rg-api-prod}"
LOCATION="${LOCATION:-eastus}"
KV_NAME="${KV_NAME:-kv-api-prod-001}"
ENV_NAME="${ENV_NAME:-cae-api-prod}"
APP_NAME="${APP_NAME:-ca-api-prod}"
IMAGE="${IMAGE:-mcr.microsoft.com/azuredocs/containerapps-helloworld:latest}"
SECRET_NAME="api-key"
SECRET_VALUE="${API_SECRET_VALUE:?Error: Set API_SECRET_VALUE before running}"

echo "==> 1. Creating Resource Group: $RG_NAME"
az group create \
  --name "$RG_NAME" \
  --location "$LOCATION" \
  --output none

echo "==> 2. Creating Key Vault: $KV_NAME"
# Check if a soft-deleted vault with this name exists and recover it, or create fresh
if az keyvault show-deleted --name "$KV_NAME" &>/dev/null; then
  echo "    Recovering soft-deleted Key Vault $KV_NAME..."
  az keyvault recover --name "$KV_NAME" --output none
else
  az keyvault create \
    --name "$KV_NAME" \
    --resource-group "$RG_NAME" \
    --location "$LOCATION" \
    --enable-rbac-authorization false \
    --output none
fi

echo "==> 3. Setting Secret in Key Vault"
# Only update the secret version if the value actually changed (strict idempotency)
CURRENT_VAL=$(az keyvault secret show --vault-name "$KV_NAME" --name "$SECRET_NAME" --query "value" -o tsv 2>/dev/null || echo "")
if [[ "$CURRENT_VAL" != "$SECRET_VALUE" ]]; then
  az keyvault secret set \
    --vault-name "$KV_NAME" \
    --name "$SECRET_NAME" \
    --value "$SECRET_VALUE" \
    --output none
else
  echo "    Secret '$SECRET_NAME' unchanged; skipping new version."
fi

echo "==> 4. Creating Container Apps Environment: $ENV_NAME"
az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RG_NAME" \
  --location "$LOCATION" \
  --output none

echo "==> 5. Deploying Container App: $APP_NAME"
az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --environment "$ENV_NAME" \
  --image "$IMAGE" \
  --target-port 80 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 1 \
  --output none

FQDN=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --query "properties.configuration.ingress.fqdn" \
  -o tsv)

echo "Deployment complete. Endpoint: https://$FQDN"