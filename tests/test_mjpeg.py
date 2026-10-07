"""Tests for the MJPEG single-frame grabber."""
from __future__ import annotations

import pytest

from bs_core.mjpeg import MJPEGGrabError, grab_jpeg

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


class FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, size):
        for chunk in self._chunks:
            yield chunk


class FakeResponse:
    def __init__(self, chunks, status=200):
        self.status = status
        self.content = FakeContent(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, chunks, status=200):
        self._chunks = chunks
        self._status = status

    def get(self, url):
        return FakeResponse(self._chunks, self._status)


async def test_grab_returns_frame_from_stream_with_garbage_prefix():
    frame = JPEG_SOI + b"jpegdata" + JPEG_EOI
    stream = b"--boundary\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n--boundary"
    session = FakeSession([stream[:20], stream[20:]])
    assert await grab_jpeg(session, "http://printer/stream") == frame


async def test_grab_handles_frame_split_across_chunks():
    head = JPEG_SOI + b"first-half-"
    tail = b"second-half" + JPEG_EOI
    session = FakeSession([b"garbage", head, tail, b"trailing"])
    assert await grab_jpeg(session, "http://printer/stream") == head + tail


async def test_grab_returns_first_complete_frame():
    frame1 = JPEG_SOI + b"one" + JPEG_EOI
    frame2 = JPEG_SOI + b"two" + JPEG_EOI
    session = FakeSession([frame1 + frame2])
    assert await grab_jpeg(session, "u") == frame1


async def test_grab_http_error_raises():
    session = FakeSession([b""], status=404)
    with pytest.raises(MJPEGGrabError):
        await grab_jpeg(session, "u")


async def test_grab_no_frame_raises():
    session = FakeSession([b"not-a-jpeg-stream"])
    with pytest.raises(MJPEGGrabError):
        await grab_jpeg(session, "u")


async def test_grab_byte_limit_raises():
    session = FakeSession([b"\x00" * 4096] * 100)
    with pytest.raises(MJPEGGrabError):
        await grab_jpeg(session, "u", max_bytes=8192)
