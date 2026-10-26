"""应用配置模块。

从 .env / 环境变量读取配置，所有配置项集中管理，禁止在业务代码中硬编码敏感值。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置模型（pydantic-settings 自动读取 .env）。"""

    # 运行环境：development / production
    ENV: str = "development"

    # 应用基础信息
    APP_NAME: str = "PlantPulse"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # 数据库连接串（开发默认 SQLite；生产切换 MySQL）
    DATABASE_URL: str = "sqlite://./db.sqlite3"

    # JWT 配置
    JWT_SECRET: str = "please-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS 允许来源（逗号分隔）
    CORS_ORIGINS: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """将 CORS_ORIGINS 字符串解析为列表。"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """缓存配置实例，避免重复读取 .env（lru_cache 保证单例）。"""
    return Settings()