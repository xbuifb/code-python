# MewCode

A terminal AI coding assistant.

## 环境要求

- Python >= 3.11
- 操作系统：Windows / macOS / Linux

## 安装

```bash
# 克隆仓库
git clone <repo-url> mewcode-python
cd mewcode-python

# 创建并激活虚拟环境（推荐）
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 安装项目（含命令行入口 mewcode）
pip install -e .
```

## 配置

MewCode 启动时按以下顺序查找配置文件并逐层合并：

1. `~/.mewcode/config.yaml`（全局默认）
2. `<project>/.mewcode/config.yaml`（项目共享）
3. `<project>/.mewcode/config.local.yaml`（本地覆盖，建议加入 .gitignore）

任一文件不存在即跳过；三者全缺时启动会报 `ConfigError`。

最小配置示例（`.mewcode/config.yaml`）：

```yaml
providers:
  - name: anthropic-official
    protocol: anthropic
    base_url: https://api.anthropic.com
    api_key: "your-api-key-here"
    model: claude-sonnet-4-20250514

permission_mode: default
```

OpenAI 兼容服务只需把 `protocol` 改为 `openai` 并调整 `base_url` 与 `model`。

## 启动

### 1. 交互式 TUI（默认）

```bash
mewcode
```

或显式指定权限模式（覆盖 `config.yaml`）：

```bash
mewcode --mode default
```

### 2. 非交互单轮执行

```bash
mewcode -p "解释 mewcode/agent.py 的入口逻辑"
```

输出格式可选：

```bash
mewcode -p "..." --output-format text         # 默认，仅打印最终文本
mewcode -p "..." --output-format stream-json  # NDJSON 事件流，便于脚本解析
```

### 3. Remote 模式（浏览器 UI）

启动 token 保护的 WebSocket 服务器，默认绑定 `127.0.0.1:18888`：

```bash
mewcode --remote
```

启动后在浏览器访问 `http://localhost:18888`，并附带启动时打印的一次性 `?token=xxx` 查询参数。

### 4. 队友 worker 模式

由 Lead 在创建团队时自动拉起，一般无需手动调用。若需手工启动（对齐 `build_teammate_cli` 产出）：

```bash
mewcode --teammate --team-name <team> --agent-name <agent>
```

## 运行验证

```bash
# 跑单元测试（需安装 dev 依赖）
pip install pytest pytest-asyncio   # 或使用 PEP 735：pip install --group dev
pytest
```

## 日志

运行时日志写入工作目录下的 `.mewcode/debug.log`，TUI 启动前会自动创建 `.mewcode/` 目录。
