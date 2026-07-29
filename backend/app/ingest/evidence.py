"""Evidence resolution.

A CamView evidence drop is a set of per-modality folders (ZI, CD, NP, INM, TP,
MD, CT) of JPGs named '{AlarmID}_{dssId}.jpg'. The folder is indexed once into an
Alarm ID -> file map so linking a sheet of alerts is a dictionary lookup rather
than a directory scan per row.
"""
from __future__ import annotations

from pathlib import Path

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov"}


def _alarm_id_from_filename(name: str) -> str:
    # '{AlarmID}_{dssId}.ext' -> AlarmID  (AlarmID itself contains hyphens, no '_')
    stem = name.rsplit(".", 1)[0]
    return stem.rsplit("_", 1)[0] if "_" in stem else stem


class EvidenceIndex:
    """Maps Alarm ID -> on-disk evidence paths for one exam's evidence root."""

    def __init__(self, root: Path):
        self.root = root
        self.images: dict[str, Path] = {}
        self.videos: dict[str, Path] = {}
        if root and root.exists():
            self._scan()

    def _scan(self) -> None:
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in _IMAGE_SUFFIXES:
                self.images.setdefault(_alarm_id_from_filename(path.name), path)
            elif suffix in _VIDEO_SUFFIXES:
                self.videos.setdefault(_alarm_id_from_filename(path.name), path)

    def image_for(self, alarm_id: str) -> Path | None:
        return self.images.get(alarm_id)

    def video_for(self, alarm_id: str) -> Path | None:
        return self.videos.get(alarm_id)

    @property
    def image_count(self) -> int:
        return len(self.images)
