from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.metrics import EVAL_CASES, EVAL_RUNS
from app.core.telemetry import get_tracer
from app.domain.ports import SearchIndex
from app.evals.score import score_case, summarize
from app.infrastructure.llm.assistant import KnowledgeAssistant, extractive_answer, retrieve

log = logging.getLogger(__name__)

CASES_PATH = Path(__file__).with_name("cases.json")


def load_dataset(path: Path | None = None) -> dict:
    payload = json.loads((path or CASES_PATH).read_text(encoding="utf-8"))
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise RuntimeError("Eval dataset has no cases")
    return payload


async def run_evals(
    index: SearchIndex,
    *,
    generate: bool = False,
    dataset_path: Path | None = None,
) -> dict:
    dataset = load_dataset(dataset_path)
    min_rate = float(dataset.get("min_pass_rate") or 0.75)
    assistant = KnowledgeAssistant()
    scores = []
    with get_tracer().start_as_current_span("eval.run") as span:
        span.set_attribute("eval.generate", generate)
        span.set_attribute("eval.cases", len(dataset["cases"]))
        for case in dataset["cases"]:
            query = str(case.get("query") or "")
            with get_tracer().start_as_current_span("eval.case") as case_span:
                case_span.set_attribute("eval.case_id", str(case.get("id") or ""))
                if generate:
                    answer, citations, used_llm = await assistant.generate(query, index)
                else:
                    formatted, citations = retrieve(index, query)
                    answer, used_llm = extractive_answer(formatted, citations), False
                scored = score_case(case, citations=citations, answer=answer)
                scores.append(scored)
                EVAL_CASES.labels("pass" if scored.passed else "fail").inc()
                case_span.set_attribute("eval.pass", scored.passed)
                log.info(
                    "Eval %s %s",
                    scored.case_id,
                    "pass" if scored.passed else "fail",
                    extra={
                        "pipeline": "eval",
                        "stage": "case",
                        "source_key": scored.case_id,
                        "outcome": "ok" if scored.passed else "error",
                    },
                )
        report = summarize(scores, min_rate)
        report["generate"] = generate
        report["used_llm"] = generate
        EVAL_RUNS.labels("ok" if report["ok"] else "fail").inc()
        span.set_attribute("eval.pass_rate", report["pass_rate"])
        span.set_attribute("eval.ok", report["ok"])
        from app.core.config import get_settings
        from app.evals.langsmith_sync import langsmith_enabled, publish_experiment

        settings = get_settings()
        if langsmith_enabled(settings):
            try:
                report["langsmith"] = await publish_experiment(
                    settings, cases=dataset["cases"], scores=scores, generate=generate
                )
            except Exception as exc:
                log.exception("LangSmith experiment publish failed")
                report["langsmith_error"] = str(exc)[:500]
        else:
            report["langsmith_error"] = "LANGSMITH_API_KEY is empty; experiment was not uploaded"
        return report
