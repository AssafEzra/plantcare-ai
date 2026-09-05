"""Supabase Storage adapter for plant images.

Object keys follow FINAL §20:

    {user_id}/{plant_id}/{gallery|identification|health}/{image_id}-{variant}.jpg

inside the private `plant-images` bucket. The first path segment is the owning
user's id, which is exactly what the storage policies key on — so the layout is
not merely tidy, it is what makes owner-only access enforceable.

Reads go through short-lived signed URLs. The bucket is private, so a URL that
leaks is useless within minutes, and no plant photograph is ever addressable by a
guessable public path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

from app.common.enums import ImageContextType
from app.common.errors import UpstreamUnavailableError
from app.config.settings import get_settings
from app.domain.services.images import ProcessedImage
from app.infrastructure.supabase.client import service_client, user_client

# Long enough to load a page, short enough that a leaked URL is quickly worthless.
SIGNED_URL_TTL_SECONDS: Final = 300


@dataclass(frozen=True)
class StoredPaths:
    original: str
    processed: str
    thumbnail: str


def _prefix(user_id: UUID, plant_id: UUID, context: ImageContextType) -> str:
    return f"{user_id}/{plant_id}/{context.value}"


def build_paths(
    user_id: UUID, plant_id: UUID, context: ImageContextType, image_id: UUID
) -> StoredPaths:
    base = f"{_prefix(user_id, plant_id, context)}/{image_id}"
    return StoredPaths(
        original=f"{base}-original",
        processed=f"{base}-processed.jpg",
        thumbnail=f"{base}-thumb.jpg",
    )


def upload(
    *,
    access_token: str,
    user_id: UUID,
    plant_id: UUID,
    context: ImageContextType,
    image: ProcessedImage,
    image_id: UUID | None = None,
) -> tuple[UUID, StoredPaths]:
    """Upload the three variants as the calling user.

    Deliberately uses the caller's own client rather than the service role: the
    storage policies then apply, so a bug in path construction is refused by the
    database instead of quietly writing into another user's namespace.
    """
    image_id = image_id or uuid4()
    paths = build_paths(user_id, plant_id, context, image_id)
    client = user_client(access_token)
    bucket = client.storage.from_(get_settings().supabase_storage_bucket)

    variants = [
        (paths.original, image.original, image.mime_type),
        (paths.processed, image.processed, image.processed_mime_type),
        (paths.thumbnail, image.thumbnail, image.processed_mime_type),
    ]

    written: list[str] = []
    try:
        for path, payload, content_type in variants:
            bucket.upload(path, payload, {"content-type": content_type, "upsert": "false"})
            written.append(path)
    except Exception as exc:
        # A half-written set would leave a plant_images row pointing at objects
        # that do not all exist. Roll back what landed before re-raising, so the
        # caller can fail cleanly rather than record a broken reference.
        _best_effort_remove(access_token, written)
        raise UpstreamUnavailableError("שמירת התמונה נכשלה. אפשר לנסות שוב.") from exc

    return image_id, paths


def _best_effort_remove(access_token: str, paths: list[str]) -> None:
    if not paths:
        return
    try:
        client = user_client(access_token)
        client.storage.from_(get_settings().supabase_storage_bucket).remove(paths)
    except Exception:
        # Cleanup must not mask the original failure.
        pass


def signed_url(access_token: str, path: str, *, ttl: int = SIGNED_URL_TTL_SECONDS) -> str | None:
    """A short-lived URL for one stored object, or None if it cannot be signed.

    Signed as the calling user, so RLS decides whether the object is theirs to
    read. Returning None rather than raising lets a gallery render the images it
    can and skip the rest, instead of failing the whole page over one object.
    """
    client = user_client(access_token)
    bucket = client.storage.from_(get_settings().supabase_storage_bucket)
    try:
        result = bucket.create_signed_url(path, ttl)
    except Exception:
        return None
    return result.get("signedURL") or result.get("signedUrl")


def remove(access_token: str, paths: StoredPaths) -> None:
    """Delete all three variants.

    Only ever called for an image never used by AI. FINAL §20 requires AI-used
    images to be retained for history and audit and merely hidden from the user;
    that rule lives in the image service, and the database enforces it too - the
    RLS delete policy on `plant_images` excludes rows where `ai_used`.
    """
    client = user_client(access_token)
    bucket = client.storage.from_(get_settings().supabase_storage_bucket)
    bucket.remove([paths.original, paths.processed, paths.thumbnail])


def admin_signed_url(path: str, *, ttl: int = SIGNED_URL_TTL_SECONDS) -> str | None:
    """Sign a URL with the service role, for retained AI-used images.

    FINAL §20 gives administrators access to images hidden from their owner. This
    bypasses RLS, so it must only ever be reached from a route already behind
    `require_admin`.
    """
    bucket = service_client().storage.from_(get_settings().supabase_storage_bucket)
    try:
        result = bucket.create_signed_url(path, ttl)
    except Exception:
        return None
    return result.get("signedURL") or result.get("signedUrl")
