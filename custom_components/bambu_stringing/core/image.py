"""Image preprocessing for better defect detection.

Enhances chamber frames before sending to the vision model:
- Crops to the print bed area (removes irrelevant top of image)
- Normalizes size for consistent token usage
- Enhances contrast and sharpness (makes stringing more visible)
- Reduces noise
"""
from __future__ import annotations

import io
import logging

LOGGER = logging.getLogger(__name__)

# Target dimensions for the vision model (4:3 aspect ratio, good balance)
TARGET_WIDTH = 1024
TARGET_HEIGHT = 768

# Crop region: focus on the print bed area
# Typical Bambu Lab chamber camera: bed is in lower 2/3 of frame
CROP_TOP_RATIO = 0.25      # Remove top 25% (ceiling, lights)
CROP_BOTTOM_RATIO = 0.95   # Keep up to 95% (remove bottom edge artifacts)
CROP_LEFT_RATIO = 0.05     # Small margin left
CROP_RIGHT_RATIO = 0.95    # Small margin right

# Enhancement factors
CONTRAST_FACTOR = 1.15     # Slight contrast boost
SHARPNESS_FACTOR = 1.3     # Sharpen to make strings visible
BRIGHTNESS_FACTOR = 1.05   # Slight brightness boost

# JPEG quality for re-encoded images
JPEG_QUALITY = 90


def preprocess_frame(
    frame: bytes,
    *,
    target_size: tuple[int, int] = (TARGET_WIDTH, TARGET_HEIGHT),
    crop: bool = True,
    enhance: bool = True,
) -> bytes:
    """Preprocess a JPEG frame for better defect detection.

    Args:
        frame: Raw JPEG bytes from the camera
        target_size: Target (width, height) for the output image
        crop: Whether to crop to the print bed area
        enhance: Whether to apply contrast/sharpness enhancement

    Returns:
        Preprocessed JPEG bytes

    Raises:
        ValueError: If the frame cannot be processed (corrupt, wrong format)
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError as err:
        LOGGER.warning("Pillow not installed, returning original frame: %s", err)
        return frame

    try:
        img = Image.open(io.BytesIO(frame))

        # Convert to RGB if necessary (handles RGBA, P mode, etc.)
        if img.mode != "RGB":
            img = img.convert("RGB")

        width, height = img.size

        # 1. Crop to print bed area
        if crop:
            left = int(width * CROP_LEFT_RATIO)
            top = int(height * CROP_TOP_RATIO)
            right = int(width * CROP_RIGHT_RATIO)
            bottom = int(height * CROP_BOTTOM_RATIO)
            img = img.crop((left, top, right, bottom))

        # 2. Resize to target dimensions
        img = img.resize(target_size, Image.Resampling.LANCZOS)

        # 3. Enhance for better defect visibility
        if enhance:
            # Slight unsharp mask to make fine strings more visible
            img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=80, threshold=2))

            # Contrast enhancement
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(CONTRAST_FACTOR)

            # Sharpness enhancement
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(SHARPNESS_FACTOR)

            # Slight brightness boost
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(BRIGHTNESS_FACTOR)

        # 4. Save as JPEG
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        result = buf.getvalue()

        LOGGER.debug(
            "Preprocessed frame: %dx%d -> %dx%d, %d -> %d bytes",
            width, height, target_size[0], target_size[1],
            len(frame), len(result),
        )

        return result

    except Exception as err:
        LOGGER.warning("Failed to preprocess frame, using original: %s", err)
        return frame


def get_frame_info(frame: bytes) -> dict:
    """Get basic info about a frame without full decode."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(frame))
        return {
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
            "format": img.format,
            "size_bytes": len(frame),
        }
    except Exception:
        return {"size_bytes": len(frame), "error": "cannot parse"}
