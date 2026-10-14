"""材质图检索能力。"""

from app.abilities.material_search.mock import MockMaterialImageSearchProvider
from app.abilities.material_search.serpapi import SerpApiMaterialSearchProvider

__all__ = ["MockMaterialImageSearchProvider", "SerpApiMaterialSearchProvider"]
