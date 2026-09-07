from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.domain.models import Chunk


class SparseIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._matrix = self._vectorizer.fit_transform(c.text for c in chunks)

    def search(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        if not query.strip():
            return []
        q = self._vectorizer.transform([query])
        scores = cosine_similarity(q, self._matrix).ravel()
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
                f"# Score: {score:.3f}\n\n{chunk.text}"
            )
        return "\n\n---\n\n".join(parts)
