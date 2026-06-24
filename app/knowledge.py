from __future__ import annotations

import json
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

_LOCAL_KB_PATH = os.path.join(os.path.dirname(__file__), "data", "knowledge_base.json")

S3_BUCKET = os.getenv("S3_BUCKET", "swim-program")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "https://storage.eu-north1.nebius.cloud")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_KEY = "knowledge_base.json"

_knowledge_base = None


def _fetch_from_object_storage() -> dict | None:
    if not (S3_ACCESS_KEY and S3_SECRET_KEY):
        return None
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
        )
        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        return json.loads(obj["Body"].read())
    except (ClientError, BotoCoreError, json.JSONDecodeError):
        return None


def _load() -> dict:
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = _fetch_from_object_storage()
        if _knowledge_base is None:
            with open(_LOCAL_KB_PATH) as f:
                _knowledge_base = json.load(f)
    return _knowledge_base


def get_coaching_summary(level: str, goal: str) -> str | None:
    kb = _load()
    key = f"{level}_{goal}"
    profile = kb["profiles"].get(key)
    return profile["coaching_summary"] if profile else None


def get_profile_data(level: str, goal: str) -> dict | None:
    kb = _load()
    key = f"{level}_{goal}"
    return kb["profiles"].get(key)
