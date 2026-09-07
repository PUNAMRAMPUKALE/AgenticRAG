from __future__ import annotations

import logging

import numpy as np

from app.infrastructure.llm.embeddings import OpenAIEmbeddings
from app.infrastructure.retrieval.chunking import (
    CHUNK_SIZE,
    MIN_CHUNK_CHARS,
    TextUnit,
    recursive_split,
    split_prose_units,
)

log = logging.getLogger(__name__)

# LangChain SemanticChunker: split when similarity is 1 SD below the mean of this document.
BREAKPOINT_STD = 1.0


def semantic_merge(units: list[TextUnit], embedder: OpenAIEmbeddings) -> list[TextUnit]:
    """Group consecutive units while they stay on-topic; cut on a std-dev drop or size cap."""
    kept = [u for u in units if len(u.text.strip()) >= 12]
    if len(kept) <= 1:
        return kept
    embeddings = embedder.embed([u.text for u in kept])
    if embeddings.shape[0] < 2:
        return kept
    sims = [
        float(np.dot(embeddings[i], embeddings[i + 1]))
        for i in range(len(kept) - 1)
    ]
    mean = float(np.mean(sims))
    std = float(np.std(sims))
    threshold = mean - BREAKPOINT_STD * std
    log.debug("Semantic breakpoints: mean=%.3f std=%.3f threshold=%.3f", mean, std, threshold)

    groups: list[TextUnit] = []
    buf = kept[0].text
    pages = _pages(kept[0])
    for i, nxt in enumerate(kept[1:], start=0):
        sim = sims[i]
        candidate = f"{buf}\n\n{nxt.text}"
        topic_break = sim < threshold
        too_big = len(candidate) > CHUNK_SIZE
        if topic_break or too_big:
            if len(buf) >= MIN_CHUNK_CHARS:
                groups.append(TextUnit(text=buf, page=_page_span(pages)))
            elif groups:
                groups[-1] = TextUnit(text=groups[-1].text + "\n\n" + buf, page=groups[-1].page)
            else:
                groups.append(TextUnit(text=buf, page=_page_span(pages)))
            buf = nxt.text
            pages = _pages(nxt)
            continue
        buf = candidate
        pages |= _pages(nxt)
    if buf.strip():
        groups.append(TextUnit(text=buf, page=_page_span(pages)))

    out: list[TextUnit] = []
    for group in groups:
        if len(group.text) <= CHUNK_SIZE:
            out.append(group)
            continue
        for piece in recursive_split(group.text):
            out.append(TextUnit(text=piece, page=group.page))
    return out


def semantic_pdf_units(pages: list[tuple[int, str]], embedder: OpenAIEmbeddings) -> list[TextUnit]:
    units: list[TextUnit] = []
    for page_no, text in pages:
        for part in split_prose_units(text):
            units.append(TextUnit(text=part, page=str(page_no)))
    return semantic_merge(units, embedder)


def semantic_section_units(body: str, embedder: OpenAIEmbeddings) -> list[str]:
    units = [TextUnit(text=part) for part in split_prose_units(body)]
    return [u.text for u in semantic_merge(units, embedder)]


def _pages(unit: TextUnit) -> set[str]:
    return {unit.page} if unit.page else set()


def _page_span(pages: set[str]) -> str:
    nums: list[int] = []
    for page in pages:
        try:
            nums.append(int(page))
        except ValueError:
            return ",".join(sorted(p for p in pages if p))
    if not nums:
        return ""
    nums = sorted(set(nums))
    if nums[0] == nums[-1]:
        return str(nums[0])
    return f"{nums[0]}-{nums[-1]}"
