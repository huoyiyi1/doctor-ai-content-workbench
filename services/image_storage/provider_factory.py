from __future__ import annotations

from .base import ImageStorageProvider
from .cloudinary_provider import CloudinaryUnsignedStorageProvider
from .local_provider import LocalOnlyStorageProvider, LocalStaticPublicStorageProvider
from .manual_url_provider import ManualUrlStorageProvider
from .streamlit_media_provider import StreamlitMediaStorageProvider


def get_image_storage_provider(provider_name: str | None = None, public_base_url: str = "") -> ImageStorageProvider:
    provider = (provider_name or "manual_url").strip().lower()
    public_base = (public_base_url or "").strip().lower()
    if provider == "local_only":
        return LocalOnlyStorageProvider()
    if provider == "local_static_public":
        if ".streamlit.app" in public_base:
            return StreamlitMediaStorageProvider(public_base_url)
        return LocalStaticPublicStorageProvider(public_base_url)
    if provider == "streamlit_media":
        return StreamlitMediaStorageProvider(public_base_url)
    if provider in {"cloudinary", "cloudinary_unsigned"}:
        return CloudinaryUnsignedStorageProvider()
    return ManualUrlStorageProvider()
