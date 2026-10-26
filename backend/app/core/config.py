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

    # 数据库连接串（默认 MySQL 8，本地开发账号 root；开发本地可切 SQLite 调试）
    DATABASE_URL: str = "mysql://root:123456@127.0.0.1:3306/plantpulse?charset=utf8mb4"

    # JWT 配置（单 token 方案：登录签发一个 token，7 天有效）
    JWT_SECRET: str = "please-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7

    # 图形验证码有效期（分钟）
    CAPTCHA_EXPIRE_MINUTES: int = 5

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