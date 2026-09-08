from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CaseScore:
    case_id: str
    query: str
    passed: bool
    retrieval_hit: bool
    answer_ok: bool
    abstain: bool
    cited_file_ids: list[str] = field(default_factory=list)
    missing_phrases: list[str] = field(default_factory=list)
    detail: str = ""
    answer: str = ""


def cited_ids(citations: list[dict]) -> list[str]:
    return [str(c.get("file_id") or "") for c in citations if c.get("file_id")]


def retrieval_hit(expected_file_ids: list[str], citations: list[dict]) -> bool:
    if not expected_file_ids:
        return True
    blob = " ".join(cited_ids(citations)).lower()
    return all(token.lower() in blob for token in expected_file_ids if token.strip())


def missing_phrases(must_contain: list[str], answer: str) -> list[str]:
    text = (answer or "").lower()
    return [p for p in must_contain if p.strip() and p.strip().lower() not in text]


def looks_like_abstain(answer: str, citations: list[dict]) -> bool:
    text = (answer or "").lower()
    if "not in the knowledge base" in text or "could not find this" in text:
        return True
    return not cited_ids(citations)


def score_case(case: dict, *, citations: list[dict], answer: str) -> CaseScore:
    case_id = str(case.get("id") or "unknown")
    query = str(case.get("query") or "")
    expected = [str(x) for x in (case.get("expected_file_ids") or [])]
    phrases = [str(x) for x in (case.get("must_contain") or [])]
    abstain = bool(case.get("abstain"))
    ids = cited_ids(citations)
    if abstain:
        answer_ok = looks_like_abstain(answer, citations)
        return CaseScore(
            case_id=case_id,
            query=query,
            passed=answer_ok,
            retrieval_hit=bool(ids),
            answer_ok=answer_ok,
            abstain=True,
            cited_file_ids=ids,
            detail="abstain ok" if answer_ok else "expected abstain; cited corpus or answered anyway",
            answer=answer,
        )
    hit = retrieval_hit(expected, citations)
    missing = missing_phrases(phrases, answer)
    answer_ok = not missing
    passed = hit and answer_ok
    return CaseScore(
        case_id=case_id,
        query=query,
        passed=passed,
        retrieval_hit=hit,
        answer_ok=answer_ok,
        abstain=False,
        cited_file_ids=ids,
        missing_phrases=missing,
        detail="ok" if passed else "missed expected file and/or required phrases",
        answer=answer,
    )


def summarize(scores: list[CaseScore], min_pass_rate: float) -> dict:
    passed = sum(1 for s in scores if s.passed)
    rate = passed / len(scores) if scores else 0.0
    return {
        "cases_total": len(scores),
        "passed": passed,
        "failed": len(scores) - passed,
        "pass_rate": round(rate, 4),
        "min_pass_rate": min_pass_rate,
        "ok": rate + 1e-9 >= min_pass_rate,
        "results": [
            {
                "id": s.case_id,
                "query": s.query,
                "pass": s.passed,
                "retrieval_hit": s.retrieval_hit,
                "answer_ok": s.answer_ok,
                "abstain": s.abstain,
                "cited_file_ids": s.cited_file_ids,
                "missing_phrases": s.missing_phrases,
                "detail": s.detail,
            }
            for s in scores
        ],
    }
