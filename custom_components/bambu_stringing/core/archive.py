"""Snapshot archive: frames, score logs and retention (sections 3/5.4).

Home Assistant free; the runtime injects the base directory
(``<config>/www/snapshots/<printer_slug>``).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def utc_timestamp() -> str:
    """Filesystem-safe UTC timestamp used in snapshot and log filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


class SnapshotArchive:
    """One instance per printer; directory layout:

    <base>/<slug>/frame_<ts>.jpg     archived frames
    <base>/<slug>/latest.jpg        newest frame (notification attachment)
    <base>/<slug>/scores_<print>.jsonl  score history per print
    """

    def __init__(
        self,
        directory: Path,
        retention_days: int,
        time_fn: Callable[[], float] = time.time,
        timestamp_fn: Callable[[], str] = utc_timestamp,
    ) -> None:
        self.directory = Path(directory)
        self.retention_days = max(1, int(retention_days))
        self._time = time_fn
        self._timestamp = timestamp_fn

    # -- frames ---------------------------------------------------------------

    def save_frame(self, data: bytes) -> Path:
        """Store one JPEG frame as timestamped file plus latest.jpg."""
        self.directory.mkdir(parents=True, exist_ok=True)
        frame_path = self.directory / f"frame_{self._timestamp()}.jpg"
        _write_atomic(frame_path, data)
        _write_atomic(self.directory / "latest.jpg", data)
        return frame_path

    # -- scores ---------------------------------------------------------------

    def append_score(self, print_id: str, record: dict[str, Any]) -> Path:
        """Append one analysis record to the per-print JSONL history."""
        self.directory.mkdir(parents=True, exist_ok=True)
        log_path = self.directory / f"scores_{print_id}.jsonl"
        record = dict(record)
        record.setdefault("ts", self._timestamp())
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return log_path

    # -- retention ------------------------------------------------------------

    def prune(self) -> int:
        """Delete archived files older than the retention window.

        Returns the number of removed files.
        """
        if not self.directory.is_dir():
            return 0
        cutoff = self._time() - self.retention_days * 86400
        removed = 0
        for path in self.directory.iterdir():
            if not path.is_file() or path.name == "latest.jpg":
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
        return removed


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
