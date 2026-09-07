from __future__ import annotations

import os

import boto3


def boto_client(service: str, region: str | None = None):
    """Use the default credential chain (env, shared config, IAM role)."""
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        if os.environ.get(key) == "":
            os.environ.pop(key, None)
    kwargs = {}
    if region:
        kwargs["region_name"] = region
    return boto3.client(service, **kwargs)
