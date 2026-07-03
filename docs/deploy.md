# Deploying TraceForge

TraceForge is a single FastAPI process — dashboard, Q&A API, and traceability engine in one
image. It runs **fully offline by default** (deterministic engine, no external calls) and switches
to Azure OpenAI for RAG synthesis the moment you provide the Azure environment variables. Nothing
about the image changes between the two modes.

## Run locally with Docker

```bash
docker build -t traceforge .
docker run -p 8000:8000 traceforge
# → dashboard at http://localhost:8000/ , Swagger at /docs
```

## Deploy to Azure Container Apps

Target region is `swedencentral`. The deploy script builds the image in Azure Container Registry
(no local Docker required) and publishes a public HTTPS endpoint.

```bash
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App

./deploy/azure.sh          # override with e.g. RG=… LOCATION=… APP=…
```

The script prints the live URL on completion:

```
✅ TraceForge is live: https://traceforge.<hash>.swedencentral.azurecontainerapps.io/
```

## Enable Azure OpenAI (optional)

The demo is complete without it, but wiring Azure OpenAI makes `search_requirements` / `/ask`
synthesize with `gpt-4o` instead of the extractive fallback. Store the key as a Container Apps
secret and set the endpoint/deployment as env vars (commands are printed at the end of the deploy
script, and the full variable list is in `.env.example`). The evidence gate and clearance
enforcement are identical in both modes — Azure only changes how the final answer is phrased.

## What ships in the image

- The Python package (with the `azure` extra) and the static dashboard (via package-data).
- The **bronze** TRUS dataset. Silver/gold lake artifacts are regenerated in-process on first
  request, so the container is stateless and needs no volume.

## Architecture note

In production the same code paths point at managed services instead of local stand-ins: Azure
Blob for bronze, Azure AI Search for the gold retrieval index, Azure OpenAI for embeddings and
synthesis (see the table in `README.md`). Container Apps gives autoscaling and HTTPS ingress; the
app is stateless, so scaling out is safe.
