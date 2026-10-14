"""应用配置：通过环境变量 / .env 覆盖。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


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
    # 能力提供方
    # ------------------------------------------------------------------ #
    # 兑底开关：mock（默认，零外部依赖）| real
    provider_mode: str = "mock"

    # 每个能力可单独覆盖，留空则回退到 provider_mode。
    #   clothing_search     : mock | serpapi
    #   material_identifier : mock | maas
    #   material_search     : mock | serpapi
    #   design_generator    : mock | dashscope | fal
    clothing_search_provider: str = ""
    material_identifier_provider: str = ""
    material_search_provider: str = ""
    design_generator_provider: str = ""

    # 阿里云 MaaS（OpenAI 兼容）—— 视觉理解与生图共用同一端点
    maas_base_url: str = (
        "https://ws-yilqbuvsxvumn3ms.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    maas_api_key: str = ""
    vlm_model: str = "qwen3-vl-plus"
    image_model: str = "qwen-image-3.0"
    image_size: str = "1024x1024"
    # 实测 qwen-image-3.0 限制：0 张 = 文生图，1~3 张 = 图生图（超限会直接 400）
    image_max_refs: int = 3
    prompt_extend: bool = False

    # 可分别覆盖上面两项（留空则回退到 MaaS 配置），便于将来换厂商
    vlm_base_url: str = ""
    vlm_api_key: str = ""
    image_base_url: str = ""
    image_api_key: str = ""

    # 其他真实 provider 的 key
    serpapi_api_key: str = ""
    fal_key: str = ""

    # HTTP / 图片
    provider_timeout_s: float = 90.0
    provider_max_retries: int = 3
    vision_max_image_side: int = 1568
    download_max_bytes: int = 15_000_000

    # 流水线参数
    identify_top_k: int = 4
    material_images_per_tag: int = 3
    design_candidates: int = 3

    # ------------------------------------------------------------------ #
    # 派生配置
    # ------------------------------------------------------------------ #
    ABILITY_NAMES: ClassVar[tuple[str, ...]] = (
        "clothing_search",
        "material_identifier",
        "material_search",
        "design_generator",
    )

    def provider_for(self, ability: str) -> str:
        """解析某个能力实际使用的 provider（显式配置优先，否则回退 provider_mode）。"""
        explicit = str(getattr(self, f"{ability}_provider", "") or "").strip()
        fallback = (self.provider_mode or "mock").strip() or "mock"
        return (explicit or fallback).lower()

    @property
    def providers(self) -> dict[str, str]:
        return {name: self.provider_for(name) for name in self.ABILITY_NAMES}

    @property
    def resolved_vlm_base_url(self) -> str:
        return (self.vlm_base_url or self.maas_base_url).rstrip("/")

    @property
    def resolved_vlm_api_key(self) -> str:
        return self.vlm_api_key or self.maas_api_key

    @property
    def resolved_image_base_url(self) -> str:
        return (self.image_base_url or self.maas_base_url).rstrip("/")

    @property
    def resolved_image_api_key(self) -> str:
        return self.image_api_key or self.maas_api_key

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
