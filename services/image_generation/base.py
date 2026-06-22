from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ImageGenerationResult:
    success: bool
    local_path: str = ""
    image_url: str = ""
    error_message: str = ""
    raw_response: Optional[dict[str, Any]] = None


class ImageGenerationProvider:
    def generate_image(
        self,
        *,
        prompt: str,
        negative_prompt: str | None = None,
        aspect_ratio: str | None = None,
        style_preset: str | None = None,
        visual_params: dict | None = None,
        output_dir: str = "",
    ) -> ImageGenerationResult:
        raise NotImplementedError
