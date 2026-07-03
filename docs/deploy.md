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

## Deploy to Hugging Face Spaces (no Azure account needed)

The same Docker image runs as a **Docker Space** — a free public HTTPS demo. The Space metadata
lives in the YAML frontmatter of `README.md` (`sdk: docker`, `app_port: 8000`), and the container
runs as UID 1000 as HF requires.

1. Create a Space at <https://huggingface.co/new-space> — **SDK: Docker**, name `traceforge`,
   visibility Public.
2. Add the Space as a git remote and push (HF builds the Dockerfile automatically):

   ```bash
   git remote add hf https://huggingface.co/spaces/<your-hf-username>/traceforge
   git push hf main
   ```

   Authenticate with a Hugging Face access token (Settings → Access Tokens, write scope) when git
   prompts, or use `huggingface-cli login` first.
3. Watch the build in the Space's **Logs** tab. When it finishes, the dashboard is live at
   `https://<your-hf-username>-traceforge.hf.space/`.

Runs fully offline on the free CPU tier — no Azure required. To enable Azure OpenAI synthesis on
the Space, add the `AZURE_OPENAI_*` values as **Secrets** in the Space settings (same variable
names as below).

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
