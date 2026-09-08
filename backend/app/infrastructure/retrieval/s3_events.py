from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import unquote_plus

from app.infrastructure.retrieval.ingest_queue import FULL_REINDEX_TYPE


@dataclass(frozen=True)
class ObjectJob:
    bucket: str
    object_key: str
    deleted: bool


def parse_reindex_command(body: str) -> str | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("Message"), str):
        try:
            inner = json.loads(payload["Message"])
        except json.JSONDecodeError:
            return None
        if isinstance(inner, dict):
            payload = inner
    if payload.get("type") != FULL_REINDEX_TYPE:
        return None
    actor = str(payload.get("actor") or "reindex").strip() or "reindex"
    return actor


def parse_sqs_jobs(body: str) -> list[ObjectJob]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    return _jobs_from_payload(payload)


def _jobs_from_payload(payload: dict) -> list[ObjectJob]:
    if isinstance(payload.get("Message"), str):
        try:
            inner = json.loads(payload["Message"])
        except json.JSONDecodeError:
            inner = None
        if isinstance(inner, dict):
            return _jobs_from_payload(inner)

    jobs: list[ObjectJob] = []
    records = payload.get("Records") or payload.get("records") or []
    if isinstance(records, list):
        for rec in records:
            if not isinstance(rec, dict):
                continue
            s3 = rec.get("s3") or {}
            if not isinstance(s3, dict):
                continue
            bucket = str((s3.get("bucket") or {}).get("name") or "")
            key = (s3.get("object") or {}).get("key")
            if not key:
                continue
            event = str(rec.get("eventName") or "")
            deleted = "ObjectRemoved" in event or event.lower().startswith("delete")
            jobs.append(ObjectJob(bucket=bucket, object_key=unquote_plus(str(key)), deleted=deleted))

    detail = payload.get("detail")
    if isinstance(detail, dict) and (detail.get("object") or detail.get("bucket")):
        bucket = str((detail.get("bucket") or {}).get("name") or "")
        key = (detail.get("object") or {}).get("key")
        if key:
            detail_type = str(payload.get("detail-type") or payload.get("detail_type") or "")
            deleted = "Deleted" in detail_type or "Object Deleted" in detail_type
            jobs.append(ObjectJob(bucket=bucket, object_key=unquote_plus(str(key)), deleted=deleted))
    return jobs
