-- AI 会话改造迁移（MySQL 8，可手工执行）
-- 作用：ai_advice 增加 session_id，用于聊天式历史会话分组与多轮记忆隔离
-- 说明：后端开发环境启动时会自动检查并执行；权限不足时可手工执行本脚本。

ALTER TABLE `ai_advice`
  ADD COLUMN `session_id` VARCHAR(64) NULL
    COMMENT '前端会话ID（多轮对话隔离与历史会话切换键）' AFTER `plant_id`,
  ADD KEY `idx_ai_advice_session_id` (`session_id`);