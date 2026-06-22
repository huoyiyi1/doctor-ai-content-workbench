from __future__ import annotations

from .base import ImageGenerationProvider, ImageGenerationResult


class DummyImageGenerationProvider(ImageGenerationProvider):
    def generate_image(self, **_: object) -> ImageGenerationResult:
        return ImageGenerationResult(
            success=False,
            error_message="图片生成模型尚未配置，请先在设置中配置图片服务，或使用手动上传图片。",
            raw_response={"provider": "dummy"},
        )
