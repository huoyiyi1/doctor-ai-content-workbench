from __future__ import annotations

from .base import ImageStorageProvider
from .cloudinary_provider import CloudinaryUnsignedStorageProvider
from .local_provider import LocalOnlyStorageProvider, LocalStaticPublicStorageProvider
from .manual_url_provider import ManualUrlStorageProvider


def get_image_storage_provider(provider_name: str | None = None, public_base_url: str = "") -> ImageStorageProvider:
    provider = (provider_name or "manual_url").strip().lower()
    if provider == "local_only":
        return LocalOnlyStorageProvider()
    if provider == "local_static_public":
        return LocalStaticPublicStorageProvider(public_base_url)
    if provider in {"cloudinary", "cloudinary_unsigned"}:
        return CloudinaryUnsignedStorageProvider()
    return ManualUrlStorageProvider()
