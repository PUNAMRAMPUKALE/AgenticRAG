from __future__ import annotations

import logging
import os

from app.core.config import Settings
from app.evals.score import CaseScore, score_case

log = logging.getLogger(__name__)


def langsmith_enabled(settings: Settings) -> bool:
    return bool(settings.langsmith_api_key.strip() or os.getenv("LANGCHAIN_API_KEY", "").strip())


def _apply_env(settings: Settings) -> None:
    key = settings.langsmith_api_key.strip() or os.getenv("LANGCHAIN_API_KEY", "").strip()
    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"
    os.environ["LANGSMITH_API_KEY"] = key
    os.environ.setdefault("LANGCHAIN_API_KEY", key)
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project.strip() or "agenticrag"
    if settings.langsmith_endpoint.strip():
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint.strip()
    if settings.langsmith_workspace_id.strip():
        os.environ["LANGSMITH_WORKSPACE_ID"] = settings.langsmith_workspace_id.strip()


def _ensure_dataset(client, name: str, cases: list[dict]):
    existing = list(client.list_datasets(dataset_name=name))
    if existing:
        dataset = existing[0]
    else:
        dataset = client.create_dataset(
            dataset_name=name,
            description="AgenticRAG gold retrieval evals (citation file_id + required phrases).",
        )
    have = {str((ex.inputs or {}).get("query") or "") for ex in client.list_examples(dataset_id=dataset.id)}
    wanted = {str(c.get("query") or "") for c in cases}
    if have != wanted:
        for ex in client.list_examples(dataset_id=dataset.id):
            client.delete_example(ex.id)
        client.create_examples(
            dataset_id=dataset.id,
            examples=[
                {
                    "inputs": {"query": str(case.get("query") or "")},
                    "outputs": {
                        "id": str(case.get("id") or ""),
                        "expected_file_ids": list(case.get("expected_file_ids") or []),
                        "must_contain": list(case.get("must_contain") or []),
                        "abstain": bool(case.get("abstain")),
                    },
                }
                for case in cases
            ],
        )
    return dataset


def _experiment_url(results, dataset_name: str) -> str:
    for attr in ("experiment_url", "url"):
        value = getattr(results, attr, None)
        if isinstance(value, str) and value.startswith("http"):
            return value
    name = getattr(results, "experiment_name", None) or ""
    if name:
        return f"https://smith.langchain.com/datasets?search={dataset_name}"
    return "https://smith.langchain.com"


async def publish_experiment(
    settings: Settings,
    *,
    cases: list[dict],
    scores: list[CaseScore],
    generate: bool,
) -> dict:
    """Create/update the gold dataset and log an experiment on the LangSmith dashboard."""
    _apply_env(settings)
    from langsmith import aevaluate
    from langsmith import Client

    client = Client()
    dataset_name = settings.langsmith_dataset.strip() or "agenticrag-gold"
    dataset = _ensure_dataset(client, dataset_name, cases)
    by_query = {s.query: s for s in scores}

    async def target(inputs: dict) -> dict:
        scored = by_query.get(str(inputs.get("query") or ""))
        if scored is None:
            return {"answer": "", "cited_file_ids": []}
        return {
            "answer": scored.answer,
            "cited_file_ids": scored.cited_file_ids,
            "case_id": scored.case_id,
        }

    def pass_score(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        citations = [{"file_id": fid} for fid in (outputs.get("cited_file_ids") or [])]
        scored = score_case(reference_outputs or {}, citations=citations, answer=str(outputs.get("answer") or ""))
        return {"key": "pass", "score": 1.0 if scored.passed else 0.0}

    def retrieval_score(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        citations = [{"file_id": fid} for fid in (outputs.get("cited_file_ids") or [])]
        scored = score_case(reference_outputs or {}, citations=citations, answer=str(outputs.get("answer") or ""))
        return {"key": "retrieval_hit", "score": 1.0 if scored.retrieval_hit else 0.0}

    mode = "generate" if generate else "retrieval"
    results = await aevaluate(
        target,
        data=dataset.name,
        evaluators=[pass_score, retrieval_score],
        experiment_prefix=f"agenticrag-{mode}",
        description="Gold Vespa citation evals from AgenticRAG",
        metadata={"generate": generate, "service": "agenticrag"},
        max_concurrency=1,
    )
    url = _experiment_url(results, dataset_name)
    host = "https://eu.smith.langchain.com" if "eu.api" in (settings.langsmith_endpoint or "") else "https://smith.langchain.com"
    url = f"{host}/datasets/{dataset.id}"
    log.info("LangSmith experiment published (%s)", dataset_name)
    return {"dataset": dataset_name, "url": url, "project": settings.langsmith_project.strip() or "agenticrag"}
