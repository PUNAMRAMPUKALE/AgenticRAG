from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.domain.models import Chunk
from app.infrastructure.llm.embeddings import OpenAIEmbeddings, get_embedder


class SparseIndex:
    def __init__(self, chunks: list[Chunk], embedder: OpenAIEmbeddings | None = None):
        self.chunks = chunks
        self._embedder = embedder
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._matrix = None
        self._dense: np.ndarray | None = None
        if chunks:
            self._matrix = self._vectorizer.fit_transform(c.text for c in chunks)
            if embedder is not None:
                self._dense = embedder.embed([c.text for c in chunks])

    def search(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        if not query.strip() or not self.chunks:
            return []
        if self._dense is not None and self._embedder is not None:
            q = self._embedder.embed([query])
            dense_scores = (self._dense @ q[0]).ravel()
            if self._matrix is not None:
                sparse_scores = cosine_similarity(self._vectorizer.transform([query]), self._matrix).ravel()
                sparse_scores = _minmax(sparse_scores)
                dense_scores = _minmax(dense_scores)
                scores = 0.7 * dense_scores + 0.3 * sparse_scores
            else:
                scores = dense_scores
        elif self._matrix is not None:
            scores = cosine_similarity(self._vectorizer.transform([query]), self._matrix).ravel()
        else:
            return []
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        hits: list[tuple[Chunk, float]] = []
        for idx, score in ranked[:k]:
            if score <= 0:
                continue
            hits.append((self.chunks[idx], float(score)))
        return hits

    def format_for_agent(self, hits: list[tuple[Chunk, float]]) -> str:
        if not hits:
            return "No relevant documents found."
        parts = []
        for chunk, score in hits:
            parts.append(
                f"# Document ID: {chunk.file_id}\n"
                f"# Title: {chunk.title}\n"
                f"# As-of: {chunk.as_of}\n"
                f"# Section: {chunk.section or '-'}\n"
                f"# Page: {chunk.page or '-'}\n"
                f"# Score: {score:.3f}\n\n{chunk.text}"
            )
        return "\n\n---\n\n".join(parts)


def build_index(chunks: list[Chunk]) -> SparseIndex:
    return SparseIndex(chunks, embedder=get_embedder())


def _minmax(values: np.ndarray) -> np.ndarray:
    lo = float(values.min()) if values.size else 0.0
    hi = float(values.max()) if values.size else 1.0
    if hi - lo < 1e-9:
        return np.zeros_like(values)
    return (values - lo) / (hi - lo)
