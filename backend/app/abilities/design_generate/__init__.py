"""图生图能力。"""

from app.abilities.design_generate.comfyui import ComfyUIImageGenerator
from app.abilities.design_generate.openai_compatible_image import (
    OpenAICompatibleImageGenerator,
)

__all__ = ["ComfyUIImageGenerator", "OpenAICompatibleImageGenerator"]
