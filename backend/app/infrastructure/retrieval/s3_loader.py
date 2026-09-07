from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.domain.models import Chunk
from app.infrastructure.retrieval.corpus import SUPPORTED_SUFFIXES
from app.infrastructure.retrieval.ingest import ingest_bytes
from app.infrastructure.retrieval.sparse import build_index

log = logging.getLogger(__name__)


def _is_supported_key(key: str) -> bool:
    name = Path(key).name
    if not name or name.startswith(".") or name.startswith("~$"):
        return False
    return Path(key).suffix.lower() in SUPPORTED_SUFFIXES


def _safe_relative(key: str) -> str | None:
    rel = key.replace("\\", "/").lstrip("/")
    if not rel or rel.endswith("/"):
        return None
    if ".." in Path(rel).parts:
        return None
    if not _is_supported_key(rel):
        return None
    return rel


class S3CorpusLoader:
    """Read documents from S3 into memory. Does not copy files onto disk."""

    def __init__(self, bucket: str, prefix: str, region: str | None):
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._region = region or None

    def _client(self):
        import boto3

        kwargs = {}
        if self._region:
            kwargs["region_name"] = self._region
        return boto3.client("s3", **kwargs)

    def _object_key(self, relative: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{relative}"
        return relative

    def list_etags(self) -> dict[str, str]:
        client = self._client()
        remote: dict[str, str] = {}
        kwargs: dict = {"Bucket": self._bucket}
        if self._prefix:
            kwargs["Prefix"] = self._prefix.rstrip("/") + "/"
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(**kwargs):
            for obj in page.get("Contents") or []:
                key = str(obj.get("Key") or "")
                if self._prefix and key.startswith(self._prefix + "/"):
                    rel = key[len(self._prefix) + 1 :]
                else:
                    rel = key
                safe = _safe_relative(rel)
                if not safe:
                    continue
                remote[safe] = str(obj.get("ETag") or "").strip('"')
        return remote

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for rel, etag in sorted(self.list_etags().items()):
            h.update(rel.encode())
            h.update(etag.encode())
        return h.hexdigest()[:16]

    def load(self) -> tuple[list[Chunk], SparseIndex, str]:
        client = self._client()
        etags = self.list_etags()
        chunks: list[Chunk] = []
        for rel in sorted(etags):
            try:
                body = client.get_object(Bucket=self._bucket, Key=self._object_key(rel))["Body"].read()
                built = ingest_bytes(rel, body)
            except Exception:
                log.exception("Failed to ingest s3://%s/%s", self._bucket, self._object_key(rel))
                continue
            if not built:
                log.warning("No usable chunks from s3://%s/%s", self._bucket, self._object_key(rel))
                continue
            chunks.extend(built)
        version = self.fingerprint()
        log.info("Loaded %s chunks from %s S3 objects in s3://%s/%s", len(chunks), len(etags), self._bucket, self._prefix)
        return chunks, build_index(chunks), version
