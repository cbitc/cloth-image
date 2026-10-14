"""图生图能力。"""

from app.abilities.design_generate.dashscope import QwenImageGenerator
from app.abilities.design_generate.fal import FalDesignGenerator
from app.abilities.design_generate.mock import MockDesignGenerator

__all__ = ["MockDesignGenerator", "FalDesignGenerator", "QwenImageGenerator"]
