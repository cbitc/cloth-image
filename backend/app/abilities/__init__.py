"""能力层：契约 + mock/real 实现 + 注册表。"""

from app.abilities.base import (
    Abilities,
    ClothingImageResult,
    ClothingSearchProvider,
    DesignImageGenerator,
    DesignImageResult,
    MaterialIdentifier,
    MaterialImageResult,
    MaterialImageSearchProvider,
    MaterialTagResult,
    ReferenceImage,
)

__all__ = [
    "Abilities",
    "ClothingImageResult",
    "ClothingSearchProvider",
    "DesignImageGenerator",
    "DesignImageResult",
    "MaterialIdentifier",
    "MaterialImageResult",
    "MaterialImageSearchProvider",
    "MaterialTagResult",
    "ReferenceImage",
]
