"""材质识别能力。"""

from app.abilities.material_identify.mock import MockMaterialIdentifier
from app.abilities.material_identify.openai_compatible_vlm import (
    OpenAICompatibleVLMIdentifier,
)

__all__ = ["MockMaterialIdentifier", "OpenAICompatibleVLMIdentifier"]
