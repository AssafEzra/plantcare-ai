"""The health-check image quality gate (A25).

The design decision under test is that it **warns and never rejects**. FINAL §16
documents `UNKNOWN` with a reason as the outcome for weak evidence, and hard-
rejecting an upload would put that outcome out of reach — telling a worried user
to go away and photograph their plant again rather than looking at what they sent.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from app.domain.services.image_quality import (
    BLUR_VARIANCE_FLOOR,
    MIN_LONG_EDGE,
    assess_image_quality,
    summarise,
)


def sharp_photo(size=(1200, 900)) -> Image.Image:
    """High-contrast edges, which is what a focus measure looks for."""
    image = Image.new("RGB", size, (250, 250, 250))
    draw = ImageDraw.Draw(image)
    for x in range(0, size[0], 12):
        draw.line([(x, 0), (x, size[1])], fill=(10, 60, 10), width=4)
    for y in range(0, size[1], 12):
        draw.line([(0, y), (size[0], y)], fill=(20, 20, 90), width=4)
    return image


def test_a_sharp_well_lit_photo_warns_about_nothing():
    assert assess_image_quality(sharp_photo()).warnings == []


def test_a_small_photo_is_flagged():
    small = sharp_photo((320, 240))
    warnings = assess_image_quality(small).warnings

    assert any("קטנה" in w for w in warnings)


def test_the_threshold_itself_passes():
    """The bound is a bound, not an off-by-one."""
    assert not any(
        "קטנה" in w for w in assess_image_quality(sharp_photo((MIN_LONG_EDGE, 400))).warnings
    )


def test_a_blank_photo_is_flagged_as_dark_or_uniform():
    """A wall, a hand over the lens, or a very dark room."""
    warnings = assess_image_quality(Image.new("RGB", (1200, 900), (30, 30, 30))).warnings

    assert any("כהה" in w or "אחידה" in w for w in warnings)


def test_a_blurred_photo_is_flagged():
    from PIL import ImageFilter

    blurred = sharp_photo().filter(ImageFilter.GaussianBlur(radius=12))
    warnings = assess_image_quality(blurred).warnings

    assert any("מטושטשת" in w for w in warnings)


def test_blurring_measurably_lowers_the_sharpness_score():
    """Guards the blur test from passing for the wrong reason."""
    from PIL import ImageFilter

    sharp = assess_image_quality(sharp_photo()).sharpness
    blurred = assess_image_quality(
        sharp_photo().filter(ImageFilter.GaussianBlur(radius=12))
    ).sharpness

    assert blurred < sharp
    assert blurred < BLUR_VARIANCE_FLOOR


def test_the_gate_never_rejects():
    """A25, the whole point. Even a photograph that fails every measure is usable,
    because the documented outcome for weak evidence is an UNKNOWN assessment
    that gets saved — not a refusal."""
    hopeless = Image.new("RGB", (64, 64), (0, 0, 0))
    report = assess_image_quality(hopeless)

    assert report.warnings
    assert report.is_usable


def test_the_same_problem_across_four_photos_is_said_once():
    """Four photographs with one problem should produce one sentence."""
    reports = [assess_image_quality(Image.new("RGB", (100, 100), (10, 10, 10))) for _ in range(4)]
    combined = summarise(reports)

    assert len(combined) == len(set(combined))


def test_nothing_to_report_summarises_to_nothing():
    assert summarise([assess_image_quality(sharp_photo())]) == []
