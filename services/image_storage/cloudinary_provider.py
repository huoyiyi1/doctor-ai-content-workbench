from __future__ import annotations

from pathlib import Path

import requests

from generate import get_runtime_setting

from .base import ImageStorageProvider, ImageStorageResult


class CloudinaryUnsignedStorageProvider(ImageStorageProvider):
    def __init__(self) -> None:
        self.cloud_name = get_runtime_setting("CLOUDINARY_CLOUD_NAME")
        self.upload_preset = get_runtime_setting("CLOUDINARY_UPLOAD_PRESET")
        self.folder = get_runtime_setting("CLOUDINARY_FOLDER", "wechat-ai-workbench")

    def upload_image(self, local_path: str) -> ImageStorageResult:
        path = Path(local_path or "")
        if not path.exists() or not path.is_file():
            return ImageStorageResult(success=False, error_message="没有找到本地图片文件。")
        if not self.cloud_name or not self.upload_preset:
            return ImageStorageResult(
                success=False,
                error_message="请先配置 CLOUDINARY_CLOUD_NAME 和 CLOUDINARY_UPLOAD_PRESET。",
            )

        endpoint = f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image/upload"
        data = {
            "upload_preset": self.upload_preset,
            "folder": self.folder,
        }
        try:
            with path.open("rb") as file_obj:
                response = requests.post(
                    endpoint,
                    data=data,
                    files={"file": (path.name, file_obj)},
                    timeout=120,
                )
        except requests.RequestException as exc:
            return ImageStorageResult(success=False, error_message=f"上传 Cloudinary 失败：{exc}")

        if response.status_code >= 400:
            return ImageStorageResult(success=False, error_message=f"上传 Cloudinary 失败：{response.text[:600]}")

        try:
            payload = response.json()
        except ValueError:
            return ImageStorageResult(success=False, error_message="Cloudinary 返回结果无法解析。")

        public_url = str(payload.get("secure_url") or payload.get("url") or "")
        if not public_url:
            return ImageStorageResult(success=False, error_message="Cloudinary 没有返回图片链接。")
        return ImageStorageResult(success=True, public_url=public_url)
