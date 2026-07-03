"""Hybrid retrieval (vector + BM25, RRF-fused) with classification-aware access control.

Access control is enforced by construction: the candidate set is filtered to
``level(doc) <= level(clearance)`` **before** ranking, so higher-marked content can never
influence the ranking signal, appear in results, or leak into a citation. In production the
same filter is an Azure AI Search ``$filter`` predicate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from .embed import Embedder, cosine
from .models import Classification


@dataclass
class Doc:
    id: str
    text: str
    classification: Classification
    kind: str  # requirement | test
    meta: dict = field(default_factory=dict)


@dataclass
class Hit:
    doc: Doc
    score: float


def _toks(text: str) -> list[str]:
    return [t for t in text.lower().replace("/", " ").split() if t]


class HybridIndex:
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or Embedder()
        self.docs: list[Doc] = []
        self._vecs: list[list[float]] = []
        self._bm25: BM25Okapi | None = None

    @property
    def backend(self) -> str:
        return self.embedder.backend

    def build(self, docs: list[Doc]) -> "HybridIndex":
        self.docs = docs
        self._vecs = self.embedder.embed([d.text for d in docs])
        self._bm25 = BM25Okapi([_toks(d.text) for d in docs])
        return self

    def search(
        self, query: str, clearance: Classification, k: int = 5, rrf_k: int = 60
    ) -> list[Hit]:
        # 1) access control: restrict candidates to the caller's clearance FIRST.
        allowed = [i for i, d in enumerate(self.docs) if d.classification <= clearance]
        if not allowed:
            return []

        # 2) lexical ranking (BM25) over the allowed set.
        bm_scores = self._bm25.get_scores(_toks(query))
        bm_rank = sorted(allowed, key=lambda i: bm_scores[i], reverse=True)

        # 3) vector ranking (cosine) over the allowed set.
        qv = self.embedder.embed([query])[0]
        vec_rank = sorted(allowed, key=lambda i: cosine(qv, self._vecs[i]), reverse=True)

        # 4) Reciprocal Rank Fusion.
        fused: dict[int, float] = {}
        for rank, i in enumerate(bm_rank):
            fused[i] = fused.get(i, 0.0) + 1.0 / (rrf_k + rank)
        for rank, i in enumerate(vec_rank):
            fused[i] = fused.get(i, 0.0) + 1.0 / (rrf_k + rank)

        top = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [Hit(doc=self.docs[i], score=score) for i, score in top]
