"""Image quality for a health check (A25).

FINAL §16 puts "image quality validation" in the Health Check flow but names no
kind of check and no threshold, so both are recorded here.

**It warns; it does not reject.** That is the whole design decision. A blurred
photograph of a genuinely sick plant is weak evidence, and the specification
already has a place for weak evidence: an `UNKNOWN` assessment with a reason,
saved rather than discarded. Hard-rejecting the upload would block the user from
reaching that documented outcome and would tell them to go away and take a better
photograph of a plant they are worried about right now.

Deterministic and local: decoded dimensions and a Laplacian-style variance for
focus. No model, because "is this photograph sharp?" is arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageFilter, ImageStat

# Below this on the long edge there is not enough detail for leaf texture to
# survive, whatever the model. Well under the 1600px the pipeline produces, so
# only a genuinely small original trips it.
MIN_LONG_EDGE = 480

# The standard cheap focus measure: variance of an edge-detected image. The floor
# is measured rather than guessed — a sharp photograph scores in the hundreds or
# thousands, a visibly blurred one under ten, and a flat surface zero. Twenty is
# deliberately conservative: a false "blurred" warning costs the user a sentence
# they can ignore, and a false pass costs nothing at all, because the agent judges
# the evidence itself.
BLUR_VARIANCE_FLOOR = 20.0

# Pixels trimmed from each edge before measuring. `FIND_EDGES` paints a bright
# border on every image, and those few thousand extreme pixels dominate the
# statistic: an untrimmed flat grey rectangle scored *higher* than a heavily
# blurred photograph, which made the measure worse than useless. Trimming makes
# it monotonic — which is the property a threshold needs.
_EDGE_ARTEFACT_MARGIN = 3

# A photograph that is nearly all one tone is usually a wall, a hand over the
# lens, or a very dark room.
MIN_CONTRAST_STDDEV = 12.0


@dataclass(frozen=True)
class QualityReport:
    """What is wrong with a photograph, if anything. Never a refusal."""

    warnings: list[str] = field(default_factory=list)
    long_edge: int = 0
    sharpness: float = 0.0
    contrast: float = 0.0

    @property
    def is_usable(self) -> bool:
        """Always true. Kept as a property so the intent is visible at call sites.

        A25: the gate warns rather than blocks, because the `UNKNOWN` outcome is
        the documented home for weak evidence and blocking would put it out of
        reach.
        """
        return True

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


def assess_image_quality(image: Image.Image) -> QualityReport:
    """Measure a decoded image. Never raises, never rejects."""
    warnings: list[str] = []

    long_edge = max(image.size)
    if long_edge < MIN_LONG_EDGE:
        warnings.append("התמונה קטנה מדי לזיהוי סימנים עדינים על העלים.")

    grey = image.convert("L")

    contrast = float(ImageStat.Stat(grey).stddev[0])
    if contrast < MIN_CONTRAST_STDDEV:
        warnings.append("התמונה כהה או אחידה מדי. כדאי לצלם באור יום.")

    # Variance of the Laplacian: an edge filter, then how much the result varies.
    # A sharp image has strong edges and therefore high variance; a blurred one
    # has neither.
    sharpness = _sharpness(grey)
    if sharpness < BLUR_VARIANCE_FLOOR:
        warnings.append("התמונה נראית מטושטשת. תמונה חדה יותר תעזור לאבחן טוב יותר.")

    return QualityReport(
        warnings=warnings,
        long_edge=long_edge,
        sharpness=sharpness,
        contrast=contrast,
    )


def _sharpness(grey: Image.Image) -> float:
    """Variance of the edge-detected image, with the border artefact removed."""
    edges = grey.filter(ImageFilter.FIND_EDGES)
    width, height = edges.size
    margin = _EDGE_ARTEFACT_MARGIN
    if width > 2 * margin and height > 2 * margin:
        edges = edges.crop((margin, margin, width - margin, height - margin))
    return float(ImageStat.Stat(edges).stddev[0]) ** 2


def summarise(reports: list[QualityReport]) -> list[str]:
    """One deduplicated list of advice across a batch.

    Four photographs with the same problem should produce one sentence, not four.
    """
    seen: dict[str, None] = {}
    for report in reports:
        for warning in report.warnings:
            seen.setdefault(warning, None)
    return list(seen)
