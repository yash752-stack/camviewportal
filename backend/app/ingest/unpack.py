"""Evidence intake: loose files, or a zip the server unpacks itself.

A real evidence drop is one image per alarm — 108 files for a small exam, tens
of thousands for a full one — so operators export it as a zip. Uploading the
zip used to silently do nothing: the form filtered on media suffixes and a
`.zip` simply fell on the floor with no error.

Unpacking untrusted archives has three well-known ways to go wrong, and all
three are handled here rather than trusted away:

  * path traversal ("zip slip") — a member named `../../etc/passwd` writing
    outside the target. Every member is resolved and checked against the
    destination before a byte is written.
  * decompression bombs — a few KB expanding to gigabytes. Both the per-member
    and the total uncompressed size are capped, using the sizes declared in
    the central directory AND the bytes actually written, since the declared
    ones are attacker-controlled.
  * the archive being something else entirely. Only media members are ever
    extracted; anything else is skipped and counted.

Nesting is not flattened. EvidenceIndex scans with rglob and keys purely on
the filename, so per-modality folders inside the zip index exactly like a flat
drop, and keeping them preserves whatever structure the operator exported.
"""
from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Iterable

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov"}
MEDIA_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES
ARCHIVE_SUFFIXES = {".zip"}

MAX_MEMBER_BYTES = 512 * 1024 * 1024          # one frame or clip
MAX_TOTAL_BYTES = 20 * 1024 * 1024 * 1024     # whole drop
MAX_MEMBERS = 200_000


@dataclass
class UnpackResult:
    media: int = 0                 # media files now on disk
    archives: int = 0              # zips opened
    skipped_nonmedia: int = 0      # members ignored (readme, .csv, ...)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.media > 0


def is_archive(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in ARCHIVE_SUFFIXES


def _safe_target(dest: Path, member: str) -> Path | None:
    """Resolve a member against dest, refusing anything that escapes it."""
    name = member.replace("\\", "/")
    if name.endswith("/"):
        return None                                   # directory entry
    candidate = (dest / name).resolve()
    try:
        candidate.relative_to(dest.resolve())
    except ValueError:
        return None                                   # zip slip
    return candidate


def extract_zip(src: IO[bytes] | Path, dest: Path, result: UnpackResult,
                budget: list[int] | None = None) -> None:
    """Extract media members of one archive into dest, in place."""
    dest.mkdir(parents=True, exist_ok=True)
    remaining = budget if budget is not None else [MAX_TOTAL_BYTES]
    try:
        zf = zipfile.ZipFile(src)
    except (zipfile.BadZipFile, OSError) as e:
        result.errors.append(f"not a readable zip: {e}")
        return
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            result.errors.append(f"archive has {len(infos):,} entries (limit {MAX_MEMBERS:,})")
            return
        result.archives += 1
        for info in infos:
            target = _safe_target(dest, info.filename)
            if target is None:
                if not info.filename.endswith("/"):
                    result.errors.append(f"refused unsafe path: {info.filename}")
                continue
            if target.suffix.lower() not in MEDIA_SUFFIXES:
                result.skipped_nonmedia += 1
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                result.errors.append(f"{info.filename}: {info.file_size:,} bytes exceeds member limit")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                with zf.open(info) as fsrc, target.open("wb") as fdst:
                    while chunk := fsrc.read(1 << 20):
                        written += len(chunk)
                        # trust the bytes, not the declared size
                        if written > MAX_MEMBER_BYTES or written > remaining[0]:
                            raise ValueError("size limit exceeded during extraction")
                        fdst.write(chunk)
            except (ValueError, zipfile.BadZipFile, OSError) as e:
                target.unlink(missing_ok=True)
                result.errors.append(f"{info.filename}: {e}")
                continue
            remaining[0] -= written
            result.media += 1


def collect_evidence(uploads: Iterable, dest: Path) -> UnpackResult:
    """Save an evidence upload set: loose media kept, zips unpacked.

    `uploads` are Starlette UploadFile-likes (.filename, .file). Mixed sets are
    fine — an operator can drop two zips and a handful of stragglers.
    """
    result = UnpackResult()
    dest.mkdir(parents=True, exist_ok=True)
    budget = [MAX_TOTAL_BYTES]
    for uf in uploads:
        name = getattr(uf, "filename", "") or ""
        if not name:
            continue
        suffix = Path(name).suffix.lower()
        if suffix in ARCHIVE_SUFFIXES:
            extract_zip(uf.file, dest, result, budget)
        elif suffix in MEDIA_SUFFIXES:
            # a directory upload carries relative paths; keep only the leaf so
            # two folders with the same frame name cannot collide on a path
            target = dest / Path(name.replace("\\", "/")).name
            with target.open("wb") as f:
                shutil.copyfileobj(uf.file, f)
            result.media += 1
        else:
            result.skipped_nonmedia += 1
    return result
