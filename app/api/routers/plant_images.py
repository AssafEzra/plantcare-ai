"""Image upload and removal (API_CONTRACTS §Images).

The pipeline is: validate by decoding, build derivatives, upload to Storage as
the caller, then record the metadata row. Storage first and the row second, so a
failed upload never leaves a row pointing at objects that do not exist; the
reverse ordering would need a cleanup sweep to stay consistent.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.api.schemas.plants import PlantImageResponse
from app.common.enums import (
    PORTRAIT_CONTEXTS,
    ImageContextType,
    PlantStatus,
    SystemEventType,
)
from app.common.errors import (
    NotFoundError,
    PayloadTooLargeError,
    PlantNotFoundError,
    ValidationFailedError,
)
from app.domain.services.images import MAX_BYTES, process
from app.infrastructure.storage import plant_images as storage
from app.repositories import plants as repo

router = APIRouter(prefix="/plants/{plant_id}/images", tags=["images"])

# FINAL §8 and §16 both cap a batch at four images; the gallery uses the same
# ceiling so a plant cannot accumulate an unbounded set.
# Per submission, not per plant for life. FINAL §16 allows a health check 1-4
# images and the gallery is a small set, so the number is right - but counting
# every image the plant has ever had in a context made the *second* health check
# impossible: four health images existed, so the fifth upload was refused, and
# would be refused forever. A gallery image stays counted (it is permanent by
# nature); a health or identification image stops counting once the assessment or
# identification that consumed it exists.
MAX_IMAGES_PER_CONTEXT = 4

# A plant's portraits are its gallery and identification images together, so the
# whole set is two contexts' worth. `PORTRAIT_CONTEXTS` says why they are one set.
MAX_PORTRAIT_IMAGES = MAX_IMAGES_PER_CONTEXT * len(PORTRAIT_CONTEXTS)
PORTRAIT_VALUES = {context.value for context in PORTRAIT_CONTEXTS}


def _with_urls(
    client_token: str, row: dict, signed: dict[str, str] | None = None
) -> PlantImageResponse:
    """One image with its two URLs.

    `signed` is the batch a list endpoint prepared; without it this signs the two
    itself, which is correct for a single upload and wrong for a loop - see
    `signed_urls` in the storage adapter.
    """
    if signed is None:
        signed = storage.signed_urls(
            client_token, [row["storage_path_thumbnail"], row["storage_path_processed"]]
        )
    return PlantImageResponse(
        **row,
        thumbnail_url=signed.get(row["storage_path_thumbnail"]),
        processed_url=signed.get(row["storage_path_processed"]),
    )


@router.get("", response_model=DataEnvelope[list[PlantImageResponse]])
async def list_images(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[list[PlantImageResponse]]:
    repo.get(user.client, plant_id, owner_id=user.id)
    found = repo.list_images(user.client, plant_id)
    signed = storage.signed_urls(
        user.access_token,
        [
            row[column]
            for row in found
            for column in ("storage_path_thumbnail", "storage_path_processed")
        ],
        client=user.client,
    )
    return DataEnvelope(
        data=[_with_urls(user.access_token, row, signed) for row in found],
        request_id=request.state.request_id,
    )


@router.post(
    "", response_model=DataEnvelope[PlantImageResponse], status_code=status.HTTP_201_CREATED
)
async def upload_image(
    request: Request,
    plant_id: UUID,
    user: CurrentUserDep,
    file: Annotated[UploadFile, File()],
    context_type: Annotated[ImageContextType, Form()] = ImageContextType.GALLERY,
) -> DataEnvelope[PlantImageResponse]:
    if not repo.find(user.client, plant_id, owner_id=user.id):
        raise PlantNotFoundError()

    if repo.count_uncommitted_images(user.client, plant_id, context_type) >= MAX_IMAGES_PER_CONTEXT:
        raise ValidationFailedError(
            f"אפשר לצרף עד {MAX_IMAGES_PER_CONTEXT} תמונות בכל פעם.",
            details={"max": MAX_IMAGES_PER_CONTEXT, "context": context_type.value},
        )

    # Read with a hard ceiling rather than trusting the declared length: a client
    # can send a Content-Length that does not match the body it actually streams.
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise PayloadTooLargeError()

    image = process(data, declared_mime=file.content_type)

    image_id, paths = storage.upload(
        access_token=user.access_token,
        user_id=user.id,
        plant_id=plant_id,
        context=context_type,
        image=image,
    )

    try:
        row = repo.create_image(
            user.client,
            {
                "id": str(image_id),
                "user_id": str(user.id),
                "plant_id": str(plant_id),
                "storage_path_original": paths.original,
                "storage_path_processed": paths.processed,
                "storage_path_thumbnail": paths.thumbnail,
                "mime_type": image.mime_type,
                "size_bytes": image.size_bytes,
                "width": image.width,
                "height": image.height,
                "context_type": context_type.value,
            },
        )
    except Exception:
        # The objects landed but the row did not. Remove them rather than leave
        # storage holding files nothing references.
        storage.remove(user.access_token, paths)
        raise

    # The first photograph of the whole plant becomes its main image, so a card
    # has something to show without the user having to choose (FINAL §6).
    #
    # Identification counts, and originally did not. Add Plant uploads with
    # context `identification` - it is the first photograph anyone takes, and for
    # most plants the only one - so restricting this to `gallery` meant every
    # plant created through the normal flow had no main image at all, and My
    # Plants was a grid of grey placeholders. Reported from real use.
    #
    # Health is deliberately still excluded: a health check is usually a close-up
    # of a damaged leaf, which is evidence, not a portrait. A plant whose only
    # photographs are health close-ups falls back on the read side instead.
    plant = repo.get(user.client, plant_id, owner_id=user.id)
    depicts_the_plant = context_type in PORTRAIT_CONTEXTS
    if depicts_the_plant and not plant.get("main_image_id"):
        repo.update(user.client, plant_id, {"main_image_id": str(image_id)})
        repo.record_event(
            user.client,
            user_id=user.id,
            plant_id=plant_id,
            event_type=SystemEventType.MAIN_IMAGE_CHANGED,
            payload={"image_id": str(image_id), "reason": f"first_{context_type.value}_image"},
        )

    return DataEnvelope(
        data=_with_urls(user.access_token, row), request_id=request.state.request_id
    )


@router.delete("/{image_id}", response_model=DataEnvelope[dict])
async def delete_image(
    request: Request, plant_id: UUID, image_id: UUID, user: CurrentUserDep
) -> DataEnvelope[dict]:
    """Remove an image, or hide it if AI has used it.

    FINAL §20: an AI-used image is never physically deleted. It stays for history
    and audit, hidden from the user and reachable by an administrator. The
    database enforces this too - the delete policy on `plant_images` excludes
    rows where `ai_used` - so this branch is the polite version of a rule that
    holds either way.
    """
    row = repo.get_image(user.client, image_id)
    if not row or row["plant_id"] != str(plant_id):
        raise NotFoundError("התמונה לא נמצאה.")

    plant = repo.get(user.client, plant_id, owner_id=user.id)

    # Section 20: an active plant keeps at least one photograph of itself. The
    # database enforces this too (migrations 0018 and 0019, on both the delete and the
    # hide path), so this is the polite version of a rule that holds either way - it
    # exists so the user reads a sentence rather than a constraint violation.
    if (
        row["context_type"] in PORTRAIT_VALUES
        and row["user_visible"]
        and plant["status"] == PlantStatus.ACTIVE.value
    ):
        remaining = [
            other
            for other in repo.list_images(user.client, plant_id, contexts=PORTRAIT_CONTEXTS)
            if other["id"] != str(image_id)
        ]
        if not remaining:
            raise ValidationFailedError("לצמח פעיל חייבת להישאר לפחות תמונה אחת.")

    if row.get("ai_used"):
        repo.hide_image(user.client, image_id, reason="user_requested_removal")
        outcome = "hidden"
    else:
        storage.remove(
            user.access_token,
            storage.StoredPaths(
                original=row["storage_path_original"],
                processed=row["storage_path_processed"],
                thumbnail=row["storage_path_thumbnail"],
            ),
        )
        repo.delete_image(user.client, image_id)
        outcome = "deleted"

    # A plant must not point at an image that is gone or hidden.
    if plant.get("main_image_id") == str(image_id):
        remaining = repo.list_images(user.client, plant_id, contexts=PORTRAIT_CONTEXTS)
        replacement = remaining[0]["id"] if remaining else None
        repo.update(user.client, plant_id, {"main_image_id": replacement})

    return DataEnvelope(data={"outcome": outcome}, request_id=request.state.request_id)


# --- ordering and the main image (migration spec section 20) ---------------------


class ReorderRequest(BaseModel):
    """The gallery in its new order, as image ids.

    The whole set rather than a single move: a drag reorders everything after the
    thing dragged, and sending one index would make the client responsible for
    working out which other rows shifted. Renumbering from a list is also idempotent
    - replaying it produces the same gallery.
    """

    model_config = {"extra": "forbid"}

    image_ids: list[UUID] = Field(min_length=1, max_length=MAX_PORTRAIT_IMAGES)


@router.put("/order", response_model=DataEnvelope[list[PlantImageResponse]])
async def reorder_images(
    request: Request, plant_id: UUID, payload: ReorderRequest, user: CurrentUserDep
) -> DataEnvelope[list[PlantImageResponse]]:
    """Set the gallery order.

    The request must name exactly the plant's visible portraits - gallery and
    identification images together, which is the set the dashboard draws as the
    gallery. A partial list would leave the unnamed ones at whatever number they had,
    which is how a reorder silently interleaves two sets.
    """
    repo.get(user.client, plant_id, owner_id=user.id)

    gallery = repo.list_images(user.client, plant_id, contexts=PORTRAIT_CONTEXTS)
    known = {row["id"] for row in gallery}
    asked = {str(image_id) for image_id in payload.image_ids}

    if len(asked) != len(payload.image_ids):
        raise ValidationFailedError("כל תמונה יכולה להופיע פעם אחת בלבד.")
    if asked != known:
        raise ValidationFailedError(
            "יש לציין את כל תמונות הצמח.",
            details={"expected": len(known), "received": len(asked)},
        )

    for position, image_id in enumerate(payload.image_ids, start=1):
        repo.set_image_order(user.client, image_id, position)

    return await list_images(request, plant_id, user)


@router.post("/{image_id}/main", response_model=DataEnvelope[PlantImageResponse])
async def set_main_image(
    request: Request, plant_id: UUID, image_id: UUID, user: CurrentUserDep
) -> DataEnvelope[PlantImageResponse]:
    """Promote an existing image to be the plant's main one.

    A dedicated route rather than a field on `PATCH /plants/{id}`: that model is
    `extra: forbid` and carries only the personal fields, deliberately, so that a
    client cannot set `main_image_id` to an image belonging to another plant. Here
    the image is checked against this plant before anything is written.
    """
    row = repo.get_image(user.client, image_id)
    if not row or row["plant_id"] != str(plant_id):
        raise NotFoundError("התמונה לא נמצאה.")

    repo.get(user.client, plant_id, owner_id=user.id)

    # A health image is evidence for one check - usually a close-up of a damaged
    # leaf - and is not a portrait. `upload_image` has drawn the same line since PR 27
    # when it picks the first main image; `PORTRAIT_CONTEXTS` is now the one place it
    # is drawn.
    if row["context_type"] not in PORTRAIT_VALUES or not row["user_visible"]:
        raise ValidationFailedError("אפשר לבחור תמונה ראשית מתוך תמונות הצמח בלבד.")

    repo.update(user.client, plant_id, {"main_image_id": str(image_id)})
    return DataEnvelope(
        data=_with_urls(user.access_token, row), request_id=request.state.request_id
    )
