"""
记账 Agent 主入口
==================
基于微信 ClawBot + 腾讯云 OpenClaw 的自动化记账服务。

启动: python app.py
默认端口: 5888

核心流程:
  微信消息 → OpenClaw 转发 → 正则解析(90%, 零Token) → LLM兜底(10%)
  → SQLite 写入(多用户隔离) → 腾讯文档同步
"""

import logging
import os
import sys
from datetime import date

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from src.ledger import LedgerDB
from src.llm_fallback import parse_with_llm
from src.models import Category, LedgerRecord, ParseResult, RecordType
from src.parser import parse
from src.proxy import ProxyClient, create_proxy_route
from src.tencent_docs import TencentDocsSync

# 加载环境变量
load_dotenv()

# ---- 配置加载 ----
def load_config():
    """加载配置文件，优先级：config.local.yaml > config.yaml > 环境变量"""
    config = {}

    # 基础配置
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    local_config_path = os.path.join(os.path.dirname(__file__), "config.local.yaml")

    for path in [config_path, local_config_path]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    _deep_update(config, data)

    # 环境变量覆盖
    if os.getenv("DEEPSEEK_API_KEY"):
        config.setdefault("llm", {})["api_key"] = os.getenv("DEEPSEEK_API_KEY")
    if os.getenv("PORT"):
        config.setdefault("server", {})["port"] = int(os.getenv("PORT"))

    return config


def _deep_update(base: dict, update: dict):
    for k, v in update.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


# ---- 应用初始化 ----
config = load_config()
app = Flask(__name__)

# 日志配置
log_level = logging.DEBUG if config.get("server", {}).get("debug") else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("app")

# 初始化各模块
db_path = config.get("database", {}).get("path", "./data/ledger.db")
db = LedgerDB(db_path)

tencent_config = config.get("tencent_docs", {})
td_sync = TencentDocsSync(
    enabled=tencent_config.get("enabled", False),
    client_id=tencent_config.get("client_id", ""),
    client_secret=tencent_config.get("client_secret", ""),
    spreadsheet_id=tencent_config.get("spreadsheet_id", ""),
    sheet_name=tencent_config.get("sheet_name", "记账记录"),
    redirect_uri=tencent_config.get("redirect_uri", "http://localhost:5888/oauth/callback"),
    sync_mode=tencent_config.get("sync_mode", "realtime"),
)

llm_config = config.get("llm", {})
proxy_client = ProxyClient(
    api_url=llm_config.get("api_url", "https://api.deepseek.com/v1/chat/completions"),
    api_key=llm_config.get("api_key", ""),
    model=llm_config.get("model", "deepseek-chat"),
)


# ---- API 路由 ----

@app.route("/api/health", methods=["GET"])
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "version": "1.0.0",
        "modules": {
            "ledger_db": "ok",
            "tencent_docs": "enabled" if td_sync.enabled else "disabled (mock)",
            "llm_proxy": "configured" if llm_config.get("api_key", "").startswith("sk-") else "not configured",
        },
    })


@app.route("/api/ledger/add", methods=["POST"])
def add_record():
    """添加记账记录

    请求体:
    {
        "user_id": "user_001",
        "text": "今天午饭花了30块"
    }

    响应:
    {
        "success": true,
        "data": { "id": 1, "type": "支出", "amount": 30.0, "category": "餐饮", ... },
        "source": "regex",  // 或 "llm"
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    user_id = data.get("user_id", "").strip()
    text = data.get("text", "").strip()

    if not user_id:
        return jsonify({"success": False, "error": "缺少 user_id"}), 400
    if not text:
        return jsonify({"success": False, "error": "缺少 text"}), 400

    # 1. 正则解析（优先，零 Token）
    result = parse(text, user_id)

    # 2. 正则失败 → LLM 兜底
    if not result.success:
        result = parse_with_llm(text, proxy_client)
        if not result or not result.success:
            return jsonify({
                "success": False,
                "error": "无法解析该记账指令，请尝试更明确的表述",
                "raw_text": text,
            }), 422

    # 3. 写入数据库
    record = LedgerRecord(
        user_id=user_id,
        type=result.type or RecordType.EXPENSE,
        amount=result.amount or 0,
        category=result.category or Category.OTHER,
        date=result.date or date.today().isoformat(),
        note=result.note or text,
    )
    record_id = db.add(record)

    # 4. 同步腾讯文档
    td_sync.append_record(record)

    return jsonify({
        "success": True,
        "data": {
            "id": record_id,
            "user_id": user_id,
            "type": record.type.value,
            "amount": record.amount,
            "category": record.category.value,
            "date": record.date,
            "note": record.note,
        },
        "source": result.source,
    })


@app.route("/api/ledger/list", methods=["GET"])
def list_records():
    """查询记账记录

    Query 参数:
        user_id: 必填
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        category: 分类筛选
        limit: 每页条数（默认 100）
        offset: 偏移量（默认 0）
    """
    user_id = request.args.get("user_id", "").strip()
    if not user_id:
        return jsonify({"success": False, "error": "缺少 user_id"}), 400

    records = db.query(
        user_id=user_id,
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
        category=request.args.get("category"),
        limit=min(int(request.args.get("limit", 100)), 500),
        offset=int(request.args.get("offset", 0)),
    )

    return jsonify({
        "success": True,
        "data": records,
        "count": len(records),
    })


@app.route("/api/ledger/stats", methods=["GET"])
def monthly_stats():
    """月度收支统计

    Query 参数:
        user_id: 必填
        month: 月份，如 "2026-04"（默认本月）
    """
    user_id = request.args.get("user_id", "").strip()
    if not user_id:
        return jsonify({"success": False, "error": "缺少 user_id"}), 400

    month = request.args.get("month", date.today().strftime("%Y-%m"))

    stats = db.stats(user_id, month)

    return jsonify({
        "success": True,
        "data": stats,
    })


@app.route("/api/ledger/delete", methods=["DELETE"])
def delete_record():
    """删除记账记录

    请求体:
    {
        "user_id": "user_001",
        "record_id": 1
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体不能为空"}), 400

    user_id = data.get("user_id", "").strip()
    record_id = data.get("record_id")

    if not user_id or not record_id:
        return jsonify({"success": False, "error": "缺少 user_id 或 record_id"}), 400

    result = db.delete(int(record_id), user_id)

    return jsonify({
        "success": result,
        "message": "已删除" if result else "记录不存在或无权限",
    })


# ---- 反向代理路由（OpenClaw 对接） ----
app.add_url_rule(
    "/api/proxy/chat",
    "proxy_chat",
    create_proxy_route(proxy_client),
    methods=["POST"],
)


# ---- OAuth 路由（腾讯文档授权） ----
@app.route("/oauth/authorize", methods=["GET"])
def oauth_authorize():
    """跳转到腾讯文档 OAuth 授权页面"""
    if not td_sync.enabled:
        return jsonify({"success": False, "error": "腾讯文档同步未启用"}), 400
    auth_url = td_sync.get_auth_url()
    return f'<html><body><a href="{auth_url}">点击授权腾讯文档</a></body></html>'


@app.route("/oauth/callback", methods=["GET"])
def oauth_callback():
    """OAuth 回调处理"""
    code = request.args.get("code")
    if not code:
        return jsonify({"success": False, "error": "缺少授权码"}), 400
    ok = td_sync.exchange_code(code)
    html = "<h2>授权成功！</h2>" if ok else "<h2>授权失败，请重试</h2>"
    return html


# ---- 启动入口 ----
if __name__ == "__main__":
    server_config = config.get("server", {})
    host = server_config.get("host", "0.0.0.0")
    port = server_config.get("port", 5888)
    debug = server_config.get("debug", False)

    logger.info("=" * 50)
    logger.info("记账 Agent 启动中...")
    logger.info("地址: http://%s:%d", host, port)
    logger.info("健康检查: http://localhost:%d/api/health", port)
    logger.info("腾讯文档: %s", "已启用" if td_sync.enabled else "Mock 模式")
    logger.info("=" * 50)

    app.run(host=host, port=port, debug=debug)
