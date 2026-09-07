from __future__ import annotations

import logging
import time

import httpx
import numpy as np

from app.core.config import get_settings

log = logging.getLogger(__name__)


class OpenAIEmbeddings:
    """One model for semantic chunk splits and query vectors (do not mix models)."""

    def __init__(self) -> None:
        settings = get_settings()
        self._key = (settings.llm_api_key or "").strip()
        self._base = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        self._model = (settings.openai_embedding_model or "text-embedding-3-small").strip()
        self._batch = 64

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    @property
    def model(self) -> str:
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            batch = [t if t.strip() else " " for t in texts[start : start + self._batch]]
            vectors.extend(self._request(batch))
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-12)
        return matrix / norms

    def _request(self, batch: list[str]) -> list[list[float]]:
        url = f"{self._base}/embeddings"
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        payload = {"model": self._model, "input": batch}
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = httpx.post(url, headers=headers, json=payload, timeout=60.0)
                if response.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                data = response.json()["data"]
                data.sort(key=lambda row: row["index"])
                return [row["embedding"] for row in data]
            except Exception as exc:
                last_error = exc
                time.sleep(2 ** attempt)
        raise RuntimeError("OpenAI embeddings failed") from last_error


def get_embedder() -> OpenAIEmbeddings | None:
    client = OpenAIEmbeddings()
    if not client.enabled:
        return None
    return client
