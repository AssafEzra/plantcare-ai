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
MAX_IMAGES_PER_CONTEXT = 4


def _with_urls(client_token: str, row: dict) -> PlantImageResponse:
    return PlantImageResponse(
        **row,
        thumbnail_url=storage.signed_url(client_token, row["storage_path_thumbnail"]),
        processed_url=storage.signed_url(client_token, row["storage_path_processed"]),
    )


@router.get("", response_model=DataEnvelope[list[PlantImageResponse]])
async def list_images(
    request: Request, plant_id: UUID, user: CurrentUserDep
) -> DataEnvelope[list[PlantImageResponse]]:
    repo.get(user.client, plant_id)
    found = repo.list_images(user.client, plant_id)
    return DataEnvelope(
        data=[_with_urls(user.access_token, row) for row in found],
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
    if not repo.find(user.client, plant_id):
        raise PlantNotFoundError()

    if repo.count_images(user.client, plant_id, context_type) >= MAX_IMAGES_PER_CONTEXT:
        raise ValidationFailedError(
            f"אפשר להעלות עד {MAX_IMAGES_PER_CONTEXT} תמונות.",
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

    # The first gallery image becomes the plant's main image, so a card has
    # something to show without the user having to choose (FINAL §6).
    plant = repo.get(user.client, plant_id)
    if context_type is ImageContextType.GALLERY and not plant.get("main_image_id"):
        repo.update(user.client, plant_id, {"main_image_id": str(image_id)})
        repo.record_event(
            user.client,
            user_id=user.id,
            plant_id=plant_id,
            event_type=SystemEventType.MAIN_IMAGE_CHANGED,
            payload={"image_id": str(image_id), "reason": "first_gallery_image"},
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

    plant = repo.get(user.client, plant_id)

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
