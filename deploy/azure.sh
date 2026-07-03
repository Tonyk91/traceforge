#!/usr/bin/env bash
# Deploy TraceForge to Azure Container Apps from the local Dockerfile.
#
# Prereqs: `az login` (Azure CLI) and the containerapp extension
#   az extension add --name containerapp --upgrade
#   az provider register --namespace Microsoft.App
#
# One command builds the image (ACR build, no local Docker needed), pushes it, and deploys a
# public HTTPS endpoint. Override any setting via env vars, e.g. `LOCATION=westeurope ./azure.sh`.
set -euo pipefail

RG=${RG:-traceforge-rg}
LOCATION=${LOCATION:-swedencentral}      # Swedish region — appropriate for the target dataset
ENVIRONMENT=${ENVIRONMENT:-traceforge-env}
APP=${APP:-traceforge}

cd "$(dirname "$0")/.."

echo "▶ Resource group $RG ($LOCATION)"
az group create -n "$RG" -l "$LOCATION" -o none

echo "▶ Building image in ACR and deploying to Container Apps (this takes a few minutes)…"
az containerapp up \
  --name "$APP" \
  --resource-group "$RG" \
  --location "$LOCATION" \
  --environment "$ENVIRONMENT" \
  --source . \
  --ingress external \
  --target-port 8000

FQDN=$(az containerapp show -n "$APP" -g "$RG" \
  --query properties.configuration.ingress.fqdn -o tsv)
echo ""
echo "✅ TraceForge is live: https://${FQDN}/"
echo "   Dashboard  https://${FQDN}/"
echo "   Swagger    https://${FQDN}/docs"

cat <<'NOTE'

── Optional: enable Azure OpenAI for RAG synthesis ──────────────────────────
Runs fully offline (deterministic extractive answers) until you wire Azure OpenAI:

  az containerapp secret set -n traceforge -g traceforge-rg \
    --secrets openai-key="$AZURE_OPENAI_API_KEY"

  az containerapp update -n traceforge -g traceforge-rg \
    --set-env-vars \
      AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
      AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o \
      AZURE_OPENAI_API_VERSION=2024-06-01 \
      AZURE_OPENAI_API_KEY=secretref:openai-key
NOTE
