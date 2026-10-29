-- ============================================================
-- PlantPulse 数据库建表脚本（MySQL 8.0+）
-- 对应 ORM：backend/app/models（Tortoise-ORM，表名 plant_record）
-- 执行方式：mysql -u root -p < schema.sql
-- 设计约束：密码仅存哈希 / 全表 user_id 数据隔离 / record_type 枚举 / 全表创建时间
-- ============================================================

CREATE DATABASE IF NOT EXISTS `plantpulse`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `plantpulse`;

-- ------------------------------------------------------------
-- 1. users 用户账号表
-- 约束1：password_hash 仅存 bcrypt 哈希，禁止明文
-- 账号体系：nickname 为唯一登录账号；username/email 预留扩展（可空）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `id`            BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `nickname`      VARCHAR(32)  NOT NULL COMMENT '昵称（登录账号，3-20位字母数字下划线）',
  `password_hash` VARCHAR(128) NOT NULL COMMENT 'bcrypt密码哈希（约束1：不存明文）',
  `username`      VARCHAR(32)  NULL COMMENT '用户名（预留扩展）',
  `email`         VARCHAR(128) NULL COMMENT '邮箱（预留扩展）',
  `avatar_url`    VARCHAR(512) NULL COMMENT '头像URL',
  `role`          VARCHAR(16)  NOT NULL DEFAULT 'ROLE_USER' COMMENT '角色：ROLE_USER/ROLE_ADMIN',
  `is_active`     TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '是否启用（禁用后禁止登录）',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（约束4）',
  `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_nickname` (`nickname`),
  KEY `idx_users_username` (`username`),
  KEY `idx_users_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户账号表';

-- ------------------------------------------------------------
-- 2. captcha_codes 图形验证码表
-- 一次性校验（is_used）+ 5 分钟有效期（expires_at），注册防刷
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `captcha_codes` (
  `id`          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `captcha_id`  VARCHAR(64) NOT NULL COMMENT '验证码唯一标识（uuid，注册时回传）',
  `code`        VARCHAR(8)  NOT NULL COMMENT '验证码明文（4位数字）',
  `expires_at`  DATETIME    NOT NULL COMMENT '过期时间（生成时间 + 5分钟）',
  `is_used`     TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '是否已使用（一次性校验）',
  `created_at`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（约束4）',
  `updated_at`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_captcha_codes_id` (`captcha_id`),
  KEY `idx_captcha_codes_expires_at` (`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='图形验证码表';

-- ------------------------------------------------------------
-- 3. plants 植物档案表
-- 约束2：user_id 外键实现数据隔离，A用户不可见B用户植物
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `plants` (
  `id`         BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id`    BIGINT      NOT NULL COMMENT '归属用户ID（数据隔离键）',
  `name`       VARCHAR(64) NOT NULL COMMENT '用户为植物起的名字',
  `species`    VARCHAR(64) NULL COMMENT '品种（AI识别或手动填写）',
  `image_url`  VARCHAR(512) NULL COMMENT '植物图片URL',
  `location`   VARCHAR(64) NULL COMMENT '摆放位置（如阳台/客厅）',
  `status`     VARCHAR(16) NOT NULL DEFAULT 'healthy' COMMENT '状态：healthy/attention/abnormal（规则引擎派生）',
  `planted_at` DATE        NULL COMMENT '种植日期',
  `notes`      TEXT        NULL COMMENT '用户备注',
  `created_at` DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（约束4）',
  `updated_at` DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_plants_user_id` (`user_id`),
  CONSTRAINT `fk_plants_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='植物档案表';

-- ------------------------------------------------------------
-- 4. plant_record 养护/打卡记录表
-- 约束3：record_type 为原生 ENUM 枚举
-- BR-03：同用户同植物同类型同日期唯一（防重复打卡）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `plant_record` (
  `id`          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id`     BIGINT      NOT NULL COMMENT '归属用户ID（数据隔离键）',
  `plant_id`    BIGINT      NOT NULL COMMENT '所属植物ID',
  `record_type` ENUM('watering','fertilizing','pruning','repotting','pest_control','other')
                NOT NULL COMMENT '养护类型枚举（约束3）',
  `content`     VARCHAR(512) NULL COMMENT '备注内容（如用量、部位）',
  `image_url`   VARCHAR(512) NULL COMMENT '打卡照片URL',
  `record_date` DATE        NOT NULL COMMENT '打卡日期（禁止未来日期）',
  `created_at`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（约束4）',
  `updated_at`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_plant_type_date` (`user_id`, `plant_id`, `record_type`, `record_date`),
  KEY `idx_plant_record_plant_id` (`plant_id`),
  KEY `idx_plant_record_user_id` (`user_id`),
  CONSTRAINT `fk_plant_record_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_plant_record_plant` FOREIGN KEY (`plant_id`) REFERENCES `plants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='植物养护/打卡记录表';

-- ------------------------------------------------------------
-- 5. plant_metric 养护指标表（P3 数据图表数据源）
-- 值域校验见 PRD 5.3.3
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `plant_metric` (
  `id`            BIGINT      NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id`       BIGINT      NOT NULL COMMENT '归属用户ID（数据隔离键）',
  `plant_id`      BIGINT      NOT NULL COMMENT '所属植物ID',
  `temperature`   DECIMAL(5,2)  NULL COMMENT '温度（℃），区间 -20~60',
  `humidity`      DECIMAL(5,2)  NULL COMMENT '空气湿度（%），区间 0~100',
  `light`         DECIMAL(10,2) NULL COMMENT '光照（lux），区间 0~200000',
  `soil_moisture` DECIMAL(5,2)  NULL COMMENT '土壤湿度（%），区间 0~100',
  `ph`            DECIMAL(4,2)  NULL COMMENT '土壤pH，区间 0~14',
  `record_time`   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '指标记录时间',
  `created_at`    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（约束4）',
  `updated_at`    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_plant_metric_plant_id` (`plant_id`),
  KEY `idx_plant_metric_user_id` (`user_id`),
  CONSTRAINT `fk_plant_metric_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_plant_metric_plant` FOREIGN KEY (`plant_id`) REFERENCES `plants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='植物养护指标表';

-- ------------------------------------------------------------
-- 6. ai_advice AI 养护建议表
-- 防幻觉：is_fallback 降级标注 / doc_refs 来源引用 / trace 全链路日志（PRD 8.4）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ai_advice` (
  `id`              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `user_id`         BIGINT       NOT NULL COMMENT '归属用户ID（数据隔离键）',
  `plant_id`        BIGINT       NULL COMMENT '关联植物ID（可空：识别未建档场景）',
  `session_id`      VARCHAR(64)  NULL COMMENT '前端会话ID（多轮对话隔离与历史会话切换键）',
  `input_image_url` VARCHAR(512) NULL COMMENT '输入图片URL（图像识别入参）',
  `species`         VARCHAR(64)  NULL COMMENT '识别/归一化后的品种名',
  `confidence`      DECIMAL(4,2) NULL COMMENT '识别置信度（0~1，<0.6 走未知品种路径）',
  `is_fallback`     TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否降级输出（无知识库匹配=true）',
  `content`         JSON         NULL COMMENT '建议分节内容（PRD 8.5 输出Schema）',
  `doc_refs`        JSON         NULL COMMENT '引用文档[{doc_id,title,source_type}]',
  `trace`           JSON         NULL COMMENT '全链路日志（识别/检索/摘要/提示词hash）',
  `feedback`        SMALLINT     NULL COMMENT '用户反馈：1有用/-1无用/0中性',
  `status`          VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '状态：pending/success/failed/timeout',
  `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（约束4）',
  `updated_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_ai_advice_plant_id` (`plant_id`),
  KEY `idx_ai_advice_user_id` (`user_id`),
  KEY `idx_ai_advice_session_id` (`session_id`),
  CONSTRAINT `fk_ai_advice_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
  CONSTRAINT `fk_ai_advice_plant` FOREIGN KEY (`plant_id`) REFERENCES `plants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI养护建议表';