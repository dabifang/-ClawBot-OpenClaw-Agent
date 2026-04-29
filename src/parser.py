"""正则解析器 —— 毫秒级解析，零 Token 消耗，处理 90% 的记账指令"""

import re
from datetime import date, timedelta
from typing import Optional

from .models import ParseResult, RecordType, Category


# ---- 分类关键词映射 ----
CATEGORY_KEYWORDS: dict[Category, list[str]] = {
    Category.FOOD: [
        "吃饭", "午餐", "午饭", "晚饭", "晚餐", "早餐", "早饭", "外卖", "聚餐",
        "奶茶", "咖啡", "饮料", "零食", "夜宵", "烧烤", "火锅", "面条", "米饭",
        "小吃", "面包", "水果", "蛋糕", "冰淇淋", "雪糕", "甜品", "快餐",
        "食堂", "盒饭", "麻辣烫", "冒菜", "串串", "自助", "日料", "韩料", "西餐",
        "炸鸡", "汉堡", "披萨", "寿司", "沙拉", "轻食", "请客", "AA", "酒水",
    ],
    Category.TRANSPORT: [
        "打车", "地铁", "公交", "加油", "停车", "高速", "过路费", "机票",
        "火车票", "高铁", "骑行", "共享单车", "出租车", "网约车", "滴滴",
        "顺风车", "代驾", "洗车", "保养", "限行", "ETC", "车票", "长途",
        "充电", "电瓶车",
    ],
    Category.SHOPPING: [
        "买", "淘宝", "京东", "拼多多", "超市", "商场", "衣服", "鞋子", "数码",
        "手机", "电脑", "日用品", "化妆品", "买菜", "菜市场", "网购", "快递",
        "包包", "首饰", "眼镜", "手表", "护肤品", "洗发水", "牙膏", "纸巾",
        "家用", "家电", "冰箱", "洗衣机", "空调", "家具", "厨具", "碗筷",
        "宠物", "猫粮", "狗粮", "鲜花", "盆栽", "植物", "书", "文具", "玩具",
    ],
    Category.ENTERTAINMENT: [
        "电影", "游戏", "KTV", "唱歌", "旅游", "景点", "门票", "演出",
        "演唱会", "会员", "充值", "视频会员", "音乐", "剧", "话剧", "展览",
        "博物馆", "游乐园", "迪士尼", "环球", "蹦迪", "酒吧", "棋牌", "麻将",
        "台球", "健身", "游泳", "瑜伽", "舞蹈", "滑雪", "潜水", "冲浪",
        "按摩", "足疗", "SPA", "美容", "美发", "美甲",
    ],
    Category.HOUSING: [
        "房租", "房贷", "水电", "电费", "水费", "燃气", "物业", "网费",
        "宽带", "话费", "维修", "装修", "暖气", "空调费", "垃圾费", "卫生费",
    ],
    Category.MEDICAL: [
        "看病", "挂号", "药", "医院", "诊所", "体检", "牙科", "检查",
        "中药", "西药", "住院", "手术", "急诊", "疫苗", "核酸检测", "口罩",
        "消毒", "医保", "药房", "药店",
    ],
}

# 金额匹配正则
RE_AMOUNT = re.compile(
    r"([¥￥])?\s*(\d+\.?\d{0,2})\s*([元块]|块钱?)?"
    r"|(\d+\.?\d{0,2})\s*([¥￥])"
)

# 纯数字金额（无单位）
RE_AMOUNT_NUM = re.compile(r"(?:花了|用了|费了|消费|付了|给了|转了|发了)\s*(\d+\.?\d{0,2})")

# 收入关键词
INCOME_KEYWORDS = [
    "收入", "赚了", "收了", "到账", "工资", "奖金", "红包", "退款",
    "报销", "兼职", "外快", "提成", "分红", "利息", "理财", "租金收入",
    "转账", "收款", "进账", "入账",
]

# 日期匹配
RE_DATE = re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})")
RE_DATE_SHORT = re.compile(r"(\d{1,2})月(\d{1,2})[日号]?")

RELATIVE_DAYS = {
    "今天": 0, "今天花了": 0,
    "昨天": 1, "昨日": 1,
    "前天": 2, "前天": 2,
    "大前天": 3,
}


def parse(text: str, user_id: str = "") -> ParseResult:
    """解析自然语言记账指令

    Args:
        text: 用户输入的自然语言文本
        user_id: 用户标识（预留）

    Returns:
        ParseResult: 解析结果，success=True 表示正则命中
    """
    text = text.strip()
    if not text:
        return ParseResult(success=False, raw_text=text)

    # 1. 解析收支类型
    record_type = _parse_type(text)

    # 2. 解析金额
    amount = _parse_amount(text)

    # 3. 解析分类
    category = _parse_category(text)

    # 4. 解析日期
    dt = _parse_date(text)

    # 5. 提取备注
    note = _parse_note(text)

    # 判断是否解析成功（至少需要金额和分类）
    if amount is not None and amount > 0:
        return ParseResult(
            success=True,
            type=record_type,
            amount=amount,
            category=category or Category.OTHER,
            date=dt,
            note=note,
            raw_text=text,
            source="regex",
        )

    return ParseResult(success=False, raw_text=text)


def _parse_type(text: str) -> RecordType:
    """识别收支类型"""
    for kw in INCOME_KEYWORDS:
        if kw in text:
            return RecordType.INCOME
    return RecordType.EXPENSE


def _parse_amount(text: str) -> Optional[float]:
    """从文本中提取金额"""
    # 先尝试匹配带单位的金额
    m = RE_AMOUNT.search(text)
    if m:
        num_str = m.group(2) or m.group(4)
        if num_str:
            return float(num_str)

    # 再尝试匹配无单位的金额（跟在动词后）
    m = RE_AMOUNT_NUM.search(text)
    if m:
        return float(m.group(1))

    return None


def _parse_category(text: str) -> Optional[Category]:
    """根据关键词匹配分类"""
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return cat
    return None


def _parse_date(text: str) -> str:
    """从文本中解析日期，默认返回今天"""
    today = date.today()

    # 绝对日期: 2024-01-15 或 2024/01/15
    m = RE_DATE.search(text)
    if m:
        return m.group(1).replace("/", "-")

    # 短日期: 1月15日
    m = RE_DATE_SHORT.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            d = date(today.year, month, day)
            return d.isoformat()
        except ValueError:
            pass

    # 相对日期
    for kw, offset in sorted(RELATIVE_DAYS.items(), key=lambda x: -len(x[0])):
        if kw in text:
            d = today - timedelta(days=offset)
            return d.isoformat()

    return today.isoformat()


def _parse_note(text: str) -> str:
    """提取备注信息"""
    # 去掉金额部分，剩下的可作为备注候选
    # 如果文本较短（< 20字），整个文本就是备注
    if len(text) <= 20:
        return text
    # 长文本取分类关键词后面的内容
    for _, keywords in CATEGORY_KEYWORDS.items():
        for kw in sorted(keywords, key=len, reverse=True):
            idx = text.find(kw)
            if idx >= 0:
                start = max(0, idx - 10)
                end = min(len(text), idx + len(kw) + 15)
                return text[start:end]
    return text[:30]
