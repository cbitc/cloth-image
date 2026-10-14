"""应用配置：通过环境变量 / .env 覆盖。"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.settings_spec import ABILITY_FIELD_NAMES

BACKEND_DIR = Path(__file__).resolve().parent.parent

#: 运行时覆盖项（由设置页写入数据库后加载进来）。优先级高于环境变量。
#: 用模块级字典而非改 Settings 字段，是为了让所有既有的 get_settings() 调用点无需改动。
_OVERRIDES: dict[str, Any] = {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 存储 / 数据库
    database_url: str = "sqlite:///./.data/app.db"
    redis_url: str = "redis://localhost:6379/0"

    # 任务执行：inline（进程内后台执行，便于本地与测试）| celery（需要 worker）
    task_execution: str = "inline"

    # 对象存储：local（本地目录 + /media 静态服务）| s3（MinIO / S3 兼容）
    storage_backend: str = "local"
    local_storage_dir: str = str(BACKEND_DIR / ".data" / "objects")
    media_url_prefix: str = "/media"
    public_base_url: str = "http://localhost:8000"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "cloth-images"
    s3_region: str = "us-east-1"

    # ------------------------------------------------------------------ #
    # 能力配置（provider / base_url / api_key / model）
    # ------------------------------------------------------------------ #
    # 这四项是「能力直接相关配置」，**唯一来源是设置页（数据库）**，见 app/ability_config.py。
    # 此处不声明字段，也不读环境变量；由 apply_overrides 按字段归属分流。
    #
    # 生图参数（env 打底，设置页可覆盖）
    image_size: str = "1024x1024"
    # 实测 qwen-image-3.0 限制：0 张 = 文生图，1~3 张 = 图生图（超限会直接 400）
    image_max_refs: int = 3
    prompt_extend: bool = False

    # HTTP / 图片
    provider_timeout_s: float = 90.0
    provider_max_retries: int = 3
    vision_max_image_side: int = 1568
    download_max_bytes: int = 15_000_000

    # 流水线参数
    identify_top_k: int = 4
    material_images_per_tag: int = 3
    design_candidates: int = 3
    # 相同图片 + 相同模型时复用识别结果（省一次 VLM 调用，约 1500 tokens）
    identify_cache_enabled: bool = True

    # 是否允许通过 /api/settings 修改配置。
    # 服务目前无鉴权，对外暴露前应设为 false 或先加鉴权。
    settings_write_enabled: bool = True

    # ------------------------------------------------------------------ #
    # 派生配置
    # ------------------------------------------------------------------ #
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    """生效配置 = 环境变量/.env 打底，再叠加数据库里的用户覆盖项。

    改完覆盖项后必须调用 `apply_overrides()`，它会清掉这里的缓存。
    注意：`database_url` / `storage_backend` 等启动期依赖的项**不在**可覆盖范围内
    （引擎与存储客户端在导入时就已按环境变量建好）。
    """
    base = Settings()
    if not _OVERRIDES:
        return base
    return base.model_copy(update=dict(_OVERRIDES))


def current_overrides() -> dict[str, Any]:
    """当前生效的（环境变量类）覆盖项快照。"""
    return dict(_OVERRIDES)


def apply_overrides(values: Mapping[str, Any] | None) -> None:
    """替换覆盖集合并清缓存。

    按字段归属分流：
    - `ABILITY_FIELD_NAMES` → `app.ability_config`（能力的唯一来源）
    - 其余 → 本模块 `_OVERRIDES`（环境变量打底、设置页可覆盖）

    调用方若需要让能力实现重新构建，还应调用
    `app.abilities.registry.reset_abilities_cache()`。
    """
    ability_values: dict[str, Any] = {}
    env_values: dict[str, Any] = {}
    for key, value in (values or {}).items():
        (ability_values if key in ABILITY_FIELD_NAMES else env_values)[key] = value

    _OVERRIDES.clear()
    _OVERRIDES.update(env_values)
    get_settings.cache_clear()

    # 延迟导入：避开 config <-> ability_config 的导入环
    from app.ability_config import apply_ability_overrides

    apply_ability_overrides(ability_values)


def reset_settings_cache() -> None:
    get_settings.cache_clear()
