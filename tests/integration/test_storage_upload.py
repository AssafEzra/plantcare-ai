"""Storage adapter against the real DEV bucket.

The unit tests prove the bytes are handled correctly. These prove the parts that
only exist against a live Supabase: that uploads land under the owner's prefix,
that signed URLs actually resolve, and that the storage policies refuse a
cross-user write rather than merely being declared.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator

import httpx
import pytest

from app.common.enums import ImageContextType
from app.common.errors import UpstreamUnavailableError
from app.domain.services.images import process
from app.infrastructure.storage import plant_images as storage
from tests.integration.conftest import delete_accounts
from tests.unit.test_image_processing import make_image

pytestmark = pytest.mark.integration

PASSWORD = "Storage-Passw0rd!"


def _load_env() -> bool:
    path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    return bool(os.environ.get("SUPABASE_URL"))


@pytest.fixture(scope="module")
def live_env() -> None:
    if not _load_env():
        pytest.skip("no .env with DEV credentials")
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()


@pytest.fixture(scope="module")
def admin_sdk(live_env):
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


@pytest.fixture
def account(admin_sdk) -> Iterator:
    """A confirmed user with a plant, signed in. Cleaned up afterwards."""
    from supabase import create_client

    created: list[str] = []
    uploaded: list[str] = []

    def _make():
        email = f"stor-{uuid.uuid4().hex[:12]}@example.com"
        user = admin_sdk.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user
        created.append(user.id)

        plant = (
            admin_sdk.table("plants")
            .insert({"user_id": user.id, "status": "PENDING_IDENTIFICATION"})
            .execute()
        )
        anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
        token = anon.auth.sign_in_with_password(
            {"email": email, "password": PASSWORD}
        ).session.access_token

        return uuid.UUID(user.id), uuid.UUID(plant.data[0]["id"]), token, uploaded

    yield _make

    bucket = admin_sdk.storage.from_("plant-images")
    if uploaded:
        with contextlib.suppress(Exception):
            bucket.remove(uploaded)
    delete_accounts(admin_sdk, created)


def _upload(account_factory, context=ImageContextType.GALLERY):
    user_id, plant_id, token, uploaded = account_factory()
    image = process(make_image(width=1200, height=900))
    image_id, paths = storage.upload(
        access_token=token,
        user_id=user_id,
        plant_id=plant_id,
        context=context,
        image=image,
    )
    uploaded.extend([paths.original, paths.processed, paths.thumbnail])
    return user_id, plant_id, token, image_id, paths


# --- upload -------------------------------------------------------------------


def test_all_three_variants_are_uploaded(account):
    _, _, token, _, paths = _upload(account)

    for path in (paths.original, paths.processed, paths.thumbnail):
        assert storage.signed_url(token, path), f"{path} was not stored"


def test_objects_land_under_the_owners_prefix(account):
    """The first path segment is what the storage policies key on, so this layout
    is what makes owner-only access enforceable rather than merely tidy."""
    user_id, plant_id, _, _, paths = _upload(account)

    assert paths.original.startswith(f"{user_id}/{plant_id}/gallery/")


@pytest.mark.parametrize(
    "context", [ImageContextType.GALLERY, ImageContextType.IDENTIFICATION, ImageContextType.HEALTH]
)
def test_each_context_has_its_own_folder(account, context: ImageContextType):
    """FINAL §20 fixes the {gallery|identification|health} segment."""
    _, _, _, _, paths = _upload(account, context)

    assert f"/{context.value}/" in paths.original


def test_a_signed_url_actually_serves_the_image(account):
    """A URL that is generated but does not resolve is worse than none."""
    _, _, token, _, paths = _upload(account)

    url = storage.signed_url(token, paths.thumbnail)
    response = httpx.get(url, timeout=30, follow_redirects=True)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")
    assert len(response.content) > 0


def test_the_bucket_is_not_publicly_readable(account):
    """Without a signature the object must not be served: a private bucket is what
    keeps a plant photo from being addressable by a guessable path."""
    _, _, token, _, paths = _upload(account)

    signed = storage.signed_url(token, paths.thumbnail)
    unsigned = signed.split("?")[0]

    assert httpx.get(unsigned, timeout=30, follow_redirects=True).status_code >= 400


# --- isolation ----------------------------------------------------------------


def test_a_user_cannot_write_into_another_users_prefix(account):
    """The storage policy, exercised rather than declared."""
    _, _, alice_token, _ = account()
    bob_id, bob_plant, _, _ = account()
    image = process(make_image())

    with pytest.raises(UpstreamUnavailableError):
        storage.upload(
            access_token=alice_token,
            user_id=bob_id,  # alice's token, bob's namespace
            plant_id=bob_plant,
            context=ImageContextType.GALLERY,
            image=image,
        )


def test_a_user_cannot_sign_a_url_for_another_users_object(account):
    _, _, _, _, alice_paths = _upload(account)
    _, _, bob_token, _ = account()

    assert storage.signed_url(bob_token, alice_paths.original) is None


def test_a_failed_upload_leaves_nothing_behind(account):
    """A half-written set would leave a plant_images row pointing at objects that
    do not all exist, so the adapter rolls back what landed."""
    _, _, alice_token, _ = account()
    bob_id, bob_plant, _, _ = account()
    image = process(make_image())

    with contextlib.suppress(UpstreamUnavailableError):
        storage.upload(
            access_token=alice_token,
            user_id=bob_id,
            plant_id=bob_plant,
            context=ImageContextType.GALLERY,
            image=image,
        )

    # Nothing of alice's making should exist under bob's prefix.
    from supabase import create_client

    admin = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    listing = admin.storage.from_("plant-images").list(f"{bob_id}/{bob_plant}/gallery")
    assert listing == [] or all("emptyFolderPlaceholder" in item["name"] for item in listing)


# --- removal ------------------------------------------------------------------


def test_removal_deletes_every_variant(account):
    _, _, token, _, paths = _upload(account)

    storage.remove(token, paths)

    for path in (paths.original, paths.processed, paths.thumbnail):
        assert storage.signed_url(token, path) is None


def test_an_admin_can_sign_a_url_for_a_retained_image(account):
    """FINAL §20: an AI-used image is hidden from its owner but remains reachable
    by an administrator for history and audit."""
    _, _, _, _, paths = _upload(account, ImageContextType.IDENTIFICATION)

    assert storage.admin_signed_url(paths.original) is not None
