"""Image validation and derivative generation.

The theme running through these: **the file's own bytes are the only evidence.**
Filenames, extensions and declared content types all come from the client, so
every test that matters here asks whether a lie about the file can get past.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.common.errors import ImageValidationError, PayloadTooLargeError
from app.domain.services import images as svc


def make_image(
    width: int = 800,
    height: int = 600,
    fmt: str = "JPEG",
    mode: str = "RGB",
    colour=(60, 120, 80),
    **save_kwargs,
) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (width, height), colour).save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


# --- accepted formats ---------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "mime"), [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")]
)
def test_supported_formats_are_accepted(fmt: str, mime: str):
    result = svc.process(make_image(fmt=fmt))

    assert result.mime_type == mime
    assert result.width == 800
    assert result.height == 600


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
def test_unsupported_formats_are_rejected(fmt: str):
    """FINAL §20 allows JPG/JPEG/PNG/WEBP and nothing else."""
    with pytest.raises(ImageValidationError):
        svc.process(make_image(fmt=fmt))


# --- lies about the file ------------------------------------------------------


def test_a_pdf_renamed_as_a_jpeg_is_rejected():
    """The canonical upload attack: right extension, wrong contents."""
    pdf = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"

    with pytest.raises(ImageValidationError):
        svc.process(pdf, declared_mime="image/jpeg")


def test_a_declared_mime_type_cannot_smuggle_a_gif_through():
    """A browser can claim anything; the decoded format is what counts."""
    with pytest.raises(ImageValidationError):
        svc.process(make_image(fmt="GIF"), declared_mime="image/jpeg")


def test_a_wrong_but_harmless_declared_mime_does_not_reject_a_valid_image():
    """Browsers mislabel routinely. The bytes are authoritative in both directions:
    a real PNG is accepted even when the client calls it a JPEG."""
    result = svc.process(make_image(fmt="PNG"), declared_mime="image/jpeg")

    assert result.mime_type == "image/png"


def test_a_script_disguised_as_an_image_is_rejected():
    with pytest.raises(ImageValidationError):
        svc.process(b"<?php system($_GET['c']); ?>", declared_mime="image/png")


# --- size and shape -----------------------------------------------------------


def test_an_empty_file_is_rejected():
    with pytest.raises(ImageValidationError):
        svc.process(b"")


def test_an_oversized_file_is_rejected():
    """FINAL §20: 10 MB maximum."""
    with pytest.raises(PayloadTooLargeError):
        svc.process(b"\xff\xd8\xff" + b"\x00" * (svc.MAX_BYTES + 1))


def test_truncated_data_is_rejected():
    """A dropped connection mid-upload must not produce a half-image."""
    data = make_image()
    with pytest.raises(ImageValidationError):
        svc.process(data[: len(data) // 3])


def test_a_tiny_image_is_rejected():
    """A 1x1 pixel is a tracking pixel or a broken upload, not a plant photo."""
    with pytest.raises(ImageValidationError):
        svc.process(make_image(width=8, height=8))


def test_a_decompression_bomb_is_rejected():
    """A few hundred kilobytes of PNG can decode to hundreds of megapixels.

    The byte-size limit in the spec gives no protection at all against this, which
    is why there is a separate pixel budget checked from the header.
    """
    bomb = make_image(width=12000, height=12000, fmt="PNG")
    assert len(bomb) < svc.MAX_BYTES, "the point is that it passes the byte-size check"

    with pytest.raises(ImageValidationError):
        svc.process(bomb)


# --- derivatives --------------------------------------------------------------


def test_derivatives_are_produced():
    result = svc.process(make_image(width=3000, height=2000))

    assert result.original
    assert result.processed
    assert result.thumbnail


def test_the_processed_image_is_bounded():
    result = svc.process(make_image(width=4000, height=3000))

    with Image.open(io.BytesIO(result.processed)) as processed:
        assert max(processed.size) == svc.PROCESSED_MAX_EDGE


def test_the_thumbnail_is_bounded():
    result = svc.process(make_image(width=4000, height=3000))

    with Image.open(io.BytesIO(result.thumbnail)) as thumb:
        assert max(thumb.size) == svc.THUMBNAIL_MAX_EDGE


def test_aspect_ratio_is_preserved():
    result = svc.process(make_image(width=4000, height=1000))

    with Image.open(io.BytesIO(result.processed)) as processed:
        assert abs((processed.width / processed.height) - 4.0) < 0.05


def test_a_small_image_is_not_upscaled():
    """Enlarging a small photo produces blur and a larger file for no benefit."""
    result = svc.process(make_image(width=300, height=200))

    with Image.open(io.BytesIO(result.processed)) as processed:
        assert processed.size == (300, 200)


def test_derivatives_are_smaller_than_a_large_original():
    original = make_image(width=4000, height=3000, fmt="PNG")
    result = svc.process(original)

    assert len(result.processed) < len(original)
    assert len(result.thumbnail) < len(result.processed)


def test_reported_dimensions_are_of_the_original():
    result = svc.process(make_image(width=2400, height=1800))

    assert (result.width, result.height) == (2400, 1800)


# --- metadata and privacy -----------------------------------------------------


def test_exif_is_stripped_from_derivatives():
    """EXIF on a phone photo routinely carries GPS coordinates - for a plant photo,
    that is the location of someone's home (FINAL §21)."""
    buffer = io.BytesIO()
    image = Image.new("RGB", (800, 600), (10, 20, 30))
    exif = image.getexif()
    exif[0x010F] = "SecretCameraMake"
    exif[0x9003] = "2026:01:01 12:00:00"
    image.save(buffer, format="JPEG", exif=exif)

    result = svc.process(buffer.getvalue())

    with Image.open(io.BytesIO(result.processed)) as processed:
        assert not dict(processed.getexif()), "derivative retained EXIF"
    assert b"SecretCameraMake" not in result.processed
    assert b"SecretCameraMake" not in result.thumbnail


def test_the_original_is_stored_unmodified():
    """The original is retained byte-for-byte: it is the evidence an AI decision
    was based on, and rewriting it would undermine the audit trail (FINAL §20)."""
    data = make_image()
    result = svc.process(data)

    assert result.original == data


def test_exif_orientation_is_applied_before_stripping():
    """Order matters. Strip first and a portrait phone photo is stored sideways,
    because the pixels were never rotated - only tagged."""
    buffer = io.BytesIO()
    image = Image.new("RGB", (800, 400), (10, 20, 30))
    exif = image.getexif()
    exif[0x0112] = 6  # rotate 90° clockwise
    image.save(buffer, format="JPEG", exif=exif)

    result = svc.process(buffer.getvalue())

    with Image.open(io.BytesIO(result.processed)) as processed:
        assert processed.height > processed.width, "orientation tag was ignored"


# --- colour handling ----------------------------------------------------------


def test_transparency_is_composited_onto_white_not_black():
    """JPEG has no alpha. Dropping it without compositing turns transparent areas
    black, which reads as a rendering bug."""
    buffer = io.BytesIO()
    Image.new("RGBA", (800, 600), (255, 255, 255, 0)).save(buffer, format="PNG")

    result = svc.process(buffer.getvalue())

    with Image.open(io.BytesIO(result.processed)) as processed:
        assert processed.mode == "RGB"
        assert processed.getpixel((10, 10)) == pytest.approx((255, 255, 255), abs=4)


@pytest.mark.parametrize(("mode", "fmt"), [("L", "PNG"), ("CMYK", "JPEG"), ("P", "PNG")])
def test_unusual_colour_modes_are_converted(mode: str, fmt: str):
    result = svc.process(make_image(mode=mode, fmt=fmt, colour=None if mode == "P" else 128))

    with Image.open(io.BytesIO(result.processed)) as processed:
        assert processed.mode == "RGB"


def test_derivatives_are_always_jpeg():
    """Predictable output format regardless of what was uploaded."""
    result = svc.process(make_image(fmt="PNG"))

    assert result.processed_mime_type == "image/jpeg"
    with Image.open(io.BytesIO(result.processed)) as processed:
        assert processed.format == "JPEG"
