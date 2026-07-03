# TraceForge — single-image deploy (API + dashboard + MCP-ready).
# The whole app is one FastAPI process serving the compliance dashboard, the Q&A API, and
# the traceability engine. Runs offline by default; set the Azure OpenAI vars (see .env.example)
# to switch RAG synthesis to Azure OpenAI without changing the image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TRACEFORGE_BRONZE=data/bronze/trus

# Non-root runtime user. Hugging Face Spaces runs the container as UID 1000, and it's good
# practice everywhere. We install as root (system site-packages, world-readable) then drop
# privileges for the running process; the serving path never writes to disk.
RUN useradd -m -u 1000 user

WORKDIR /app

# Install the package (with the Azure extra so Azure OpenAI works when configured).
# Static dashboard assets ship via package-data; the bronze dataset is copied below.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[azure]"

# Bronze source only — silver/gold lake artifacts are regenerated in-process at first request.
COPY data/bronze ./data/bronze

USER user

# Hosts inject PORT (Container Apps) or route to app_port (HF Spaces); default 8000 for local run.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn traceforge.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
