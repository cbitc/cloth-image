"""材质图检索能力。"""

from app.abilities.material_search.mock import MockMaterialImageSearchProvider
from app.abilities.material_search.unsplash import UnsplashMaterialSearchProvider

__all__ = ["MockMaterialImageSearchProvider", "UnsplashMaterialSearchProvider"]
