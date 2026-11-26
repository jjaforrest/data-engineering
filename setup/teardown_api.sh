#!/usr/bin/env bash
set -euo pipefail

RG_NAME="${RG_NAME:-rg-api-prod}"
LOCATION="${LOCATION:-eastus}"
KV_NAME="${KV_NAME:-kv-api-prod-001}"

echo "==> 1. Deleting Resource Group: $RG_NAME (asynchronous)"
if az group exists --name "$RG_NAME" | grep -q "true"; then
  az group delete \
    --name "$RG_NAME" \
    --yes \
    --no-wait
  echo "    Deletion triggered in background."
else
  echo "    Resource group $RG_NAME does not exist."
fi

echo "==> 2. Handling Key Vault Soft-Delete: $KV_NAME"
# Note: If the RG is still deleting asynchronously, the vault won't appear in
# 'show-deleted' for ~30-60 seconds. Wait briefly if the vault still exists.
for i in {1..12}; do
  if az keyvault show-deleted --name "$KV_NAME" &>/dev/null; then
    break
  fi
  sleep 5
done

if az keyvault show-deleted --name "$KV_NAME" &>/dev/null; then
  PURGE_PROTECTED=$(az keyvault show-deleted --name "$KV_NAME" --query "properties.purgeProtectionEnabled" -o tsv)
  if [[ "$PURGE_PROTECTED" == "true" ]]; then
    echo "    NOTE: Purge protection is enabled on $KV_NAME. It will auto-expire after its retention period."
  else
    echo "    Purging soft-deleted Key Vault $KV_NAME..."
    az keyvault purge --name "$KV_NAME" --location "$LOCATION" --no-wait
  fi
else
  echo "    Key Vault $KV_NAME not yet in soft-deleted state (RG deletion still in progress)."
fi

echo "Teardown complete."