"""数据模型定义"""

from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Optional


class RecordType(Enum):
    INCOME = "收入"
    EXPENSE = "支出"


class Category(Enum):
    FOOD = "餐饮"
    TRANSPORT = "交通"
    SHOPPING = "购物"
    ENTERTAINMENT = "娱乐"
    HOUSING = "居住"
    MEDICAL = "医疗"
    OTHER = "其他"

    @classmethod
    def values(cls):
        return [c.value for c in cls]

    @classmethod
    def from_value(cls, v: str):
        for c in cls:
            if c.value == v:
                return c
        return cls.OTHER


@dataclass
class LedgerRecord:
    user_id: str
    type: RecordType
    amount: float
    category: Category
    date: str  # YYYY-MM-DD
    note: str = ""
    id: Optional[int] = None
    created_at: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        d["type"] = self.type.value
        d["category"] = self.category.value
        return d


@dataclass
class ParseResult:
    """解析器输出"""
    success: bool
    type: Optional[RecordType] = None
    amount: Optional[float] = None
    category: Optional[Category] = None
    date: Optional[str] = None
    note: str = ""
    raw_text: str = ""
    source: str = ""  # "regex" 或 "llm"
