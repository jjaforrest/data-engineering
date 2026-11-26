# API Deployment Runbook

## Variables
```bash
export RG_NAME="rg-de-path-engineer"
export LOCATION="eastus"
export VAULT_NAME="kv-de-path-2fee01e0"
export SECRET_NAME="paysim-api-key"
export SECRET_VALUE=$(openssl rand -base64 32)
export GH_USER="jjaforrest"
export ENV_NAME="cae-paysim-mock"
export APP_NAME="ca-paysim-api"
export CURRENT_USER_ID=$(az ad signed-in-user show --query id -o tsv)
export SUBSCRIPTION_ID=$(az account show --query id -o tsv)
export IMAGE_TAG="v1"
```

## Resource Group and Key Vault (Initial Setup Only)
```bash
az group create --name "$RG_NAME" --location "$LOCATION" --tags project=de-path

az keyvault create \
  --name "$VAULT_NAME" \
  --resource-group "$RG_NAME" \
  --location "$LOCATION" \
  --enable-rbac-authorization true

az role assignment create \
  --role "Key Vault Secrets Officer" \
  --assignee "$CURRENT_USER_ID" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_NAME/providers/Microsoft.KeyVault/vaults/$VAULT_NAME"

az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee "$CURRENT_USER_ID" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_NAME/providers/Microsoft.KeyVault/vaults/$VAULT_NAME"

az keyvault secret set \
--vault-name "$VAULT_NAME" \
--name "$SECRET_NAME" \
--value "$SECRET_VALUE"
```
### Verify Resource Group, Key Vault, & Roles
```bash
echo "Resource Group: " 
az group list --output table

echo "Using Key Vault Name: " $VAULT_NAME

KV_ID=$(az keyvault show --name "$VAULT_NAME" --resource-group "$RG_NAME" --query id -o tsv)

az role assignment list \
  --scope "$KV_ID" \
  --query "[].{Principal:principalName, Type:principalType, Role:roleDefinitionName}" \
  -o table

```

## Build `linux/amd64` Image and Verify Locally
```bash
podman build --platform linux/amd64 -t localhost/paysim-api:amd64 .
podman run -d --name paysim-test -p 8000:8000 localhost/paysim-api:amd64
curl -sI -H "X-API-Key: dev-processor-key" -H "Accept-Encoding: gzip" \
  "[http://127.0.0.1:8000/v1/transactions?page=1&pageSize=10](http://127.0.0.1:8000/v1/transactions?page=1&pageSize=10)"
podman rm -f paysim-test
```

## Push Image to GHCR
Ensure the GHCR package visibility is set to Public.

```bash
echo "$GH_TOKEN" | podman login ghcr.io -u "$GH_USER" --password-stdin
podman tag localhost/paysim-api:amd64 "ghcr.io/${GH_USER}/paysim-api:${IMAGE_TAG}"
podman push "ghcr.io/${GH_USER}/paysim-api:${IMAGE_TAG}"
```

## Register Provider & Create Container Apps Environment
Note: Keep `cae-paysim-mock` intact when recreating the app so the generated FQDN stays unchanged. Using `--logs-destination none` avoids Log Analytics ingestion costs; rely on live `az containerapp logs show` for debugging.

```bash
az provider register --namespace Microsoft.App --wait
az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RG_NAME" \
  --location "$LOCATION" \
  --logs-destination none
```

## Deploy Container App (Consumption Plan, Scale-to-Zero)
```bash
API_KEY_SECRET=$(az keyvault secret show \
  --vault-name "$VAULT_NAME" \
  --name "$SECRET_NAME" \
  --query value -o tsv)

az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --environment "$ENV_NAME" \
  --image "ghcr.io/${GH_USER}/paysim-api:${IMAGE_TAG}" \
  --target-port 8000 \
  --ingress external \
  --cpu 0.5 \
  --memory 1.0Gi \
  --min-replicas 0 \
  --max-replicas 1 \
  --secrets "paysim-api-key=${API_KEY_SECRET}" \
  --env-vars "MOCK_API_KEY=secretref:paysim-api-key" "FAULT_SEED=42"

unset API_KEY_SECRET
```

## Public HTTPS URL (for DDR-GA Addendum)
Verify live FDQN after creation:
```bash
export API_URL="https://$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --query properties.configuration.ingress.fqdn -o tsv)"
echo "$API_URL"
```

- Base URL: https://ca-paysim-api.kindsand-c066c1cc.eastus.azurecontainerapps.io
- Container Apps Environment: cae-paysim-mock
- Container App Name: ca-paysim-api
- Fault Seed: 42

## Smoke Test
```bash
PYTHONPATH=. \
API_URL="$API_URL" \
MOCK_API_KEY=$(az keyvault secret show --vault-name "$VAULT_NAME" --name "$SECRET_NAME" --query value -o tsv) \
python3 setup/smoke_test_api.py
```

## Day-2 Operations (Rebuild, Image Rollout, Secret Rotation, Logs)

### Delete and Recreate Only the Container App
Deletes the app without destroying `cae-paysim-mock` (preserves the URL):
```bash
az containerapp delete \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --yes
```

Re-run section 5-7 to restore service.

### Deploy a New Image Tag
After push new tag (e.g., `export IMAGE_TAG="v2"` in Section 3):
```bash
az containerapp update \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --image "ghcr.io/${GH_USER}/paysim-api:${IMAGE_TAG}"
```

### Rotate Key Vault Secret & Restart Revision
Because the secret is injected as a literal Container Apps secret (Not a Managed Identity Key Vault reference), updating Key Vault alone will not update the running container:
```bash
# 1. Store the new secret version in Key Vault
az keyvault secret set \
  --vault-name "$VAULT_NAME" \
  --name "$SECRET_NAME" \
  --value "<new-generated-api-key>"

# 2. Pull the new value and update the Container Apps secret
API_KEY_SECRET=$(az keyvault secret show \
  --vault-name "$VAULT_NAME" \
  --name "$SECRET_NAME" \
  --query value -o tsv)

az containerapp secret set \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --secrets "paysim-api-key=${API_KEY_SECRET}"

unset API_KEY_SECRET

# 3. Restart the active revision so existing/scaled replicas load the new secret
ACTIVE_REV=$(az containerapp revision list \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --query "[?properties.active].name | [0]" -o tsv)

az containerapp revision restart \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --revision "$ACTIVE_REV"
  ```

  Re-run Smoke Test to verify new key works and the old key is rejected.

  ### Inspect Revisions & Stream Logs

  ```bash
  # Check revision health and traffic split
az containerapp revision list \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  -o table

# Stream live container stdout/stderr (required since --logs-destination is none)
az containerapp logs show \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --follow
```
