from __future__ import annotations

from .base import ImageGenerationProvider
from .dummy_provider import DummyImageGenerationProvider
from .siliconflow_provider import SiliconFlowImageGenerationProvider


def get_image_generation_provider(provider_name: str | None = None) -> ImageGenerationProvider:
    provider = (provider_name or "dummy").strip().lower()
    if provider in {"siliconflow", "silicon_flow"}:
        return SiliconFlowImageGenerationProvider()
    if provider == "dummy":
        return DummyImageGenerationProvider()
    return DummyImageGenerationProvider()
