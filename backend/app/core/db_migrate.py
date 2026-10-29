"""开发环境幂等增量迁移（Tortoise generate_schemas 只建新表，不会给已有表加列）。

当前仅处理 AI 会话改造：ai_advice 增加 session_id。
- MySQL：通过 information_schema 检查后再 ALTER，可重复执行；
- SQLite（单测临时库）：generate_schemas 直接建新表，无需迁移。

生产环境仍应使用正式迁移工具/脚本，本模块只在 development 启动时执行。
"""

import logging

from tortoise import Tortoise

logger = logging.getLogger(__name__)

_AI_SESSION_COLUMN_SQL = (
    "ALTER TABLE `ai_advice` "
    "ADD COLUMN `session_id` VARCHAR(64) NULL "
    "COMMENT '前端会话ID（多轮对话隔离与历史会话切换键）' AFTER `plant_id`, "
    "ADD KEY `idx_ai_advice_session_id` (`session_id`)"
)


async def ensure_ai_session_column() -> None:
    """确保 ai_advice.session_id 存在（幂等，失败只告警不阻断启动）。"""
    connection = Tortoise.get_connection("default")
    try:
        tables = await connection.execute_query_dict(
            "SELECT 1 FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_advice'"
        )
        if not tables:
            return
        columns = await connection.execute_query_dict(
            "SELECT 1 FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ai_advice' "
            "AND COLUMN_NAME = 'session_id'"
        )
        if columns:
            return
        await connection.execute_script(_AI_SESSION_COLUMN_SQL)
        logger.info("已为 ai_advice 添加 session_id 列")
    except Exception as exc:  # 权限不足/并发启动等场景不阻断服务
        logger.warning("ai_advice.session_id 自动迁移失败，请手工执行 sql/migrate_ai_session.sql：%s", exc)