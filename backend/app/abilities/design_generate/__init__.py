"""图生图能力。"""

from app.abilities.design_generate.mock import MockDesignGenerator
from app.abilities.design_generate.openai_compatible_image import (
    OpenAICompatibleImageGenerator,
)

__all__ = ["MockDesignGenerator", "OpenAICompatibleImageGenerator"]
