"""应用配置模块。

从 .env / 环境变量读取配置，所有配置项集中管理，禁止在业务代码中硬编码敏感值。
"""

from functools import lru_cache
from pathlib import Path

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

    # 图片上传目录（相对 backend 包目录解析，PRD 9.6）
    UPLOAD_DIR: str = "static/uploads"

    # CORS 允许来源（逗号分隔）
    CORS_ORIGINS: str = "http://localhost:5173"

    # ===================== AI 模块（PRD 5.4 / 第 8 章） =====================
    # LLM（多模态，节点1 图像识别 + 节点5 生成共用）：OpenAI 兼容接口
    # 主地址默认走百炼专属部署 MaaS；切通用地址只需把 AI_USE_FALLBACK_BASE_URL 改为 true
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://ws-iyypdocg6wq1k3e4.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    LLM_BASE_URL_FALLBACK: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen3.8-omni-flash"
    # 视觉模型：留空表示复用 LLM_MODEL（多模态模型可直接接收 image_url）
    LLM_VISION_MODEL: str = ""
    LLM_TEMPERATURE: float = 0.3
    LLM_TIMEOUT_SECONDS: int = 60
    # 生成输出上限（五节建议约 1200 tokens，留余量避免 JSON 被截断）
    LLM_MAX_TOKENS: int = 1800
    # 是否允许模型思考：false 时向百炼传 enable_thinking=false，可显著降低生成耗时；
    # 若模型/接口不支持该参数报 400，改为 true 即可不发送该参数
    LLM_ENABLE_THINKING: bool = False

    # Base URL 切换开关：true 时 LLM/Embedding 统一改用各自的 FALLBACK 地址
    AI_USE_FALLBACK_BASE_URL: bool = False

    # Embedding：与 LLM 使用独立 API Key / 独立接口（PRD 8.1 节点3）
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://ws-iyypdocg6wq1k3e4.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_BASE_URL_FALLBACK: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    EMBEDDING_MODEL: str = "qwen3.7-text-embedding-flash"
    EMBEDDING_TIMEOUT_SECONDS: int = 30

    # 知识库文档目录（相对 backend 目录解析：../docs/knowledge_base 即项目根 docs 下）
    KNOWLEDGE_DIR: str = "../docs/knowledge_base"

    # ChromaDB 持久化目录（相对 backend 目录；已加入 .gitignore）
    CHROMA_DIR: str = "chroma_db"
    CHROMA_COLLECTION: str = "plant_knowledge"

    # RAG 调参项（PRD 8.1 节点3 / 8.4 阈值兜底；自测后在此微调，不改代码）
    RAG_CHUNK_SIZE: int = 600
    RAG_CHUNK_OVERLAP: int = 100
    RAG_TOP_K: int = 5
    RAG_SCORE_THRESHOLD: float = 0.45

    # AI 链路：端到端超时（PRD 9.3 → 504）、内存记忆轮数、按用户限流（PRD 12）
    AI_TIMEOUT_SECONDS: int = 30
    AI_MEMORY_MAX_TURNS: int = 10
    AI_RATE_LIMIT_PER_MINUTE: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """将 CORS_ORIGINS 字符串解析为列表。"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def upload_dir(self) -> Path:
        """上传目录绝对路径：相对 backend 包目录（app/..）解析，避免受运行目录影响。"""
        path = Path(self.UPLOAD_DIR)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path

    @property
    def static_dir(self) -> Path:
        """静态资源根目录（/static 挂载点）。

        必须取 upload_dir 的父目录：URL 形如 /static/uploads/<file>，
        若把 /static 直接挂到 uploads 目录，实际会查找 uploads/uploads/<file> 而 404。
        """
        return self.upload_dir.parent

    # ---- AI 模块路径与地址解析 ----
    @property
    def backend_dir(self) -> Path:
        """backend 目录绝对路径（app/core/config.py → 向上 3 层）。"""
        return Path(__file__).resolve().parents[2]

    @property
    def project_root(self) -> Path:
        """项目根目录绝对路径（backend 的上一级）。"""
        return self.backend_dir.parent

    def _resolve_backend_path(self, raw: str) -> Path:
        """把配置中的相对路径统一按 backend 目录解析，避免受启动目录影响。"""
        path = Path(raw)
        return path if path.is_absolute() else (self.backend_dir / path).resolve()

    @property
    def knowledge_dir(self) -> Path:
        """知识库文档目录（默认项目根 docs/knowledge_base）。"""
        return self._resolve_backend_path(self.KNOWLEDGE_DIR)

    @property
    def chroma_dir(self) -> Path:
        """ChromaDB 持久化目录（默认 backend/chroma_db）。"""
        return self._resolve_backend_path(self.CHROMA_DIR)

    @property
    def llm_base_url(self) -> str:
        """当前生效的 LLM 地址：开关打开时用备用（dashscope 通用）地址。"""
        return self.LLM_BASE_URL_FALLBACK if self.AI_USE_FALLBACK_BASE_URL else self.LLM_BASE_URL

    @property
    def llm_vision_model(self) -> str:
        """视觉模型名：未单独配置时复用 LLM_MODEL。"""
        return self.LLM_VISION_MODEL or self.LLM_MODEL

    @property
    def embedding_base_url(self) -> str:
        """当前生效的 Embedding 地址：与 LLM 共用同一个切换开关。"""
        return (
            self.EMBEDDING_BASE_URL_FALLBACK
            if self.AI_USE_FALLBACK_BASE_URL
            else self.EMBEDDING_BASE_URL
        )


@lru_cache
def get_settings() -> Settings:
    """缓存配置实例，避免重复读取 .env（lru_cache 保证单例）。"""
    return Settings()