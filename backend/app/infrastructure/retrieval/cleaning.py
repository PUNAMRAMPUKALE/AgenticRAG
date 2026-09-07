from __future__ import annotations

import re
import unicodedata

# Drop extracted pages/cells that are almost certainly OCR/parse junk.
_MIN_SIGNAL_CHARS = 24
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]+")


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def strip_controls(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", text)


def collapse_whitespace(text: str) -> str:
    lines = [_MULTI_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return _MULTI_NL_RE.sub("\n\n", "\n".join(lines)).strip()


def repair_pdf_line_wrap(text: str) -> str:
    """Rejoin words split by PDF extractors ('regula-\ntion' → 'regulation')."""
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    # Single newlines inside a paragraph are usually wrap, not new sections.
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    return collapse_whitespace(text)


def looks_like_signal(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < _MIN_SIGNAL_CHARS:
        return False
    alnum = sum(ch.isalnum() for ch in compact)
    return alnum / max(len(compact), 1) >= 0.30


def clean_prose(text: str, *, pdf: bool = False) -> str:
    text = normalize_unicode(text)
    text = strip_controls(text)
    if pdf:
        text = repair_pdf_line_wrap(text)
    else:
        text = collapse_whitespace(text)
    return text


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    text = collapse_whitespace(strip_controls(normalize_unicode(str(value))))
    return text
