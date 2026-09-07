from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import unquote_plus

from app.application.knowledge_service import KnowledgeService

log = logging.getLogger(__name__)


class KnowledgeS3Pipeline:
    """Poll S3 (and optionally SQS). Rebuild in-memory chunks when the bucket changes."""

    def __init__(
        self,
        knowledge: KnowledgeService,
        poll_seconds: float,
        queue_url: str = "",
        region: str | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._poll = max(poll_seconds, 5.0)
        self._queue_url = queue_url.strip()
        self._region = region or None
        self._task: asyncio.Task | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._knowledge.ingesting = True
        self._task = loop.create_task(self._run(), name="knowledge-s3-ingest")
        log.info("S3 knowledge ingest running in the background (poll %.0fs)", self._poll)

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def sync_now(self) -> None:
        await self._knowledge.reindex_if_changed("s3-ingest-pipeline")

    async def _run(self) -> None:
        try:
            while True:
                if self._queue_url:
                    await self._drain_queue()
                await self.sync_now()
                await asyncio.sleep(self._poll)
        except asyncio.CancelledError:
            return

    def _sqs(self):
        import boto3

        kwargs = {}
        if self._region:
            kwargs["region_name"] = self._region
        return boto3.client("sqs", **kwargs)

    async def _drain_queue(self) -> None:
        def _receive() -> list[dict]:
            resp = self._sqs().receive_message(
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=10,
                VisibilityTimeout=60,
            )
            return list(resp.get("Messages") or [])

        messages = await asyncio.to_thread(_receive)
        if not messages:
            return
        log.info("S3 queue had %s message(s)", len(messages))
        await self.sync_now()

        def _delete() -> None:
            client = self._sqs()
            entries = [
                {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]}
                for i, m in enumerate(messages)
                if m.get("ReceiptHandle")
            ]
            if entries:
                client.delete_message_batch(QueueUrl=self._queue_url, Entries=entries)

        await asyncio.to_thread(_delete)


def _s3_keys_from_sqs_body(body: str) -> list[str]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    if isinstance(payload.get("Message"), str):
        try:
            payload = json.loads(payload["Message"])
        except json.JSONDecodeError:
            return []
    records = payload.get("Records") or payload.get("records") or []
    keys: list[str] = []
    if isinstance(records, list):
        for rec in records:
            if not isinstance(rec, dict):
                continue
            obj = (rec.get("s3") or {}).get("object") or {}
            key = obj.get("key")
            if key:
                keys.append(unquote_plus(str(key)))
    detail = payload.get("detail") or {}
    if isinstance(detail, dict):
        obj = detail.get("object") or {}
        if obj.get("key"):
            keys.append(unquote_plus(str(obj["key"])))
    return keys
