"""API 路由包。"""

from app.api import cache, events, media, search, tasks, taxonomy
from app.api import settings as settings_api

__all__ = ["cache", "events", "media", "search", "settings_api", "tasks", "taxonomy"]
