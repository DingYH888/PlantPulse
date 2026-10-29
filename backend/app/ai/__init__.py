"""AI 智能养护模块（PRD 5.4 / 第 8 章 AI-RAG 固定工作流）。

分层职责（单一职责，避免路由层直接操作模型）：
- llm.py             LLM / Embedding 客户端工厂（百炼 OpenAI 兼容接口）
- prompts.py          识别 / 生成提示词（防幻觉约束，PRD 8.3）
- schemas.py          LLM 结构化输出模型与内容校验（PRD 8.5）
- species_aliases.py  品种同义词归一化（PRD 8.1 节点2）
- loaders.py          知识库文档加载（md/txt/pdf/docx + 轻量 frontmatter）
- splitter.py         中文友好的递归文本切分
- vector_store.py     ChromaDB 持久化向量库
- ingestion.py        文档 → 切分 → 入库（幂等）
- retriever.py        相似度检索 + 阈值过滤 + 通用知识降级（节点3/3b）
- context.py          当前用户当前植物的打卡与指标摘要（节点4，数据隔离）
- memory.py           多轮对话记忆（ConversationBufferMemory，仅内存）
- chain.py            LangChain LCEL 五节点编排（节点1~5）
- advice_service.py   AI 建议落库 / 历史 / 详情 / 反馈

注意：本包大量依赖 LangChain，路由层按需惰性导入，
未安装 requirements-ai.txt 时后端其余模块仍可正常启动。
"""