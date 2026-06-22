from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from .base import ImageStorageProvider, ImageStorageResult


class StreamlitMediaStorageProvider(ImageStorageProvider):
    """Register generated images with Streamlit's public media endpoint.

    Streamlit Community Cloud protects `/app/static/...` behind its auth layer,
    but images registered through the runtime media manager are publicly served
    from the app frame path, for example `/~/+/media/<id>.jpg`.
    """

    def __init__(self, public_base_url: str = "") -> None:
        self.public_base_url = public_base_url.strip().rstrip("/")

    def upload_image(self, local_path: str) -> ImageStorageResult:
        path = Path(local_path or "")
        if not local_path or not path.exists():
            return ImageStorageResult(success=False, error_message="没有找到本地图片文件。")

        try:
            from streamlit import runtime
            import streamlit as st
        except Exception as exc:
            return ImageStorageResult(success=False, error_message=f"无法加载 Streamlit 图片服务：{exc}")

        if not runtime.exists():
            return ImageStorageResult(success=False, error_message="当前运行环境不支持 Streamlit 图片服务。")

        mimetype = mimetypes.guess_type(path.name)[0] or "image/png"
        coordinates = f"published-image-{path.stem}"
        try:
            relative_url = runtime.get_instance().media_file_mgr.add(
                path.read_bytes(),
                mimetype,
                coordinates,
                file_name=path.name,
            )
        except Exception as exc:
            return ImageStorageResult(success=False, error_message=f"注册 Streamlit 图片失败：{exc}")

        public_url = self._absolute_media_url(relative_url, getattr(st.context, "url", "") or "")
        if not public_url:
            return ImageStorageResult(success=False, error_message="无法生成公网图片链接。")
        return ImageStorageResult(success=True, public_url=public_url)

    def _absolute_media_url(self, media_url: str, context_url: str) -> str:
        if not media_url:
            return ""
        parsed_media = urlparse(media_url)
        if parsed_media.scheme in {"http", "https"}:
            return media_url

        base_url = context_url or self.public_base_url
        parsed_base = urlparse(base_url)
        if not parsed_base.scheme or not parsed_base.netloc:
            return media_url

        origin = urlunparse((parsed_base.scheme, parsed_base.netloc, "", "", "", ""))
        if media_url.startswith("/~/+/"):
            return origin + media_url
        if media_url.startswith("/media/"):
            if parsed_base.path.startswith("/~/+/"):
                return origin + "/~/+" + media_url
            return origin + media_url
        if media_url.startswith("media/") and parsed_base.path.startswith("/~/+/"):
            return origin + "/~/+/" + media_url
        return urljoin(base_url, media_url)
