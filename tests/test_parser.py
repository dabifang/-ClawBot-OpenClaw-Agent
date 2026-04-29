"""正则解析器单元测试"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from src.parser import parse
from src.models import RecordType, Category


def test_basic_expense():
    """基础支出：金额 + 分类关键词"""
    result = parse("今天午饭花了30块")
    assert result.success
    assert result.type == RecordType.EXPENSE
    assert result.amount == 30.0
    assert result.category == Category.FOOD
    assert result.date == date.today().isoformat()


def test_decimal_amount():
    """金额带小数"""
    result = parse("打车花了23.5元")
    assert result.success
    assert result.amount == 23.5
    assert result.category == Category.TRANSPORT


def test_yuan_symbol():
    """¥ 符号"""
    result = parse("¥50 买奶茶")
    assert result.success
    assert result.amount == 50.0
    assert result.category == Category.FOOD


def test_no_unit():
    """无单位的金额"""
    result = parse("菜市场花了80块买菜")
    assert result.success
    assert result.amount == 80.0
    assert result.category in (Category.FOOD, Category.SHOPPING)


def test_income():
    """收入识别"""
    result = parse("工资到账 15000")
    assert result.success
    assert result.type == RecordType.INCOME
    assert result.amount == 15000.0


def test_medical():
    """医疗分类"""
    result = parse("去医院看病花了200")
    assert result.success
    assert result.amount == 200.0
    assert result.category == Category.MEDICAL


def test_entertainment():
    """娱乐分类"""
    result = parse("看电影花了80块")
    assert result.success
    assert result.amount == 80.0
    assert result.category == Category.ENTERTAINMENT


def test_complex_input():
    """复杂输入：含日期"""
    result = parse("昨天和朋友聚餐 AA 花了 156 元")
    assert result.success
    assert result.amount == 156.0
    assert result.category == Category.FOOD


def test_unsupported_input():
    """无法解析的输入返回失败"""
    result = parse("今天天气真好")
    assert not result.success


if __name__ == "__main__":
    test_basic_expense()
    test_decimal_amount()
    test_yuan_symbol()
    test_no_unit()
    test_income()
    test_medical()
    test_entertainment()
    test_complex_input()
    test_unsupported_input()
    print("所有测试通过！")
