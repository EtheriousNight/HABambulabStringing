"""Single-frame grab from a raw MJPEG stream (direct P1S camera access).

Home Assistant free: takes an ``aiohttp.ClientSession`` (or compatible).
Works without multipart boundary parsing by scanning for JPEG SOI/EOI
markers, which is robust against the P1S's raw MJPEG output.
"""
from __future__ import annotations

import asyncio
from typing import Any

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"
MAX_FRAME_BYTES = 10 * 1024 * 1024


class MJPEGGrabError(Exception):
    """Raised when no complete JPEG frame could be read from the stream."""


async def grab_jpeg(
    session: Any,
    url: str,
    *,
    timeout: float = 10.0,
    max_bytes: int = MAX_FRAME_BYTES,
) -> bytes:
    """Read the first complete JPEG frame from an MJPEG HTTP stream."""
    buffer = bytearray()
    async with asyncio.timeout(timeout):
        async with session.get(url) as resp:
            if resp.status != 200:
                raise MJPEGGrabError(f"stream returned HTTP {resp.status}")
            async for chunk in resp.content.iter_chunked(4096):
                buffer.extend(chunk)
                start = buffer.find(JPEG_SOI)
                if start != -1:
                    end = buffer.find(JPEG_EOI, start)
                    if end != -1:
                        return bytes(buffer[start : end + 2])
                if len(buffer) > max_bytes:
                    raise MJPEGGrabError("no JPEG frame within byte limit")
    raise MJPEGGrabError("stream ended without a JPEG frame")
