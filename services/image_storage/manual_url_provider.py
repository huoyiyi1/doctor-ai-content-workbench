from __future__ import annotations

from .base import ImageStorageProvider, ImageStorageResult


class ManualUrlStorageProvider(ImageStorageProvider):
    def upload_image(self, local_path: str) -> ImageStorageResult:
        return ImageStorageResult(
            success=False,
            error_message="当前使用手动链接模式，请把图片上传到图床或 OSS 后，将图片链接填写回来。",
        )
