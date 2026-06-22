from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ImageStorageResult:
    success: bool
    public_url: str = ""
    error_message: str = ""


class ImageStorageProvider:
    def upload_image(self, local_path: str) -> ImageStorageResult:
        raise NotImplementedError
