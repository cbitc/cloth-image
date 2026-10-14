"""服装图搜索能力。"""

from app.abilities.clothing_search.mock import MockClothingSearchProvider
from app.abilities.clothing_search.unsplash import UnsplashClothingSearchProvider

__all__ = ["MockClothingSearchProvider", "UnsplashClothingSearchProvider"]
