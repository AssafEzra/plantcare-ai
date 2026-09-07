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

from app.api.dependencies import CurrentUserDep
from app.api.schemas.common import DataEnvelope
from app.api.schemas.plants import PlantImageResponse
from app.common.enums import ImageContextType, SystemEventType
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
    depicts_the_plant = context_type in (ImageContextType.GALLERY, ImageContextType.IDENTIFICATION)
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
        remaining = repo.list_images(user.client, plant_id, context=ImageContextType.GALLERY)
        replacement = remaining[0]["id"] if remaining else None
        repo.update(user.client, plant_id, {"main_image_id": replacement})

    return DataEnvelope(data={"outcome": outcome}, request_id=request.state.request_id)
