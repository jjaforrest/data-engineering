# API Deployment Runbook

## Variables
```bash
export RG_NAME="rg-de-path-engineer"
export LOCATION="eastus"
export VAULT_NAME="<your-unique-keyvault-name>"
export SECRET_NAME="paysim-api-key"
```

## Resource Group and Key Vault
1. Create the resource group with required tags:
   ```bash
   az group create --name "$RG_NAME" --location "$LOCATION" --tags project=de-path
   ```
