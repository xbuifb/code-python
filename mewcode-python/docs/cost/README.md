# Cost 观测系统 — 交付说明

> 范围：MewCode 终端 AI 编程助手的成本与延迟观测模块（`mewcode/cost/`）。
> 版本：v0.2（commit `566f909`）。本文档与该 commit 的真实实现一致。

---

## 1. README：怎么启动、怎么跑、怎么验证

### 1.1 环境要求

- Python ≥ 3.11（实测 3.12.4，venv 位于 `.venv/`）
- 依赖见 `pyproject.toml`：`anthropic`、`openai`、`pyyaml`、`textual` 等

### 1.2 启动 Agent

```bash
# 交互式 TUI（默认入口）
mewcode

# 非交互式：执行单条 prompt 后输出到 stdout
mewcode -p "用 ReadFile 读取 MEWCODE.md"

# 远程模式：WebSocket 服务 + 浏览器 UI（⚠️ 见 §4 鉴权缺口）
mewcode --remote
```

进入 TUI 后，发送若干条消息触发 LLM 调用，然后输入斜杠命令查看成本。
下面示例假设已发生 2 次 LLM 调用：一次 `bash` 工具触发 claude-3-5-sonnet（1000 in / 500 out / 100 cr / 200 cc），一次 `grep` 工具触发 gpt-4o（2000 in / 1000 out）。

### `/cost` — 总览（默认）

```
> /cost
成本与延迟（总览）
─────────────
记录数: 2
总成本: $0.0263
Token: 输入 3,000 · 输出 1,500 · 缓存读 100 · 缓存写 200
缓存命中率: 3.0%
平均首 token 延迟: 65 ms
平均总耗时: 650 ms
```

含未知价格模型时，`总成本` 行变为 `价格未知（含未在价格表的模型）` 并追加 `未知价格模型: gpt-5`。

### `/cost by-tool` | `/cost by-model` | `/cost by-agent` — 分桶

按指定维度切片，每桶一行，**已知成本降序、未知价格桶排最后**：

```
> /cost by-tool
成本分桶（按 工具）
─────────────────────────────────────────────
工具                 调用数   Token      成本          平均TTFT  平均耗时
grep                 1       3000       $0.0150       88ms     800ms
bash                 1       1500       $0.0113       42ms     500ms
```

`by-model` 把"工具"列换成"模型"（如 `gpt-4o`、`claude-3-5-sonnet`）；`by-agent` 换成"Agent"（如 `main`、`worker-1`）。桶内任一记录价格未知时该桶成本显示 `未知`。

### `/cost json` — 导出 JSON

输出含 `total` / `by_tool` / `by_model` / `by_agent` / `records` 5 个顶层 key 的 JSON，供离线分析（jupyter / BI 工具消费）：

```
> /cost json
{
  "total": {
    "record_count": 2,
    "total_input": 3000,
    "total_output": 1500,
    "total_cache_read": 100,
    "total_cache_creation": 200,
    "cache_hit_rate": 0.0303,
    "avg_ttft_ms": 65.0,
    "avg_duration_ms": 650.0,
    "total_cost": 0.02628,
    "unknown_models": []
  },
  "by_tool": [ ... ],
  "by_model": [ ... ],
  "by_agent": [ ... ],
  "records": [ ... ]
}
```

### `/cost reload` — 热加载价格表

改完 `~/.mewcode/pricing.yaml` 后不必重启 Agent：

```
> /cost reload
价格表已重载，共 14 条模型记录
来源：~/.mewcode/pricing.yaml（覆盖默认表同名模型）
```

`pricing.yaml` 格式（4 个字段，单位 USD/百万 token）：

```yaml
my-custom-model:
  input_per_mtok: 5.0
  output_per_mtok: 20.0
  cache_read_per_mtok: 0.5      # 可选，默认 0
  cache_creation_per_mtok: 6.25  # 可选，默认 0
```

### `/cost history` — 跨会话历史

列出所有持久化会话（按最近使用排序）：

```
> /cost history
成本历史（按最近使用排序）
─────────────────────────────────────────────
会话 ID                            调用数   成本          首次调用            最后调用
a1b2c3d4e5f6...                    2       $0.0263       2026-09-28 14:30   2026-09-28 14:35
```

查指定会话明细（复用 total 渲染）：

```
> /cost history a1b2c3d4e5f6
会话成本明细：a1b2c3d4e5f6
─────────────────────────────────────────────
成本与延迟（总览）
─────────────
记录数: 2
总成本: $0.0263
...
```

### 边界提示（非正常路径）

| 输入 | 输出 |
|---|---|
| `/cost foobar` | `未知子命令: foobar` + 列出可用子命令 |
| `/cost`（agent 未注入 ledger） | `成本账本未启用（agent 未注入 cost_ledger）` |
| `/cost history`（无 CostStore） | `成本持久化未启用（agent 未绑定 CostStore）` |

### 1.3 跑测试

```bash
# 全量（606 passed, 3 skipped, 0 failed）
.venv\Scripts\python.exe -m pytest tests/ -q

# 只跑 cost 相关（109 个）
.venv\Scripts\python.exe -m pytest tests/test_ledger.py tests/test_store.py \
  tests/test_pricing.py tests/test_report.py tests/test_commands.py::TestCostHandler \
  tests/test_teams.py::TestCostAggregation \
  tests/test_agent.py::test_cost_ledger_records_single_llm_call \
  tests/test_agent.py::test_cost_ledger_records_cache_tokens_and_tool_attribution -q
```

### 1.4 验证主链路（最快路径）

```bash
.venv\Scripts\python.exe -m pytest \
  tests/test_agent.py::test_cost_ledger_records_single_llm_call -v
```

这条测试跑一次 `agent.run()`，断言 `cost_ledger` 写入了 1 条记录、`total_cost == 0.0105`（手算对齐）。**它是"Agent 真的记录了 LLM 成本"这一核心声明的唯一证据**，改 agent.py 的 cost 注入路径后必须先跑它。

---

## 2. 设计说明：为什么这么设计，核心结构是什么

### 2.1 设计目标

观测系统不能拖垮主流程。三条硬约束决定了所有取舍：

1. **观测失败不能阻断 LLM 调用** — 所有 cost 写入路径用 `try/except` 兜底，失败只 `log.warning`。
2. **价格表加载失败不能阻断启动** — `_load_user_pricing()` 失败一律回退空表，绝不抛。
3. **坏数据不能污染聚合** — 负 token 拒收；坏 jsonl 行跳过；坏 cost_report 消息跳过。

### 2.2 核心结构（6 个文件）

```
mewcode/cost/
├── record.py     CostRecord — 单次 LLM 调用的原始记录（frozen dataclass）
├── pricing.py    Price + 价格表（内置 Anthropic/OpenAI + 用户 yaml 覆盖）
├── ledger.py     CostLedger — 会话级账本：append / total / aggregate / to_json / from_json
├── store.py      CostStore — 跨会话 jsonl 持久化
├── report.py     render_text / render_json / render_history — 渲染层
└── (handlers/cost.py)  /cost 斜杠命令分发
```

**数据流**：

```
LLM 调用结束
  └─ agent.py 在 stream 末尾 append CostRecord(model, tokens, ttft, ...)
       └─ CostLedger._records（内存）+ CostStore.append（落盘 .mewcode/cost/{sid}.jsonl）
  └─ /cost 命令 → render_text(ledger) / render_json(ledger) → 用户看到
```

**子 Agent 聚合**（多进程 worktree 场景）：

```
worker Agent 退出前
  └─ ledger.to_json() → 写 mailbox（type="cost_report"）
lead Agent drain_lead_mailbox()
  └─ CostLedger.from_json(msg.text) → lead.extend(records) → 合并到主账本
```

### 2.3 关键设计取舍

| 取舍 | 原因 |
|---|---|
| 单 Agent + 单事件循环不加锁 | 当前架构无并发写入；引入子 Agent 跨进程回传时走 mailbox 序列化，不走共享内存锁 |
| `total_cost = None` 表示存在未知价格模型 | 比"显示 0 误导用户免费"诚实；`unknown_models` 列出具体模型名供用户补价格表 |
| `cache_hit_rate = cache_read / (input + cache_read + cache_creation)` | 与 `conversation.py` 的 baseline_tokens 口径一致（input 已排除缓存分量，三者相加才是真实 prompt 规模） |
| `_extract_last_tool_name` 取最后一个 tool call | 单轮归因的最简一致规则；不引入"哪个工具贡献了多少"的复杂归因 |
| 落盘用 append + flush，不 fsync | 崩溃最多丢最后一条未 flush 记录，可接受；fsync 会拖慢每轮 LLM 调用 |

---

## 3. 测试说明：验证了什么，还有什么没有验证

### 3.1 已验证（109 个 cost 相关测试）

| 层 | 文件 | 覆盖 |
|---|---|---|
| 价格表 | `test_pricing.py` | 已知/未知模型查表、cache 计费、reload 不丢内置表 |
| 账本 | `test_ledger.py` (23) | append 累积、负 token 拒收、cache_hit_rate clamp、unknown_models 去重、to_json/from_json 往返、extend 跳过坏记录、**aggregate 排序降序+未知末尾** |
| 持久化 | `test_store.py` | append/load 往返、session 隔离、坏行跳过、list_sessions 按 mtime 排序与 total_cost 聚合 |
| 渲染 | `test_report.py` | render_json 5 个顶层 key、by_tool/by_model 分桶、空账本返回空列表、render_history 截断 |
| 命令 | `test_commands.py::TestCostHandler` (7) | total / by-tool / json / reload / history(无 store 提示) / 未知子命令 / ledger 未注入 |
| Agent 端到端 | `test_agent.py` (2) | `agent.run()` 后 ledger 有记录且 `total_cost==0.0105`（手算对齐）；cache+tool 归因（`tool_name=="ReadFile"`） |
| 子 Agent 聚合 | `test_teams.py::TestCostAggregation` (3) | worker→mailbox→lead merge 全链路（`total_cost==0.0285` 手算对齐）；坏 payload 不中断 drain；无 sink 静默丢弃 |

### 3.2 没有验证（已知缺口）

| 缺口 | 严重度 | 原因 |
|---|---|---|
| TTFT/duration 的**精确数值** | 低 | 测试只断言 `>= 0` / `> 0`，未断言具体 ms。`first_chunk_perf` 用 `time.perf_counter()` 差值，依赖真实计时，难以钉死精确值 |
| `render_text` by-tool/by-model/by-agent 的**文本格式细节**（列宽、截断） | 低 | 只测了 `render_json` 的结构，文本渲染只断言关键关键词存在 |
| OpenAI provider 在真实 API 下 `cache_read` 是否正确进 CostRecord | 中 | MockLLMClient 不走真实 HTTP；client.py 的 `prompt_tokens_details.cached_tokens` 解析逻辑有代码但无集成测试 |
| 真实 Anthropic API 的 thinking 模型 cost 计费 | 中 | thinking token 的计费口径未在价格表区分（当前按普通 input/output 计） |
| 多 worker 并发回传 cost_report 的竞态 | 低 | 当前单事件循环模型下不触发；加锁是引入真并发后才需要 |

---

## 4. 风险与限制：哪些问题是已知的，为什么当前仍可接受

### 4.1 P0（已知但仍可接受的限制）

**R1 — Remote 模式无鉴权**
- 现状：`mewcode --remote` 在 `0.0.0.0:18888` 启 WebSocket，无 token / Bearer / origin 校验（见 `remote.py`）。
- 为何仍可交付：cost 模块本身不依赖 remote；remote 鉴权是**独立模块**，memory 已规划为下一个 P0 修复项（生成一次性 token + 绑定 127.0.0.1）。当前 cost 交付不阻塞于它。
- 缓解：不要在不可信网络开 `--remote`；只用本地或 `-p` 模式。

### 4.2 P1（功能性限制）

**R2 — 价格表覆盖有限**
- 现状：内置 Anthropic Claude 3/3.5 全系 + OpenAI gpt-4o/4o-mini/4-turbo。未收录的模型 `total_cost = None`。
- 为何可接受：用户可通过 `~/.mewcode/pricing.yaml` 追加任意模型，`/cost reload` 热加载；`unknown_models` 会显式列出缺哪些。
- 不可接受时：补 yaml 或在 `pricing.py._DEFAULT_PRICING` 加条目。

**R3 — 子 Agent 聚合仅覆盖 worktree/teammate 场景**
- 现状：worker 退出前 `to_json()` 写邮箱，lead `drain` 后合并。**不覆盖** AgentTool 内联子 Agent（同进程，未走 mailbox）。
- 为何可接受：同进程子 Agent 可直接共享 `cost_ledger` 实例注入（`Agent(cost_ledger=parent_ledger)`），不需要邮箱路径。memory 早期笔记把"sub-Agent aggregation"列为已知限制，**实际 worktree 路径已端到端测试通过**（§3.1），该笔记已 stale。

**R4 — 持久化崩溃可能丢最后一条**
- 现状：`CostStore.append` 用 `write + flush`，不 `fsync`。
- 为何可接受：观测丢一条不影响主流程；进程崩溃丢的是"最后一条未 flush"，可接受。加 fsync 会拖慢每轮 LLM 调用。

### 4.3 P2（精度限制）

**R5 — thinking token 计费未区分**
- Anthropic extended thinking 的 thinking token 计费口径与普通 output token 不同，当前价格表未区分。用 thinking 模型时成本会略偏。

**R6 — OpenAI cache_creation 固定 0**
- OpenAI 自动 prompt caching 不额外收费，价格表 `cache_creation_per_mtok=0` 正确；但部分兼容 provider（vLLM/Ollama）不上报 `cached_tokens`，导致 `cache_read=0`，成本略高于实际（少算缓存折扣）。

---

## 5. 演示顺序：如果只有几分钟

按"从证据最强到价值最高"的顺序，5 步约 3-4 分钟：

### 步骤 1（30 秒）— 跑核心端到端测试，证明主链路工作

```bash
.venv\Scripts\python.exe -m pytest \
  tests/test_agent.py::test_cost_ledger_records_single_llm_call -v
```

一句话：**"这条测试证明 Agent 跑完一轮 LLM 后，cost 账本真的有记录，金额和手算一致。"**

### 步骤 2（60 秒）— 跑子 Agent 聚合，证明多 Agent 场景

```bash
.venv\Scripts\python.exe -m pytest \
  tests/test_teams.py::TestCostAggregation::test_worker_cost_report_merges_into_lead_ledger -v
```

一句话：**"worker 的成本通过邮箱序列化回传，lead 合并后总额对得上（0.0285）。"**

### 步骤 3（60 秒）— 跑全量 cost 测试，证明覆盖面

```bash
.venv\Scripts\python.exe -m pytest tests/test_ledger.py tests/test_store.py \
  tests/test_pricing.py tests/test_report.py tests/test_commands.py::TestCostHandler -q
```

一句话：**"109 个测试覆盖价格表、账本、持久化、渲染、命令分发。"**

### 步骤 4（60 秒）— 演示 /cost 命令（若有 API key）

```
mewcode
> 帮我读一下 MEWCODE.md
> /cost
> /cost by-tool
```

一句话：**"用户唯一入口是 /cost，7 个子命令覆盖总览/分桶/导出/历史。"**

### 步骤 5（30 秒）— 诚实收口

指到 §4 风险表，点出 R1（remote 无鉴权，独立模块下一轮修）和 R5（thinking 计费未区分）。

一句话：**"已知的限制都列在这里，没有藏。"**

---

## 附：关键文件索引

| 想看什么 | 看哪里 |
|---|---|
| 单次 LLM 调用如何记录成本 | `mewcode/agent.py` 搜 `cost_ledger.append`（两处：交互式 ~L634，-p 模式 ~L1174） |
| 价格表 / 加载用户 yaml | `mewcode/cost/pricing.py` |
| 账本聚合公式（total / cache_hit_rate） | `mewcode/cost/ledger.py` 的 `total()` |
| 持久化文件布局 | `mewcode/cost/store.py`（`.mewcode/cost/{session_id}.jsonl`） |
| /cost 命令分发 | `mewcode/commands/handlers/cost.py` |
| 子 Agent cost 回传 | `mewcode/teams/manager.py` 的 `_merge_cost_report` + `mewcode/__main__.py` ~L582 |
| 排序行为被哪条测试钉死 | `tests/test_ledger.py::test_aggregate_sort_known_descending_unknown_last` |
