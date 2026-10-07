"""Tests for the snapshot archive (frames, score logs, retention)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bs_core.archive import SnapshotArchive


@pytest.fixture()
def archive(tmp_path: Path) -> SnapshotArchive:
    ts = iter(["20260918-080000", "20260918-080100", "20260918-080200"])
    return SnapshotArchive(
        tmp_path / "p1s",
        retention_days=14,
        time_fn=lambda: 1_000_000.0,
        timestamp_fn=lambda: next(ts),
    )


def test_save_frame_writes_timestamped_file_and_latest(archive, tmp_path):
    data = b"\xff\xd8frame-bytes\xff\xd9"
    path = archive.save_frame(data)
    assert path.name == "frame_20260918-080000.jpg"
    assert path.read_bytes() == data
    latest = tmp_path / "p1s" / "latest.jpg"
    assert latest.read_bytes() == data
    # no leftover temp files
    assert not list((tmp_path / "p1s").glob("*.tmp"))


def test_append_score_writes_jsonl(archive):
    log = archive.append_score(
        "20260918-075500",
        {"stringing_score": 60, "spaghetti_score": 5, "observations": "Fäden."},
    )
    assert log.name == "scores_20260918-075500.jsonl"
    archive.append_score(
        "20260918-075500",
        {"stringing_score": 65, "spaghetti_score": 5, "observations": "Mehr Fäden."},
    )
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["stringing_score"] == 60
    assert "ts" in first


def test_prune_removes_old_files_keeps_latest(archive, tmp_path):
    old_frame = tmp_path / "p1s" / "frame_old.jpg"
    old_log = tmp_path / "p1s" / "scores_old.jsonl"
    latest = tmp_path / "p1s" / "latest.jpg"
    for path in (old_frame, old_log, latest):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    day = 86400
    old = 1_000_000.0 - (archive.retention_days * day + 10)
    for path in (old_frame, old_log, latest):
        os.utime(path, (old, old))
    removed = archive.prune()
    assert removed == 2
    assert not old_frame.exists()
    assert not old_log.exists()
    assert latest.exists()


def test_prune_keeps_recent_files(archive, tmp_path):
    recent = tmp_path / "p1s" / "frame_recent.jpg"
    recent.parent.mkdir(parents=True, exist_ok=True)
    recent.write_bytes(b"x")
    assert archive.prune() == 0
    assert recent.exists()


def test_prune_empty_directory(tmp_path):
    archive = SnapshotArchive(tmp_path / "missing", retention_days=1)
    assert archive.prune() == 0
