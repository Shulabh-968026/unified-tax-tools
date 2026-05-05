"""File-storage primitive — the Client Library's backing store.

Today we keep files on disk under `/app/uploads/...`.  Tomorrow this same
class can be swapped for an S3 / R2 implementation without touching any
caller — both `save` and `read` are agnostic to physical location.

Layout (deterministic, tenant-safe):

    /app/uploads/
      └── {firm_id}/
          └── {client_id}/
              └── {period}/
                  └── {division or "_"}/
                      └── {file_type}/
                          └── v{version_no}/
                              └── {checksum}__{original_filename}

The `checksum__` prefix avoids collisions when the auditor uploads two
files with the same name (and lets us de-duplicate identical content
trivially — same checksum = same path).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

UPLOAD_ROOT = Path(os.environ.get("ASSUREAI_UPLOAD_ROOT", "/app/uploads"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_storage_path(
    *,
    firm_id: str,
    client_id: str,
    period: str,
    division: str | None,
    file_type: str,
    version_no: int,
    checksum: str,
    original_filename: str,
) -> str:
    """Return the path *relative to* `UPLOAD_ROOT`.

    Storing the relative form means we can move `UPLOAD_ROOT` (e.g. to an
    S3 bucket, mounted volume, etc.) without rewriting database rows.
    """
    safe_name = original_filename.replace("/", "_").replace("\\", "_")
    return str(
        Path(firm_id)
        / client_id
        / period
        / (division or "_")
        / file_type
        / f"v{version_no}"
        / f"{checksum[:12]}__{safe_name}"
    )


def save_blob(rel_path: str, content: bytes) -> None:
    """Write `content` to `UPLOAD_ROOT / rel_path` (creates parents)."""
    abs_path = UPLOAD_ROOT / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)


def read_blob(rel_path: str) -> bytes:
    return (UPLOAD_ROOT / rel_path).read_bytes()


def delete_blob(rel_path: str) -> None:
    """Hard-delete the file from disk (used only after soft-delete grace)."""
    p = UPLOAD_ROOT / rel_path
    if p.exists():
        p.unlink()


def blob_exists(rel_path: str) -> bool:
    return (UPLOAD_ROOT / rel_path).exists()
