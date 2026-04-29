"""腾讯文档同步模块

支持两种模式：
- Mock 模式（默认）：日志记录，不实际调用 API，方便本地测试
- 真实模式：通过腾讯文档 Open API 实时同步到在线表格

腾讯文档 Open API 文档: https://docs.qq.com/open/document/app/openapi/v2/
"""

import json
import logging
from datetime import datetime
from typing import Optional

import requests

from .models import LedgerRecord

logger = logging.getLogger(__name__)


class TencentDocsSync:
    """腾讯文档同步客户端"""

    def __init__(
        self,
        enabled: bool = False,
        client_id: str = "",
        client_secret: str = "",
        spreadsheet_id: str = "",
        sheet_name: str = "记账记录",
        redirect_uri: str = "http://localhost:5888/oauth/callback",
        sync_mode: str = "realtime",
    ):
        self.enabled = enabled
        self.client_id = client_id
        self.client_secret = client_secret
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.redirect_uri = redirect_uri
        self.sync_mode = sync_mode
        self._access_token: Optional[str] = None
        self._token_expires: float = 0

        if not enabled:
            logger.info("腾讯文档同步未启用（Mock 模式）")

    # ---- OAuth 2.0 ----

    def get_auth_url(self) -> str:
        """获取 OAuth 授权链接"""
        return (
            "https://docs.qq.com/oauth/v2/authorize"
            f"?client_id={self.client_id}"
            "&response_type=code"
            f"&redirect_uri={self.redirect_uri}"
            "&scope=docs.write"
        )

    def exchange_code(self, code: str) -> bool:
        """用授权码换取 access_token"""
        try:
            resp = requests.post(
                "https://docs.qq.com/oauth/v2/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
                timeout=10,
            )
            data = resp.json()
            if "access_token" in data:
                self._access_token = data["access_token"]
                self._token_expires = datetime.now().timestamp() + data.get("expires_in", 7200)
                logger.info("腾讯文档 OAuth 授权成功")
                return True
            logger.error("OAuth 换取 token 失败: %s", data)
            return False
        except Exception as e:
            logger.error("OAuth 请求异常: %s", e)
            return False

    # ---- 数据同步 ----

    def append_record(self, record: LedgerRecord) -> bool:
        """追加一条记账记录到腾讯文档表格

        表格列顺序: 日期 | 类型 | 金额 | 分类 | 备注 | 用户
        """
        if not self.enabled:
            self._mock_append(record)
            return True

        if not self._access_token:
            logger.warning("未授权腾讯文档，跳过同步")
            return False

        row_data = [
            record.date,
            record.type.value,
            str(record.amount),
            record.category.value,
            record.note,
            record.user_id,
        ]

        try:
            resp = requests.post(
                f"https://docs.qq.com/openapi/v2/spreadsheet/{self.spreadsheet_id}/values",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "range": f"{self.sheet_name}!A:F",
                    "values": [row_data],
                    "insertMode": "APPEND",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("已同步到腾讯文档: %s %.2f %s", record.date, record.amount, record.category.value)
                return True
            logger.error("腾讯文档 API 返回错误 %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.error("腾讯文档同步异常: %s", e)
            return False

    def _mock_append(self, record: LedgerRecord):
        """Mock 模式：仅记录日志"""
        logger.info(
            "[Mock] 模拟同步到腾讯文档: 日期=%s 类型=%s 金额=%.2f 分类=%s 备注=%s",
            record.date, record.type.value, record.amount,
            record.category.value, record.note,
        )

    def append_records(self, records: list[LedgerRecord]) -> int:
        """批量追加记录，返回成功数量"""
        count = 0
        for r in records:
            if self.append_record(r):
                count += 1
        return count
