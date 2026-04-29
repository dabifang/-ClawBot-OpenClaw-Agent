"""账本管理 —— SQLite 多用户隔离，CRUD + 月度统计"""

import logging
import os
import sqlite3
from datetime import date, datetime
from threading import Lock
from typing import Optional

from .models import LedgerRecord, RecordType, Category

logger = logging.getLogger(__name__)


class LedgerDB:
    """SQLite 账本数据库，支持多用户隔离"""

    def __init__(self, db_path: str = "./data/ledger.db"):
        self.db_path = db_path
        self._lock = Lock()
        self._init_db()

    def _init_db(self):
        """初始化数据库和表结构"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    date TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_date
                ON records(user_id, date)
            """)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def add(self, record: LedgerRecord) -> int:
        """添加一条记账记录，返回记录 ID"""
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    """INSERT INTO records (user_id, type, amount, category, date, note)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        record.user_id,
                        record.type.value,
                        record.amount,
                        record.category.value,
                        record.date,
                        record.note,
                    ),
                )
                conn.commit()
                record_id = cursor.lastrowid
                logger.info("新增记录 id=%d user=%s %s %.2f %s",
                            record_id, record.user_id, record.type.value,
                            record.amount, record.category.value)
                return record_id

    def query(
        self,
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """查询记账记录"""
        sql = "SELECT * FROM records WHERE user_id = ?"
        params = [user_id]

        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
        if category:
            sql += " AND category = ?"
            params.append(category)

        sql += " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def stats(self, user_id: str, month: str) -> dict:
        """月度收支统计

        Args:
            user_id: 用户标识
            month: 月份，如 "2026-04"

        Returns:
            {
                "total_income": 总收入,
                "total_expense": 总支出,
                "by_category": [{"category": "餐饮", "total": 500.0}, ...],
                "count": 记录总数,
            }
        """
        with self._get_conn() as conn:
            # 分类统计
            rows = conn.execute(
                """SELECT category, SUM(amount) as total, COUNT(*) as cnt
                   FROM records
                   WHERE user_id = ? AND date LIKE ?
                   GROUP BY category
                   ORDER BY total DESC""",
                (user_id, f"{month}%"),
            ).fetchall()

            by_category = [{"category": r["category"], "total": r["total"], "count": r["cnt"]}
                           for r in rows]

            # 收入/支出总额
            summary = conn.execute(
                """SELECT type, SUM(amount) as total
                   FROM records
                   WHERE user_id = ? AND date LIKE ?
                   GROUP BY type""",
                (user_id, f"{month}%"),
            ).fetchall()

        total_income = 0.0
        total_expense = 0.0
        for r in summary:
            if r["type"] == "收入":
                total_income = r["total"]
            else:
                total_expense = r["total"]

        return {
            "month": month,
            "total_income": total_income,
            "total_expense": total_expense,
            "balance": total_income - total_expense,
            "by_category": by_category,
            "record_count": sum(c["count"] for c in by_category),
        }

    def delete(self, record_id: int, user_id: str) -> bool:
        """删除一条记录，校验 user_id 防止越权"""
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "DELETE FROM records WHERE id = ? AND user_id = ?",
                    (record_id, user_id),
                )
                conn.commit()
                return cursor.rowcount > 0
