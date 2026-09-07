from __future__ import annotations

import re
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.domain.models import Chunk
from app.infrastructure.retrieval.cleaning import looks_like_signal

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 180
MIN_CHUNK_CHARS = 40
# Consecutive units stay in the same chunk if TF-IDF cosine is at least this.
# Below it we treat as a topic change (same idea as semantic chunking, without an embedding API).
MIN_COHESION = 0.18
XLSX_ROWS_PER_CHUNK = 15
RECURSIVE_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""]


@dataclass(frozen=True)
class ChunkPlan:
    strategy: str
    reason: str


def plan_for_suffix(suffix: str) -> ChunkPlan:
    suffix = suffix.lower()
    if suffix == ".md":
        return ChunkPlan(
            "hybrid_markdown_cohesion",
            "Split on headings first (business sections). Inside a long section, merge "
            "paragraphs only while they stay similar; split when similarity drops or size caps.",
        )
    if suffix == ".pdf":
        return ChunkPlan(
            "hybrid_page_cohesion",
            "A PDF page is not automatically one chunk. Split into paragraphs/sentences, "
            "keep neighbors together only while they are similar enough (TF-IDF cosine), "
            "and always stop at the size cap. Page numbers stay as citation metadata.",
        )
    if suffix in {".xlsx", ".xlsm"}:
        return ChunkPlan(
            "tabular_row_groups",
            "Workbooks are rows of facts. Prose splitters would cut mid-row. Group rows and "
            "repeat headers so each chunk remains a valid table fragment.",
        )
    if suffix == ".jsonl":
        return ChunkPlan(
            "record_then_recursive",
            "Each line is already a record. Keep it whole unless it exceeds the cap.",
        )
    return ChunkPlan(
        "recursive_character",
        "No stable headings. Recursive split is the default: paragraph, then line, then "
        "sentence, then word — same cascade as LangChain RecursiveCharacterTextSplitter.",
    )


def recursive_split(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Same separator cascade as LangChain RecursiveCharacterTextSplitter (production default)."""
    parts = _split(text.strip(), list(RECURSIVE_SEPARATORS), chunk_size)
    return [_c for _c in _with_overlap(parts, overlap) if len(_c.strip()) >= MIN_CHUNK_CHARS]


def _split(text: str, separators: list[str], chunk_size: int) -> list[str]:
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    sep = ""
    nested: list[str] = []
    for i, candidate in enumerate(separators):
        if candidate == "":
            return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
        if candidate in text:
            sep = candidate
            nested = separators[i + 1 :]
            break
    if not sep:
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    pieces = [p for p in text.split(sep) if p != ""]
    acc: list[str] = []
    merged: list[str] = []

    def flush() -> None:
        if acc:
            merged.extend(_merge(acc, sep, chunk_size, nested))
            acc.clear()

    for piece in pieces:
        if len(piece) <= chunk_size:
            acc.append(piece)
        else:
            flush()
            merged.extend(_split(piece, nested or [""], chunk_size))
    flush()
    return merged


def _merge(parts: list[str], sep: str, chunk_size: int, nested: list[str]) -> list[str]:
    out: list[str] = []
    buf = ""
    for part in parts:
        candidate = part if not buf else f"{buf}{sep}{part}"
        if len(candidate) <= chunk_size:
            buf = candidate
            continue
        if buf:
            out.append(buf)
        if len(part) > chunk_size:
            out.extend(_split(part, nested or [""], chunk_size))
            buf = ""
        else:
            buf = part
    if buf:
        out.append(buf)
    return out


def _with_overlap(chunks: list[str], overlap: int) -> list[str]:
    if overlap <= 0 or len(chunks) < 2:
        return chunks
    out = [chunks[0]]
    for chunk in chunks[1:]:
        tail = out[-1][-overlap:]
        if chunk.startswith(tail):
            out.append(chunk)
        else:
            out.append(tail + chunk)
    return out


def split_markdown_sections(text: str) -> list[tuple[str, str]]:
    current = ["", "", ""]
    buf: list[str] = []
    sections: list[tuple[str, str]] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if not body:
            return
        path = " > ".join(h for h in current if h)
        sections.append((path, body))

    for line in text.split("\n"):
        match = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if not match:
            buf.append(line)
            continue
        flush()
        buf = [line]
        level = len(match.group(1))
        heading = match.group(2).strip()
        current[level - 1] = heading
        for i in range(level, 3):
            current[i] = ""
    flush()
    return sections or [("", text.strip())]


@dataclass(frozen=True)
class TextUnit:
    text: str
    page: str = ""


def split_prose_units(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    units: list[str] = []
    for para in paragraphs:
        if len(para) <= 220:
            units.append(para)
            continue
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
        units.extend(sentences or [para])
    return units


def consecutive_similarity(left: str, right: str) -> float:
    try:
        matrix = TfidfVectorizer(stop_words="english").fit_transform([left, right])
    except ValueError:
        return 0.0
    if matrix.shape[0] < 2:
        return 0.0
    return float(cosine_similarity(matrix[0], matrix[1])[0, 0])


def cohesive_merge(units: list[TextUnit], max_chars: int = CHUNK_SIZE, min_cosine: float = MIN_COHESION) -> list[TextUnit]:
    """Keep current+next in one chunk only if they are similar enough and under the size cap."""
    kept = [u for u in units if looks_like_signal(u.text) and len(u.text) >= 12]
    if not kept:
        return []
    groups: list[TextUnit] = []
    buf = kept[0].text
    pages = {kept[0].page} if kept[0].page else set()
    for nxt in kept[1:]:
        sim = consecutive_similarity(buf[-800:], nxt.text)
        candidate = f"{buf}\n\n{nxt.text}"
        same_topic = sim >= min_cosine
        tiny = len(nxt.text) < 120 or len(buf) < 120
        fits = len(candidate) <= max_chars
        if (same_topic or tiny) and fits:
            buf = candidate
            if nxt.page:
                pages.add(nxt.page)
            continue
        groups.append(TextUnit(text=buf, page=_page_label(pages)))
        buf = nxt.text
        pages = {nxt.page} if nxt.page else set()
    groups.append(TextUnit(text=buf, page=_page_label(pages)))
    return [g for g in groups if len(g.text) >= MIN_CHUNK_CHARS]


def _page_label(pages: set[str]) -> str:
    nums: list[int] = []
    for page in pages:
        if not page:
            continue
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


def hybrid_markdown_chunks(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for section, body in split_markdown_sections(text):
        units = [TextUnit(text=u) for u in split_prose_units(body)]
        merged = cohesive_merge(units) if len(body) > CHUNK_SIZE or len(units) > 1 else [TextUnit(text=body)]
        if not merged:
            merged = [TextUnit(text=p) for p in recursive_split(body)]
        for piece in merged:
            if looks_like_signal(piece.text) and len(piece.text) >= MIN_CHUNK_CHARS:
                out.append((section, piece.text))
    return out


def cohesive_pdf_chunks(pages: list[tuple[int, str]]) -> list[TextUnit]:
    units: list[TextUnit] = []
    for page_no, page_text in pages:
        for part in split_prose_units(page_text):
            units.append(TextUnit(text=part, page=str(page_no)))
    merged = cohesive_merge(units)
    if merged:
        return merged
    fallback: list[TextUnit] = []
    for page_no, page_text in pages:
        for piece in recursive_split(page_text):
            fallback.append(TextUnit(text=piece, page=str(page_no)))
    return fallback


def make_chunk(
    *,
    file_id: str,
    index: int,
    title: str,
    as_of: str,
    text: str,
    strategy: str,
    doc_type: str,
    section: str = "",
    page: str = "",
) -> Chunk:
    return Chunk(
        chunk_id=f"{file_id}:{index}",
        file_id=file_id,
        title=title,
        text=text,
        as_of=as_of,
        section=section,
        page=page,
        doc_type=doc_type,
        strategy=strategy,
    )
