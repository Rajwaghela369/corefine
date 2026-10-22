"""Object storage: one S3 bucket in cloud mode, a local folder with the same key layout otherwise.

Key layout (spec):  datasets/<id>/dataset.yaml | raw/... | README.md
                    runs/<run-id>/plan.json | code/... | logs/... | outputs/... | report.md
"""

import hashlib
import mimetypes
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str | None = None) -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, key: str) -> None: ...
    def presign_put(self, key: str, expires_s: int = 900) -> str | None: ...
    def ping(self) -> None: ...


class S3Store:
    def __init__(self, bucket: str, region: str, endpoint_url: str = "", key_id: str = "", secret: str = ""):
        import boto3

        self.bucket = bucket
        # Keys come from Settings (backend/.env), which boto3 cannot see in os.environ
        self.s3 = boto3.client("s3", region_name=region, endpoint_url=endpoint_url or None,
                               aws_access_key_id=key_id or None, aws_secret_access_key=secret or None)

    def put(self, key, data, content_type=None):
        ct = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=ct)
        return sha256(data)

    def get(self, key):
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key):
        from botocore.exceptions import ClientError

        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, key):
        self.s3.delete_object(Bucket=self.bucket, Key=key)

    def list(self, prefix):
        keys = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return sorted(keys)

    def presign_put(self, key, expires_s=900):
        return self.s3.generate_presigned_url(
            "put_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_s
        )

    def ping(self):
        self.s3.head_bucket(Bucket=self.bucket)


class LocalStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root.resolve()):
            raise ValueError(f"key escapes the store: {key}")
        return p

    def put(self, key, data, content_type=None):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return sha256(data)

    def get(self, key):
        p = self._path(key)
        if not p.is_file():
            raise FileNotFoundError(key)
        return p.read_bytes()

    def exists(self, key):
        return self._path(key).is_file()

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix):
        base = self.root.resolve()
        return sorted(
            str(p.relative_to(base)) for p in base.rglob("*")
            if p.is_file() and str(p.relative_to(base)).startswith(prefix)
        )

    def presign_put(self, key, expires_s=900):
        return None  # browser uploads go through the backend in local mode

    def ping(self):
        self.root.stat()


@lru_cache
def get_store() -> ObjectStore:
    s = get_settings()
    if s.S3_BUCKET and s.AWS_ACCESS_KEY_ID:
        return S3Store(s.S3_BUCKET, s.AWS_REGION, s.S3_ENDPOINT_URL, s.AWS_ACCESS_KEY_ID, s.AWS_SECRET_ACCESS_KEY)
    return LocalStore(s.LOCAL_DATA_DIR / "bucket")
