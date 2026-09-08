from __future__ import annotations

import asyncio
import logging

from app.infrastructure.aws import boto_client
from app.infrastructure.retrieval.s3_events import parse_sqs_jobs
from app.infrastructure.retrieval.s3_loader import S3CorpusLoader

log = logging.getLogger(__name__)


class KnowledgeS3Pipeline:
    """S3 ingest: SQS per-object jobs when configured, otherwise bucket polling."""

    def __init__(
        self,
        knowledge,
        poll_seconds: float,
        queue_url: str = "",
        region: str | None = None,
        *,
        loader: S3CorpusLoader | None = None,
        dlq_url: str = "",
        max_receive: int = 5,
        visibility_timeout: int = 900,
        reconcile_seconds: float = 3600,
    ) -> None:
        self._knowledge = knowledge
        self._poll = max(poll_seconds, 5.0)
        self._queue_url = queue_url.strip()
        self._dlq_url = dlq_url.strip()
        self._region = region or None
        self._loader = loader
        self._max_receive = max(1, max_receive)
        self._visibility = max(30, visibility_timeout)
        self._reconcile = max(0.0, reconcile_seconds)
        self._task: asyncio.Task | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._task = loop.create_task(self._run(), name="knowledge-s3-ingest")
        if self._queue_url:
            log.info(
                "S3 ingest worker consuming SQS (%s); reconcile every %.0fs",
                self._queue_url.split("/")[-1],
                self._reconcile,
            )
        else:
            log.info("S3 ingest worker polling the bucket every %.0fs", self._poll)

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def sync_now(self) -> None:
        await self._knowledge.reindex_if_changed("s3-ingest-pipeline")

    async def _run(self) -> None:
        try:
            if self._queue_url:
                await asyncio.gather(self._consume_queue(), self._reconcile_loop())
            else:
                while True:
                    await self.sync_now()
                    await asyncio.sleep(self._poll)
        except asyncio.CancelledError:
            return

    async def _reconcile_loop(self) -> None:
        if self._reconcile <= 0:
            await asyncio.Future()
            return
        await self.sync_now()
        while True:
            await asyncio.sleep(self._reconcile)
            await self.sync_now()

    def _sqs(self):
        return boto_client("sqs", self._region)

    async def _consume_queue(self) -> None:
        while True:
            messages = await asyncio.to_thread(self._receive)
            if not messages:
                continue
            for message in messages:
                await self._handle_message(message)

    def _receive(self) -> list[dict]:
        resp = self._sqs().receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
            VisibilityTimeout=self._visibility,
            AttributeNames=["ApproximateReceiveCount"],
        )
        return list(resp.get("Messages") or [])

    async def _handle_message(self, message: dict) -> None:
        receipt = str(message.get("ReceiptHandle") or "")
        body = str(message.get("Body") or "")
        receive_count = int((message.get("Attributes") or {}).get("ApproximateReceiveCount") or "1")
        try:
            await self._apply_body(body)
        except Exception:
            log.exception("Ingest job failed (receive %s/%s)", receive_count, self._max_receive)
            if receive_count >= self._max_receive:
                await self._to_dlq(body, receipt)
            return
        await self._delete(receipt)

    async def _apply_body(self, body: str) -> None:
        jobs = parse_sqs_jobs(body)
        if not jobs:
            raise ValueError("SQS message is not an S3 object event")
        expected_bucket = self._loader.bucket_name() if self._loader is not None else ""
        processed = 0
        for job in jobs:
            if expected_bucket and job.bucket and job.bucket != expected_bucket:
                log.info("Skipping S3 event for other bucket %s", job.bucket)
                continue
            source_key = self._loader.to_source_key(job.object_key) if self._loader is not None else None
            if not source_key:
                continue
            await self._knowledge.ingest_object(
                source_key,
                deleted=job.deleted,
                actor="s3-sqs",
            )
            processed += 1
        if processed == 0:
            log.info("SQS message had no objects in this knowledge prefix")

    async def _delete(self, receipt: str) -> None:
        if not receipt:
            return

        def _do() -> None:
            self._sqs().delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt)

        await asyncio.to_thread(_do)

    async def _to_dlq(self, body: str, receipt: str) -> None:
        if not self._dlq_url:
            log.error("Dropping failed ingest job; set KNOWLEDGE_S3_DLQ_URL or an SQS redrive policy")
            await self._delete(receipt)
            return

        def _do() -> None:
            client = self._sqs()
            client.send_message(QueueUrl=self._dlq_url, MessageBody=body)
            client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt)

        await asyncio.to_thread(_do)
        log.error("Moved failed ingest job to the dead-letter queue")
