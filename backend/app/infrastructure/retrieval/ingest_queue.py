from __future__ import annotations

import json

from app.infrastructure.aws import boto_client

FULL_REINDEX_TYPE = "agenticrag.full_reindex"


def enqueue_full_reindex(queue_url: str, actor: str, region: str | None = None) -> None:
    if not queue_url.strip():
        raise RuntimeError("KNOWLEDGE_S3_QUEUE_URL is empty")
    boto_client("sqs", region).send_message(
        QueueUrl=queue_url.strip(),
        MessageBody=json.dumps({"type": FULL_REINDEX_TYPE, "actor": actor}),
    )
