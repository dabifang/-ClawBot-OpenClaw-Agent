# 记账 Agent

基于 **微信 ClawBot + 腾讯云 OpenClaw** 的轻量化自动化记账 Agent，专为个人及 3-5 人小团队的日常收支管理设计。

## 核心痛点

- **传统记账 APP 操作繁琐**：手动打开输入，80% 的人会因忘记记录导致数据失真
- **小团队数据不同步**：共用账本时每次对账需要手动汇总，耗时费力
- **OpenClaw 原生 400 bug**：思考模式模型参数校验问题，无法正常使用 DeepSeek 等大模型

## 核心逻辑流

```
微信输入（自然语言）
    ↓
OpenClaw 转发
    ↓
┌─ 正则解析器（90% 请求）──→ 毫秒级响应，Token 消耗为 0
│        ↓ 失败
└─ LLM 兜底（10% 请求）──→ 本地反向代理清洗参数后调用大模型
    ↓
SQLite 写入（多用户独立账本隔离）
    ↓
腾讯文档同步（实时/批量）
```

采用 **「正则快速解析 + LLM 兜底处理」** 的双层架构：

- **90%** 的标准收支指令通过正则毫秒级解析，**Token 消耗为 0**
- 剩余复杂指令通过本地反向代理中转层调用大模型
- 中转层同时实现**思考内容自动剥离**、**请求参数标准化**、**响应格式校验**三大功能，彻底解决 OpenClaw 的 400 报错问题

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制配置文件
cp config.yaml config.local.yaml

# 编辑 config.local.yaml，填写：
#   - DeepSeek API Key
#   - 腾讯文档 OAuth 凭证（可选）
```

或通过环境变量：

```bash
export DEEPSEEK_API_KEY=sk-your-key
export PORT=5888
```

### 3. 启动

```bash
python app.py
```

服务默认运行在 `http://localhost:5888`。

### 4. 测试

```bash
# 健康检查
curl http://localhost:5888/api/health

# 添加记账
curl -X POST http://localhost:5888/api/ledger/add \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user_001","text":"今天午饭花了30块"}'

# 查询记录
curl "http://localhost:5888/api/ledger/list?user_id=user_001"

# 月度统计
curl "http://localhost:5888/api/ledger/stats?user_id=user_001&month=2026-04"
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/ledger/add` | 添加记账记录 |
| `GET` | `/api/ledger/list` | 查询记录列表 |
| `GET` | `/api/ledger/stats` | 月度收支统计 |
| `DELETE` | `/api/ledger/delete` | 删除记录 |
| `POST` | `/api/proxy/chat` | OpenClaw 代理转发 |
| `GET` | `/oauth/authorize` | 腾讯文档 OAuth 授权 |
| `GET` | `/oauth/callback` | OAuth 回调 |

## 项目结构

```
├── app.py                  # 主入口，Flask 服务
├── config.yaml             # 配置文件
├── requirements.txt        # Python 依赖
├── src/
│   ├── proxy.py            # 反向代理中转层（解决 400 报错）
│   ├── parser.py           # 正则解析器（90% 请求，零 Token）
│   ├── llm_fallback.py     # LLM 兜底（10% 请求）
│   ├── ledger.py           # 账本管理 + SQLite CRUD
│   ├── tencent_docs.py     # 腾讯文档 OAuth + 写入
│   └── models.py           # 数据模型
└── tests/
    └── test_parser.py      # 解析器单元测试
```

## 性能指标

- 单条记账响应时间：正则命中 **<10ms**，LLM 兜底 **<2s**
- Token 消耗较原生调用降低 **85%**
- 支持多用户独立账本隔离
- SQLite WAL 模式，支持高并发写入

## 腾讯文档同步

1. 在 [腾讯文档开放平台](https://docs.qq.com/open) 注册应用
2. 获取 `client_id` 和 `client_secret`
3. 在 `config.local.yaml` 中启用并填写凭证
4. 访问 `/oauth/authorize` 完成授权
5. 未启用时默认使用 Mock 模式（日志输出）

## 许可证

MIT
