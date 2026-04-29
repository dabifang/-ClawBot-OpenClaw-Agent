"""反向代理中转层 —— 解决 OpenClaw 原生 400 报错问题

三大核心功能：
1. 剥离 reasoning_content（思考内容）—— DeepSeek 思考模型在非思考模式调用时带此字段会 400
2. 标准化请求参数 —— 确保 message 格式与目标模型兼容
3. 校验并修复响应格式 —— 确保返回内容符合 OpenAI 格式规范
"""

import json
import logging
from typing import Optional

import requests
from flask import Request, Response

logger = logging.getLogger(__name__)


def clean_reasoning_content(data: dict) -> dict:
    """递归删除 reasoning_content 字段（DeepSeek V3 非思考模式不识别此字段）"""
    if isinstance(data, dict):
        data.pop("reasoning_content", None)
        for v in data.values():
            clean_reasoning_content(v)
    elif isinstance(data, list):
        for item in data:
            clean_reasoning_content(item)
    return data


def normalize_messages(messages: list) -> list:
    """标准化消息列表，确保每条消息只包含 role 和 content"""
    cleaned = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # 如果 content 是数组（多模态格式），尝试提取纯文本
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            content = " ".join(parts)
        cleaned.append({"role": role, "content": content})
    return cleaned


def normalize_request_body(body: dict) -> dict:
    """标准化整个请求体"""
    body = clean_reasoning_content(body)
    if "messages" in body:
        body["messages"] = normalize_messages(body["messages"])
    # 移除可能不兼容的参数
    body.pop("stop", None)
    body.pop("logprobs", None)
    body.pop("logit_bias", None)
    return body


def validate_response(data: dict) -> dict:
    """校验并修复 LLM 响应格式

    确保返回格式符合 OpenAI chat completion 规范：
    {
      "choices": [{"message": {"role": "assistant", "content": "..."}}],
      ...
    }
    """
    if "choices" not in data:
        # 某些模型返回格式不同，尝试修复
        if "response" in data:
            return {
                "choices": [{"message": {"role": "assistant", "content": data["response"]}}]
            }
        return data

    for choice in data["choices"]:
        if "message" not in choice:
            if "text" in choice:
                choice["message"] = {"role": "assistant", "content": choice["text"]}
            elif "content" in choice:
                choice["message"] = {"role": "assistant", "content": choice["content"]}

    return data


class ProxyClient:
    """LLM API 代理客户端"""

    def __init__(self, api_url: str, api_key: str, model: str = "deepseek-chat"):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def forward(self, request_body: dict, timeout: int = 30) -> dict:
        """转发请求到 LLM API，自动完成清洗→请求→校验全流程"""
        # 1. 清洗请求体
        clean_body = normalize_request_body(request_body)
        clean_body["model"] = self.model

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.debug("转发请求到 %s，已剥离 reasoning_content", self.api_url)

        # 2. 发送请求
        resp = requests.post(
            self.api_url,
            json=clean_body,
            headers=headers,
            timeout=timeout,
        )

        if resp.status_code >= 400:
            logger.error("API 返回错误 %d: %s", resp.status_code, resp.text[:500])
            raise ProxyError(f"API 错误 {resp.status_code}: {resp.text[:200]}")

        # 3. 校验响应
        result = resp.json()
        result = validate_response(result)
        return result

    def chat(self, system_prompt: str, user_message: str, **kwargs) -> str:
        """快捷方法：发送对话并返回纯文本响应"""
        body = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": kwargs.get("temperature", 0),
            "max_tokens": kwargs.get("max_tokens", 200),
        }
        result = self.forward(body, timeout=kwargs.get("timeout", 30))
        return result["choices"][0]["message"]["content"]


class ProxyError(Exception):
    """代理层异常"""
    pass


def create_proxy_route(proxy_client: ProxyClient):
    """创建 Flask 代理路由处理函数"""

    def handle_proxy():
        from flask import request, jsonify

        try:
            body = request.get_json(force=True)
        except Exception:
            return jsonify({"error": "无效的 JSON 请求体"}), 400

        try:
            result = proxy_client.forward(body)
            return jsonify(result)
        except ProxyError as e:
            return jsonify({"error": str(e)}), 502
        except requests.Timeout:
            return jsonify({"error": "上游 API 超时"}), 504
        except Exception as e:
            logger.exception("代理请求异常")
            return jsonify({"error": f"代理异常: {str(e)}"}), 500

    return handle_proxy
