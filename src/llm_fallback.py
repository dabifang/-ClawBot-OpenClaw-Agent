"""LLM 兜底模块 —— 正则解析失败时调用 DeepSeek API

精简 prompt，约 100 token，仅处理复杂/模糊的记账指令。
"""

import json
import logging
import re
from datetime import date
from typing import Optional

from .models import ParseResult, RecordType, Category
from .proxy import ProxyClient

logger = logging.getLogger(__name__)

# 极简系统提示词，约 80 token
SYSTEM_PROMPT = """你是记账解析器。解析用户输入，输出JSON：
{"type":"支出|收入","amount":数字,"category":"餐饮|交通|购物|娱乐|居住|医疗|其他","date":"YYYY-MM-DD","note":"简短备注"}

规则：
1. 金额必须是纯数字，不含货币符号
2. type: 花钱/消费→支出，收钱/到账→收入
3. 未说明日期用今天
4. 只输出JSON，不输出其他内容"""


def parse_with_llm(text: str, proxy: ProxyClient) -> Optional[ParseResult]:
    """使用 LLM 兜底解析记账指令

    Args:
        text: 用户输入的自然语言
        proxy: 代理客户端实例

    Returns:
        ParseResult 或 None（LLM 也失败时）
    """
    logger.info("正则解析失败，触发 LLM 兜底: %s", text[:50])

    try:
        raw_response = proxy.chat(SYSTEM_PROMPT, text, max_tokens=200, temperature=0)
        return _extract_json(raw_response, text)
    except Exception as e:
        logger.error("LLM 兜底调用失败: %s", e)
        return None


def _extract_json(raw: str, text: str) -> Optional[ParseResult]:
    """从 LLM 响应中提取 JSON 并解析为 ParseResult"""
    raw = raw.strip()

    # 尝试提取 markdown 代码块中的 JSON
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)

    # 尝试直接找 JSON 对象
    m = re.search(r"\{[^{}]*\"type\"[^{}]*\}", raw)
    if not m:
        m = re.search(r"\{[^{}]+\}", raw)

    if not m:
        logger.warning("LLM 响应中未找到 JSON: %s", raw[:200])
        return None

    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("JSON 解析失败: %s", m.group(0)[:200])
        return None

    return ParseResult(
        success=True,
        type=RecordType.INCOME if data.get("type") == "收入" else RecordType.EXPENSE,
        amount=float(data.get("amount", 0)),
        category=Category.from_value(data.get("category", "其他")),
        date=data.get("date", date.today().isoformat()),
        note=data.get("note", text[:30]),
        raw_text=text,
        source="llm",
    )
