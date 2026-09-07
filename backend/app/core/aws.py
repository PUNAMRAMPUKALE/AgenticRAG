from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

_EMPTY_AWS_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")


def drop_empty_aws_env() -> None:
    """Empty dotenv keys block the default IAM/instance-profile chain."""
    for key in _EMPTY_AWS_KEYS:
        if os.environ.get(key) == "":
            os.environ.pop(key, None)


def load_optional_secrets() -> None:
    """If AWS_SECRETS_ARN is set, copy missing keys from Secrets Manager JSON."""
    drop_empty_aws_env()
    arn = (os.getenv("AWS_SECRETS_ARN") or "").strip()
    if not arn:
        return
    try:
        import boto3

        client = boto3.client("secretsmanager")
        payload = client.get_secret_value(SecretId=arn).get("SecretString") or "{}"
        data = json.loads(payload)
    except Exception:
        log.exception("Failed to load AWS_SECRETS_ARN")
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if os.environ.get(key):
            continue
        os.environ[key] = value
    drop_empty_aws_env()
    log.info("Loaded secrets from AWS Secrets Manager")
