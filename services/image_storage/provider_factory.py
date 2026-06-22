from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from .base import ImageStorageProvider
from .cloudinary_provider import CloudinaryUnsignedStorageProvider
from .local_provider import LocalOnlyStorageProvider, LocalStaticPublicStorageProvider
from .manual_url_provider import ManualUrlStorageProvider
from .streamlit_media_provider import StreamlitMediaStorageProvider


def normalize_streamlit_static_base(public_base_url: str) -> str:
    raw = (public_base_url or "").strip().rstrip("/")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not parsed.scheme or not parsed.netloc or not host.endswith(".streamlit.app"):
        return raw

    path = parsed.path.rstrip("/")
    if path.startswith("/~/+/app/static/images"):
        normalized_path = path
    elif path.startswith("/app/static/images"):
        normalized_path = "/~/+" + path
    elif path.startswith("/~/+/"):
        normalized_path = "/~/+/app/static/images"
    else:
        normalized_path = "/~/+/app/static/images"
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))


def get_image_storage_provider(provider_name: str | None = None, public_base_url: str = "") -> ImageStorageProvider:
    provider = (provider_name or "manual_url").strip().lower()
    public_base = (public_base_url or "").strip().lower()
    if provider == "local_only":
        return LocalOnlyStorageProvider()
    if provider == "local_static_public":
        if ".streamlit.app" in public_base:
            return LocalStaticPublicStorageProvider(normalize_streamlit_static_base(public_base_url))
        return LocalStaticPublicStorageProvider(public_base_url)
    if provider == "streamlit_media":
        return StreamlitMediaStorageProvider(public_base_url)
    if provider in {"cloudinary", "cloudinary_unsigned"}:
        return CloudinaryUnsignedStorageProvider()
    return ManualUrlStorageProvider()
