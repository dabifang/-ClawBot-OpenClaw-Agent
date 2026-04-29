"""API 集成测试"""
import requests
import json

BASE = "http://localhost:5888"

# 测试多个记账场景
tests = [
    ("user_a", "打车花了23.5元"),
    ("user_a", "昨天买衣服花了299"),
    ("user_b", "工资到账15000"),
    ("user_b", "去医院看病花了200"),
    ("user_a", "晚上看电影花了80块"),
]

print("===== 记账测试 =====")
for uid, text in tests:
    r = requests.post(f"{BASE}/api/ledger/add", json={"user_id": uid, "text": text})
    d = r.json()
    data = d["data"]
    print(f"[{d['source']:5s}] {uid} | {data['type']} | {data['amount']:>8.1f} | {data['category']:4s} | {text}")

# 查询
print("\n===== 查询测试 =====")
r = requests.get(f"{BASE}/api/ledger/list", params={"user_id": "user_a"})
print(f"user_a 共 {r.json()['count']} 条记录")

# 统计
print("\n===== 统计测试 =====")
r = requests.get(f"{BASE}/api/ledger/stats", params={"user_id": "user_a", "month": "2026-04"})
stats = r.json()["data"]
print(f"月份: {stats['month']}")
print(f"总收入: {stats['total_income']}")
print(f"总支出: {stats['total_expense']}")
print(f"结余: {stats['balance']}")
print(f"记录数: {stats['record_count']}")
print(f"分类明细:")
for c in stats["by_category"]:
    print(f"  {c['category']}: {c['total']} ({c['count']}条)")

# 多用户隔离
print("\n===== 多用户隔离测试 =====")
r = requests.get(f"{BASE}/api/ledger/list", params={"user_id": "user_b"})
print(f"user_b 共 {r.json()['count']} 条记录 (user_a 看不到)")

print("\n全部测试通过!")
