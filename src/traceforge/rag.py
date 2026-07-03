"""Grounded question answering with an evidence gate and clearance enforcement.

Retrieval restricts candidates to the caller's clearance; the evidence gate refuses when the
distinctive terms of the question are not actually present in the retrieved (allowed) context,
so the system never fabricates a compliance claim — and never answers from content the caller
is not cleared to see. Synthesis uses Azure OpenAI when configured, else a deterministic
extractive answer built from the retrieved requirements.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import ingest
from .models import Classification
from .retrieve import Doc, HybridIndex

_STOP = {
    "the", "a", "an", "of", "for", "to", "and", "or", "with", "in", "on", "at", "is",
    "are", "what", "which", "how", "does", "do", "shall", "system", "requirement",
    "requirements", "have", "has", "that", "this", "there", "any", "all", "no",
}
_GATE_THRESHOLD = 0.3
_REFUSAL = (
    "I don't have grounded evidence at your clearance level to answer that. "
    "No accessible requirement covers it."
)


@dataclass
class RagResult:
    answer: str
    citations: list[str] = field(default_factory=list)
    contexts: list[dict] = field(default_factory=list)
    refused: bool = False
    backend: str = "local-hash"


def _distinctive(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 3}


def build_docs(bronze: str) -> list[Doc]:
    reqs, tests, _ = ingest.load_bronze(bronze)
    docs = [
        Doc(id=r.requirement_id, text=r.text, classification=r.classification, kind="requirement",
            meta={"section": r.section, "verification": r.verification_method})
        for r in reqs
    ]
    docs += [
        Doc(id=t.test_id, text=f"{t.title} (verifies {', '.join(t.covers)})",
            classification=t.classification, kind="test", meta={"status": t.status})
        for t in tests
    ]
    return docs


class Rag:
    def __init__(self, bronze: str) -> None:
        self.index = HybridIndex().build(build_docs(bronze))

    def answer(self, question: str, clearance: Classification, k: int = 5) -> RagResult:
        hits = self.index.search(question, clearance, k=k)
        backend = self.index.backend
        if not hits:
            return RagResult(answer=_REFUSAL, refused=True, backend=backend)

        # Evidence gate: how many distinctive question terms appear in the retrieved context?
        q_terms = _distinctive(question)
        context_text = " ".join(h.doc.text for h in hits).lower()
        covered = sum(1 for t in q_terms if t in context_text)
        coverage = covered / len(q_terms) if q_terms else 0.0
        if coverage < _GATE_THRESHOLD:
            return RagResult(answer=_REFUSAL, refused=True, backend=backend,
                             contexts=[_ctx(h) for h in hits])

        contexts = [_ctx(h) for h in hits]
        answer = self._synthesize(question, hits)
        # Cite only requirements that actually share a distinctive term with the question.
        relevant = [
            h.doc.id for h in hits
            if h.doc.kind == "requirement" and _distinctive(h.doc.text) & q_terms
        ]
        citations = relevant[:4] or [hits[0].doc.id]
        return RagResult(answer=answer, citations=citations, contexts=contexts, backend=backend)

    def _synthesize(self, question: str, hits) -> str:  # noqa: ANN001
        if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
            try:
                return self._synthesize_azure(question, hits)
            except Exception:  # noqa: BLE001 — fall back to extractive on any Azure error
                pass
        top = [h for h in hits if h.doc.kind == "requirement"][:2] or hits[:1]
        return " ".join(f"[{h.doc.id}] {h.doc.text}" for h in top)

    def _synthesize_azure(self, question: str, hits) -> str:  # noqa: ANN001
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01"),
        )
        context = "\n".join(f"[{h.doc.id}] {h.doc.text}" for h in hits)
        msg = [
            {"role": "system", "content": (
                "You answer questions about system requirements using ONLY the provided context. "
                "Cite requirement IDs in brackets. If the context does not contain the answer, say "
                "you cannot answer from the available requirements. Never invent requirements.")},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ]
        resp = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o"),
            messages=msg, temperature=0,
        )
        return resp.choices[0].message.content.strip()


def _ctx(hit) -> dict:  # noqa: ANN001
    return {"id": hit.doc.id, "kind": hit.doc.kind,
            "classification": hit.doc.classification.name, "score": round(hit.score, 4)}


# Module-level convenience used by the CLI.
def answer(question: str, clearance: Classification, bronze: str) -> RagResult:
    return Rag(bronze).answer(question, clearance)
