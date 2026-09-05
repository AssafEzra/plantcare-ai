"""Image validation and derivative generation.

Spec: FINAL_SPECIFICATION §20 (images and storage), DATABASE_SCHEMA `plant_images`.

Validation decodes the file
---------------------------
The declared content type and the filename extension are both attacker-controlled
and are never trusted. A file is an image only if Pillow can actually decode it,
and its format is whatever Pillow reports — not what the request claimed. This is
the difference between "the client said JPEG" and "this is a JPEG".

Decompression bombs
-------------------
A few hundred kilobytes of PNG can decode to hundreds of megapixels and exhaust
memory. The byte-size limit in the spec does not protect against that at all, so
there is an explicit pixel budget as well, checked from the header before the
image is ever fully decoded.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final, NoReturn

from PIL import Image, ImageOps, UnidentifiedImageError

from app.common.errors import ImageValidationError, PayloadTooLargeError

# FINAL §20: JPG/JPEG/PNG/WEBP, maximum 10 MB per image.
MAX_BYTES: Final = 10 * 1024 * 1024
ALLOWED_FORMATS: Final = frozenset({"JPEG", "PNG", "WEBP"})
MIME_BY_FORMAT: Final = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}

# A6: the spec fixes neither dimension, so these are the recorded choices.
PROCESSED_MAX_EDGE: Final = 1600
THUMBNAIL_MAX_EDGE: Final = 400
JPEG_QUALITY: Final = 85

# Roughly a 46-megapixel photograph, comfortably above any phone camera and far
# below what a decompression bomb needs to hurt us. Pillow's own default limit is
# ~89 megapixels and only warns; this is a hard rejection.
MAX_PIXELS: Final = 46_000_000

# Smaller than this cannot be a useful plant photograph, and is usually a
# tracking pixel or a truncated upload.
MIN_EDGE: Final = 64

# Pillow only *warns* at its own ~89 megapixel threshold and decodes anyway.
# Lowering it to our budget makes the library refuse outright, so a bomb is
# stopped even on a code path that forgets to call validate() first.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass(frozen=True)
class ProcessedImage:
    """One uploaded image plus the derivatives that get stored alongside it."""

    original: bytes
    processed: bytes
    thumbnail: bytes
    mime_type: str
    width: int
    height: int
    size_bytes: int

    @property
    def processed_mime_type(self) -> str:
        # Derivatives are always JPEG - see `_encode`.
        return "image/jpeg"


def _reject(message: str) -> NoReturn:
    raise ImageValidationError(message)


def _open(data: bytes) -> Image.Image:
    """Decode, or raise. Rejects anything Pillow cannot identify as an image."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except UnidentifiedImageError:
        _reject("הקובץ אינו תמונה תקינה.")
    except Image.DecompressionBombError as exc:
        raise ImageValidationError("רזולוציית התמונה גבוהה מדי.") from exc
    except OSError as exc:
        # Truncated or corrupt data surfaces here rather than as a clean
        # UnidentifiedImageError.
        raise ImageValidationError("התמונה פגומה או חלקית.") from exc
    return image


def validate(data: bytes, *, declared_mime: str | None = None) -> Image.Image:
    """Validate raw bytes and return the decoded image.

    `declared_mime` is accepted only so a mismatch can be *reported*; it never
    decides whether the file is acceptable.
    """
    if not data:
        _reject("הקובץ ריק.")

    if len(data) > MAX_BYTES:
        raise PayloadTooLargeError(
            f"התמונה גדולה מדי. הגודל המרבי הוא {MAX_BYTES // (1024 * 1024)}MB."
        )

    # Read the header first so a bomb is rejected before it is decoded.
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            width, height = probe.size
    except UnidentifiedImageError:
        _reject("הקובץ אינו תמונה תקינה.")
    except Image.DecompressionBombError as exc:
        # Pillow refuses before decoding, which is the earliest possible point.
        raise ImageValidationError("רזולוציית התמונה גבוהה מדי.") from exc
    except OSError as exc:
        raise ImageValidationError("התמונה פגומה או חלקית.") from exc

    if fmt not in ALLOWED_FORMATS:
        # Reported as the *actual* format, which is what makes a renamed file
        # legible in the logs rather than mysterious.
        _reject("סוג הקובץ אינו נתמך. אפשר להעלות JPG, PNG או WEBP.")

    if width * height > MAX_PIXELS:
        _reject("רזולוציית התמונה גבוהה מדי.")

    if width < MIN_EDGE or height < MIN_EDGE:
        _reject(f"התמונה קטנה מדי. נדרשים לפחות {MIN_EDGE} פיקסלים בכל צד.")

    # A mismatch between `declared_mime` and the decoded format is deliberately
    # not an error: browsers mislabel routinely, and the decoded format has
    # already been checked against the allow-list above. The declared value is
    # never consulted for the decision.

    return _open(data)


def _flatten(image: Image.Image) -> Image.Image:
    """Convert to RGB, compositing any transparency onto white.

    Derivatives are JPEG, which has no alpha channel. Discarding it without
    compositing turns transparent regions black, which looks like a rendering bug
    rather than a design choice.
    """
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    if image.mode != "RGB":
        # Covers greyscale, CMYK and palette images.
        return image.convert("RGB")
    return image


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    # No `exif=` argument, so the derivative carries none. EXIF routinely holds
    # GPS coordinates for a photo of someone's home (FINAL §21 privacy).
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return buffer.getvalue()


def _resized(image: Image.Image, max_edge: int) -> Image.Image:
    copy = image.copy()
    # thumbnail() preserves aspect ratio and never enlarges, so a small image is
    # left alone rather than upscaled into blur.
    copy.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return copy


def process(data: bytes, *, declared_mime: str | None = None) -> ProcessedImage:
    """Validate an upload and build its processed and thumbnail derivatives."""
    image = validate(data, declared_mime=declared_mime)
    source_format = image.format or "JPEG"

    with image:
        # Apply the EXIF orientation, then drop the metadata. Doing it in this
        # order matters: strip first and a phone photo taken in portrait is stored
        # sideways, because the pixels were never rotated - only tagged.
        oriented = ImageOps.exif_transpose(image) or image
        flat = _flatten(oriented)

        width, height = flat.size
        processed = _encode(_resized(flat, PROCESSED_MAX_EDGE))
        thumbnail = _encode(_resized(flat, THUMBNAIL_MAX_EDGE))

    return ProcessedImage(
        original=data,
        processed=processed,
        thumbnail=thumbnail,
        mime_type=MIME_BY_FORMAT.get(source_format, "image/jpeg"),
        width=width,
        height=height,
        size_bytes=len(data),
    )
