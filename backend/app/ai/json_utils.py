"""LLM 原始输出解析工具（图像识别 / 问题解析 / 建议生成共用）。

单独成模块的原因：chain 与 question_parser 都需要把模型返回的 JSON 文本
解析成 dict，若放回 chain 会形成循环导入。
"""

import json


def content_to_text(content) -> str:
    """兼容 OpenAI 兼容接口返回 str 或 content 数组两种形态。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def parse_json_payload(text: str) -> dict:
    """从模型输出中提取 JSON（容忍代码块包裹与前后说明文字）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型未返回 JSON 对象")
    return json.loads(cleaned[start : end + 1])