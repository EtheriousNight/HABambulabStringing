"""Tests for image preprocessing module."""
from __future__ import annotations

import io

import pytest

from bs_core import image


def _make_test_jpeg(width: int = 640, height: int = 480, color: tuple = (128, 128, 128)) -> bytes:
    """Create a minimal valid JPEG for testing."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_preprocess_frame_returns_bytes():
    """Preprocessing a valid JPEG returns valid JPEG bytes."""
    frame = _make_test_jpeg()
    result = image.preprocess_frame(frame)
    assert isinstance(result, bytes)
    assert len(result) > 0
    # Should be a valid JPEG (starts with JPEG magic bytes)
    assert result[:2] == b"\xff\xd8"


def test_preprocess_frame_resizes():
    """Preprocessing resizes to target dimensions."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    frame = _make_test_jpeg(1920, 1080)
    result = image.preprocess_frame(frame)
    img = Image.open(io.BytesIO(result))
    assert img.size == (image.TARGET_WIDTH, image.TARGET_HEIGHT)


def test_preprocess_frame_invalid_returns_original():
    """Invalid image data returns the original bytes unchanged."""
    invalid = b"not a jpeg at all"
    result = image.preprocess_frame(invalid)
    assert result == invalid


def test_preprocess_frame_crop_disabled():
    """With crop=False, the full image is kept (just resized)."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    frame = _make_test_jpeg(800, 600)
    result = image.preprocess_frame(frame, crop=False)
    img = Image.open(io.BytesIO(result))
    # Still resized to target
    assert img.size == (image.TARGET_WIDTH, image.TARGET_HEIGHT)


def test_preprocess_frame_enhance_disabled():
    """With enhance=False, no contrast/sharpness enhancement is applied."""
    frame = _make_test_jpeg()
    result = image.preprocess_frame(frame, enhance=False)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_get_frame_info_valid():
    """get_frame_info returns image metadata for valid JPEG."""
    frame = _make_test_jpeg(640, 480)
    info = image.get_frame_info(frame)
    assert info["width"] == 640
    assert info["height"] == 480
    assert info["mode"] == "RGB"
    assert info["size_bytes"] == len(frame)


def test_get_frame_info_invalid():
    """get_frame_info handles invalid data gracefully."""
    info = image.get_frame_info(b"invalid")
    assert "error" in info
    assert info["size_bytes"] == 7


def test_preprocess_frame_custom_target_size():
    """Custom target size is respected."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    frame = _make_test_jpeg(1920, 1080)
    result = image.preprocess_frame(frame, target_size=(512, 512))
    img = Image.open(io.BytesIO(result))
    assert img.size == (512, 512)
