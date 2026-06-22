from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from generate import get_runtime_setting, load_env

from .base import ImageGenerationProvider, ImageGenerationResult


ASPECT_TO_IMAGE_SIZE = {
    "2.35:1": "1024x576",
    "16:9": "1024x576",
    "4:3": "1024x768",
    "3:4": "768x1024",
    "1:1": "512x512",
}


class SiliconFlowImageGenerationProvider(ImageGenerationProvider):
    def __init__(self) -> None:
        load_env()
        self.api_key = get_runtime_setting("SILICONFLOW_API_KEY")
        self.api_base = get_runtime_setting("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1").rstrip("/")
        self.model = (
            get_runtime_setting("SILICONFLOW_IMAGE_MODEL")
            or get_runtime_setting("IMAGE_MODEL")
            or "Tongyi-MAI/Z-Image-Turbo"
        )

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
        if not self.api_key:
            return ImageGenerationResult(
                success=False,
                error_message="还没有配置 SiliconFlow API Key。请先在 .env 中配置 SILICONFLOW_API_KEY。",
                raw_response={"provider": "siliconflow"},
            )
        if not prompt.strip():
            return ImageGenerationResult(success=False, error_message="图片提示词不能为空。")

        output_path = Path(output_dir or "outputs/images")
        output_path.mkdir(parents=True, exist_ok=True)

        payload = {
            "model": self.model,
            "prompt": self._build_prompt(prompt, style_preset, visual_params),
            "image_size": ASPECT_TO_IMAGE_SIZE.get(aspect_ratio or "", "1024x1024"),
            "batch_size": 1,
            "num_inference_steps": 8 if "Z-Image-Turbo" in self.model else 20,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        try:
            response = requests.post(
                f"{self.api_base}/images/generations",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
        except requests.RequestException as exc:
            return ImageGenerationResult(success=False, error_message=f"SiliconFlow 图片生成请求失败：{exc}")

        if response.status_code >= 400:
            return ImageGenerationResult(
                success=False,
                error_message=f"SiliconFlow 图片生成失败：{self._error_text(response)}",
                raw_response=self._safe_json(response),
            )

        data = self._safe_json(response)
        image_url = self._first_image_url(data)
        if not image_url:
            return ImageGenerationResult(
                success=False,
                error_message="SiliconFlow 已返回结果，但没有找到图片链接。",
                raw_response=data,
            )

        local_path = self._download_image(image_url, output_path)
        return ImageGenerationResult(
            success=True,
            local_path=str(local_path),
            image_url=image_url,
            raw_response={"provider": "siliconflow", "model": self.model, "response": data},
        )

    def _build_prompt(self, prompt: str, style_preset: str | None, visual_params: dict | None) -> str:
        prompt_parts = [prompt.strip()]
        if style_preset:
            prompt_parts.append(f"图片风格：{style_preset}")
        if visual_params:
            readable_params = "，".join(
                f"{key}: {value}" for key, value in visual_params.items() if value
            )
            if readable_params:
                prompt_parts.append(f"视觉参数：{readable_params}")
        prompt_parts.append("画面干净、专业、温和，避免文字乱码和可识别隐私信息。")
        return "\n".join(prompt_parts)

    def _download_image(self, image_url: str, output_dir: Path) -> Path:
        response = requests.get(image_url, timeout=120)
        response.raise_for_status()
        suffix = self._suffix_from_content_type(response.headers.get("content-type", ""))
        filename = f"siliconflow_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
        path = output_dir / filename
        path.write_bytes(response.content)
        return path

    @staticmethod
    def _suffix_from_content_type(content_type: str) -> str:
        if "jpeg" in content_type or "jpg" in content_type:
            return ".jpg"
        if "webp" in content_type:
            return ".webp"
        return ".png"

    @staticmethod
    def _safe_json(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
            return data if isinstance(data, dict) else {"data": data}
        except ValueError:
            return {"text": response.text[:1000]}

    @staticmethod
    def _first_image_url(data: dict[str, Any]) -> str:
        images = data.get("images")
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                return str(first.get("url") or "")
        data_items = data.get("data")
        if isinstance(data_items, list) and data_items:
            first = data_items[0]
            if isinstance(first, dict):
                return str(first.get("url") or "")
        return ""

    @staticmethod
    def _error_text(response: requests.Response) -> str:
        try:
            return json.dumps(response.json(), ensure_ascii=False)[:1000]
        except ValueError:
            return response.text[:1000]
