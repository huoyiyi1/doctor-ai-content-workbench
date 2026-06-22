from __future__ import annotations

import shutil
from pathlib import Path

from .base import ImageStorageProvider, ImageStorageResult


STATIC_IMAGE_DIR = Path("static/images")


class LocalOnlyStorageProvider(ImageStorageProvider):
    def upload_image(self, local_path: str) -> ImageStorageResult:
        if not local_path or not Path(local_path).exists():
            return ImageStorageResult(success=False, error_message="没有找到本地图片文件。")
        return ImageStorageResult(
            success=False,
            error_message="当前仅保存本地图片，无法生成可用于 Raphael 的公网图片链接。",
        )


class LocalStaticPublicStorageProvider(ImageStorageProvider):
    def __init__(self, public_base_url: str = "") -> None:
        self.public_base_url = public_base_url.rstrip("/")

    def upload_image(self, local_path: str) -> ImageStorageResult:
        path = Path(local_path)
        if not local_path or not path.exists():
            return ImageStorageResult(success=False, error_message="没有找到本地图片文件。")
        if not self.public_base_url:
            return ImageStorageResult(success=False, error_message="请先配置 IMAGE_PUBLIC_BASE_URL。")
        STATIC_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        target = STATIC_IMAGE_DIR / path.name
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        return ImageStorageResult(success=True, public_url=f"{self.public_base_url}/{target.name}")
