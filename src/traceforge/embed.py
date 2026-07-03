"""Embedding provider with an Azure-first, offline-fallback design.

If ``AZURE_OPENAI_*`` is configured, embeddings come from Azure OpenAI
(``text-embedding-3-large``). Otherwise a deterministic hashed bag-of-words embedder is used
so retrieval, the API and CI all run offline with zero external calls. Both return unit-norm
vectors, so downstream cosine similarity is identical.
"""

from __future__ import annotations

import hashlib
import math
import os
import re

_DIM = 256


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _hash_embed(text: str) -> list[float]:
    vec = [0.0] * _DIM
    for tok in _tokens(text):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        idx = h % _DIM
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class Embedder:
    """Chooses Azure OpenAI when configured, else the deterministic local embedder."""

    def __init__(self) -> None:
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.deployment = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-large")
        self.use_azure = bool(self.endpoint and self.api_key)
        self._client = None

    @property
    def backend(self) -> str:
        return "azure-openai" if self.use_azure else "local-hash"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.use_azure:
            return [_hash_embed(t) for t in texts]
        return self._embed_azure(texts)

    def _embed_azure(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            from openai import AzureOpenAI  # imported lazily; optional dependency

            self._client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01"),
            )
        resp = self._client.embeddings.create(model=self.deployment, input=texts)
        return [d.embedding for d in resp.data]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # inputs are unit-norm
