"""Where evidence frames live: the local vault, or an S3 bucket.

The database holds a reference per alert (`alerts.evidence_image`). With the
local backend that reference is an absolute path under CAMVIEW_DATA_DIR, as it
always was. With `CAMVIEW_STORAGE_BACKEND=s3` it is `s3://bucket/key`, the
frame bytes live in the bucket, and the instance's disk is only a working area
(uploads, thumbnails, PDF renders) that can be lost without losing evidence.

Why this exists: on any host whose disk is not durable — a container replaced
on deploy, Render's free tier, an EC2 instance rebuilt from an AMI — the rows
survive in Postgres while the files vanish, and the portal then shows "no
evidence frame on file" for alerts that were linked an hour earlier. Putting
the frames in S3 breaks that dependency: the instance can be replaced at will.

Credentials come from the standard AWS chain (instance role on EC2/ECS,
AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in the environment for a workstation).
boto3 is imported lazily so the local backend never needs it installed.

Reads that need a file on disk (thumbnails for a report) go through
`local_copy()`, which fetches an S3 object into a small cache under the data
directory and returns its path; local references come back unchanged.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Iterator

from .settings import get_settings

log = logging.getLogger("camview.storage")
_S = get_settings()

S3_PREFIX = "s3://"


def is_s3(ref: str) -> bool:
    return bool(ref) and ref.startswith(S3_PREFIX)


def enabled() -> bool:
    """True when frames are stored in S3 rather than on the instance."""
    return _S.storage_backend.lower() == "s3" and bool(_S.s3_bucket)


def _split(ref: str) -> tuple[str, str]:
    rest = ref[len(S3_PREFIX):]
    bucket, _, key = rest.partition("/")
    return bucket, key


_client = None


def client():
    """One boto3 S3 client per process (thread-safe for reads and puts)."""
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config
        _client = boto3.client("s3", region_name=_S.s3_region or None,
                               config=Config(retries={"max_attempts": 5, "mode": "standard"}))
    return _client


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", part or "")[:120]


def key_for(exam_code: str, alarm_id: str, suffix: str) -> str:
    base = (_S.s3_prefix.strip("/") + "/") if _S.s3_prefix else ""
    return f"{base}evidence/{_safe(exam_code)}/{_safe(alarm_id)}{suffix.lower()}"


def store(local_path: str | os.PathLike, exam_code: str, alarm_id: str) -> str:
    """Put one frame where evidence lives and return the reference to record.

    Local backend: the path itself. S3 backend: uploads the file and returns
    `s3://bucket/key`; the local file is left in place as a cache."""
    p = Path(local_path)
    if not enabled():
        return str(p)
    key = key_for(exam_code, alarm_id, p.suffix or ".jpg")
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    client().upload_file(str(p), _S.s3_bucket, key, ExtraArgs={"ContentType": ctype})
    return f"{S3_PREFIX}{_S.s3_bucket}/{key}"


def exists(ref: str) -> bool:
    """Does the referenced frame exist? S3 references are trusted without a
    round trip — one HEAD per row on every alert list would be too slow and the
    bucket does not lose objects the way an instance loses files."""
    if not ref:
        return False
    if is_s3(ref):
        return True
    return os.path.isfile(ref)


def cache_dir() -> Path:
    d = _S.data_dir / "cache" / "evidence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def local_copy(ref: str) -> str | None:
    """A path on disk for the frame: the reference itself when local, or an
    S3 object fetched into the cache (once). None when it cannot be had."""
    if not ref:
        return None
    if not is_s3(ref):
        return ref if os.path.isfile(ref) else None
    bucket, key = _split(ref)
    target = cache_dir() / (hashlib.sha1(ref.encode()).hexdigest()[:24] + Path(key).suffix.lower())
    if target.exists() and target.stat().st_size > 0:
        return str(target)
    try:
        obj = client().get_object(Bucket=bucket, Key=key)
        with open(target, "wb") as fh:
            while True:
                b = obj["Body"].read(1 << 20)
                if not b:
                    break
                fh.write(b)
        return str(target)
    except Exception as e:  # noqa: BLE001
        log.warning("could not fetch %s: %s", ref, e)
        return None


def stream(ref: str) -> tuple[Iterator[bytes], str, int | None] | None:
    """(chunks, content type, length) for an S3 reference, for the evidence route."""
    bucket, key = _split(ref)
    try:
        obj = client().get_object(Bucket=bucket, Key=key)
    except Exception as e:  # noqa: BLE001
        log.warning("could not read %s: %s", ref, e)
        return None
    body = obj["Body"]

    def chunks():
        try:
            while True:
                b = body.read(256 * 1024)
                if not b:
                    break
                yield b
        finally:
            close = getattr(body, "close", None)
            if close:
                close()
    return chunks(), obj.get("ContentType") or "image/jpeg", obj.get("ContentLength")


def delete_exam(exam_code: str) -> int:
    """Remove every frame of an exam from the bucket (purge / retention sweep)."""
    if not enabled():
        return 0
    prefix = key_for(exam_code, "", "").rstrip(".")
    prefix = prefix[: prefix.rfind("/") + 1]
    c = client()
    n = 0
    token = None
    while True:
        kw = {"Bucket": _S.s3_bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        page = c.list_objects_v2(**kw)
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            c.delete_objects(Bucket=_S.s3_bucket, Delete={"Objects": keys, "Quiet": True})
            n += len(keys)
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
    return n


def check() -> str:
    """One-line status for the boot log and /healthz."""
    if not enabled():
        return "local disk"
    try:
        client().head_bucket(Bucket=_S.s3_bucket)
        return f"s3://{_S.s3_bucket} ({_S.s3_region}) reachable"
    except Exception as e:  # noqa: BLE001
        return f"s3://{_S.s3_bucket} NOT reachable: {e}"
