"""Off-machine object storage, when the pharmacy has any.

WHY THIS EXISTS

A backup that lives on the same disk as the database is not a backup. It
survives somebody deleting a row; it does not survive the disk, the theft of
the till, or the fire. `backup.py` says out loud that one disk failure ends the
business, and until now the only answer to that was a folder on that same disk,
with `BACKUP_DIR` left as an env override for "a real off-machine target" that
nothing implemented.

On a hosted deployment it is worse than unhelpful, it is a lie: Render gives a
container an ephemeral filesystem, so the nightly backup wrote a verified file
onto a disk that the next deploy threw away. The screen said the pharmacy was
protected. It was not.

So: an S3-compatible bucket, configured by environment and absent by default.

WHY IT IS OPTIONAL, AND WHY THAT IS NOT A HEDGE

Most installs of this product are one machine in a back office. That pharmacy
has no object store, no credentials and no interest in acquiring either, which
is exactly the reasoning that put compliance documents and the logo in the
database as base64 rather than behind a path into a filesystem. Nothing here
changes for them: with no credentials set, `enabled()` is False, every call is
a no-op that says so, and the local folder remains the whole story.

WHY FAILING TO UPLOAD IS NOT AN ERROR

A backup that verified locally is a good backup whether or not the copy reached
the bucket. Raising here would turn "we also could not reach the internet" into
"your backup failed", which is both false and the kind of message that teaches
somebody to ignore the backup screen. Upload failures are reported in the
result and logged, and the caller decides.

S3-compatible rather than DigitalOcean-specific: Spaces, Backblaze B2, MinIO in
a back office and AWS itself all speak this, and the only thing that changes is
the endpoint.
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import env

log = logging.getLogger("rx5000.objects")

#: The bucket and how to reach it. Endpoint rather than region alone, because
#: every S3-compatible provider that is not AWS needs one.
ENDPOINT = env("SPACES_ENDPOINT", "").strip().rstrip("/")
BUCKET = env("SPACES_BUCKET", "").strip()
REGION = env("SPACES_REGION", "").strip() or "us-east-1"
KEY = env("SPACES_KEY", "").strip()
SECRET = env("SPACES_SECRET", "").strip()

#: Everything this product writes goes under one prefix, so a bucket shared
#: with something else stays legible and a lifecycle rule can be aimed at us
#: without catching somebody else's files.
PREFIX = env("SPACES_PREFIX", "rx5000").strip().strip("/")

_client = None


def enabled() -> bool:
    """Whether off-machine storage is configured at all.

    All five, not some. A half-configured bucket is the state where an upload
    fails every night at two in the morning and the first anybody hears of it
    is when a backup is needed.
    """
    return bool(ENDPOINT and BUCKET and KEY and SECRET)


def why_not() -> str:
    """What is missing, for a screen that has to explain itself."""
    if enabled():
        return ""
    missing = [name for name, value in (
        ("SPACES_ENDPOINT", ENDPOINT), ("SPACES_BUCKET", BUCKET),
        ("SPACES_KEY", KEY), ("SPACES_SECRET", SECRET)) if not value]
    if len(missing) == 4:
        return ("No off-machine storage is configured, so backups exist only on "
                "this machine.")
    return ("Off-machine storage is half configured and will not be used: "
            + ", ".join(missing) + " " + ("is" if len(missing) == 1 else "are")
            + " not set.")


def _s3():
    global _client
    if _client is None:
        import boto3                       # imported late: an install without
        from botocore.config import Config  # a bucket never pays for it
        _client = boto3.client(
            "s3",
            endpoint_url=ENDPOINT,
            region_name=REGION,
            aws_access_key_id=KEY,
            aws_secret_access_key=SECRET,
            # Retries are the point of a nightly job nobody watches, but not so
            # many that a broken endpoint holds the scheduler for ten minutes.
            config=Config(retries={"max_attempts": 3, "mode": "standard"},
                          connect_timeout=10, read_timeout=60),
        )
    return _client


def key_for(*parts: str) -> str:
    """A key under this product's prefix, with no empty or doubled separators."""
    bits = [PREFIX] + [str(p).strip("/") for p in parts if str(p).strip("/")]
    return "/".join(b for b in bits if b)


@dataclass
class PutResult:
    ok: bool
    key: str = ""
    bytes: int = 0
    message: str = ""


def put_file(path: Path, *parts: str, content_type: str = "") -> PutResult:
    """Copy one file up. Never raises: see the module docstring."""
    if not enabled():
        return PutResult(False, message=why_not())
    path = Path(path)
    if not path.is_file():
        return PutResult(False, message=f"There is no file at {path}.")
    key = key_for(*(parts or (path.name,)))
    extra = {"ContentType": content_type} if content_type else {}
    try:
        _s3().upload_file(str(path), BUCKET, key, ExtraArgs=extra or None)
    except Exception as exc:                            # noqa: BLE001
        log.warning("Could not upload %s to %s/%s: %s", path.name, BUCKET, key, exc)
        return PutResult(False, key=key, message=str(exc))
    size = path.stat().st_size
    log.info("Uploaded %s to %s/%s (%s bytes)", path.name, BUCKET, key, size)
    return PutResult(True, key=key, bytes=size)


def listing(*parts: str, limit: int = 100) -> list[dict]:
    """What is in the bucket under a prefix, newest first."""
    if not enabled():
        return []
    prefix = key_for(*parts)
    try:
        page = _s3().list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=limit)
    except Exception as exc:                            # noqa: BLE001
        log.warning("Could not list %s/%s: %s", BUCKET, prefix, exc)
        return []
    rows = [{"key": o["Key"], "bytes": o["Size"], "at": o["LastModified"]}
            for o in page.get("Contents", [])]
    return sorted(rows, key=lambda r: r["at"], reverse=True)


def delete(key: str) -> bool:
    if not enabled():
        return False
    try:
        _s3().delete_object(Bucket=BUCKET, Key=key)
        return True
    except Exception as exc:                            # noqa: BLE001
        log.warning("Could not delete %s/%s: %s", BUCKET, key, exc)
        return False


def check() -> dict:
    """Can we actually reach the bucket, said plainly.

    Configuration being present and the bucket being reachable are different
    claims, and the screen that tells a pharmacy it is protected must be making
    the second one.
    """
    if not enabled():
        return {"configured": False, "reachable": False, "message": why_not()}
    try:
        _s3().head_bucket(Bucket=BUCKET)
    except Exception as exc:                            # noqa: BLE001
        return {"configured": True, "reachable": False, "bucket": BUCKET,
                "endpoint": ENDPOINT,
                "message": f"The bucket {BUCKET} could not be reached: {exc}"}
    return {"configured": True, "reachable": True, "bucket": BUCKET,
            "endpoint": ENDPOINT, "prefix": PREFIX,
            "message": f"Backups are copied off this machine to {BUCKET}."}
