# MewCode

基于 Python 的 AI 编程助手，可通过终端或本地浏览器对话，辅助理解代码、修改文件和执行开发任务。

## 功能

- **多种交互方式**：终端 TUI、浏览器 Remote UI、命令行单次执行。
- **代码与工具调用**：读取和编辑文件、搜索代码、执行命令。
- **模型接入**：Anthropic Messages、OpenAI Responses 和 OpenAI 兼容 Chat Completions 接口。
- **开发协作**：子代理与团队调度、Git worktree 支持。
- **扩展能力**：MCP 服务、Skills 和 Hooks。
- **会话管理**：历史记录、上下文管理和 Token 用量统计。

## 环境要求

- Python **3.11 或更高版本**，建议使用 Python 3.12。
- Git。
- 可用的模型服务 API Key。
- 可选：使用 `npx` 启动 MCP 服务时，需要 Node.js 和 npm。

支持 Windows、macOS 和 Linux。以下快速开始以 Windows PowerShell 为例。

## 快速开始

### 1. 下载项目并安装

```powershell
git clone https://github.com/xbuifb/code-python.git
cd code-python\mewcode-python

# 请先通过 python --version 确认当前 Python >= 3.11
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

下文直接调用虚拟环境中的 Python，无需手动激活环境。所有运行命令均在 `mewcode-python` 目录执行。

### 2. 配置模型

在 `mewcode-python` 目录创建 `.mewcode/config.yaml`：

```powershell
New-Item -ItemType Directory -Force .mewcode | Out-Null
notepad .mewcode\config.yaml
```

以 **DeepSeek 官方 deepseek-v4-pro** 为例，填写：

```yaml
providers:
  - name: deepseek-official
    protocol: anthropic
    base_url: https://api.deepseek.com/anthropic
    api_key: "填入你的 DeepSeek 官方 API Key"
    model: deepseek-v4-pro
    thinking: true

permission_mode: default
enable_coordinator_mode: false
```

DeepSeek 提供 Anthropic 兼容接口，上述地址、模型和思考模式配置依据其[官方文档](https://api-docs.deepseek.com/guides/anthropic_api/)。API 使用产生的费用由模型服务商收取。

请将密钥保留在本地。项目内的 `.mewcode/` 目录已被 Git 忽略。若将 `api_key` 留空，`anthropic` 协议会读取 `ANTHROPIC_API_KEY`，`openai` 和 `openai-compat` 协议会读取 `OPENAI_API_KEY`。

配置文件依次加载并合并：

1. 用户目录下的 `~/.mewcode/config.yaml`。
2. 当前工作目录下的 `.mewcode/config.yaml`。
3. 当前工作目录下的 `.mewcode/config.local.yaml`。

后加载的配置按项目合并规则覆盖前面的配置；至少需要一个配置文件。修改配置后，请重启程序。

### 3. 启动浏览器界面

```powershell
.\.venv\Scripts\python.exe -m mewcode --remote
```

打开终端打印的完整网址，例如：

```text
http://localhost:18888/?token=启动时生成的token
```

Remote 默认仅监听本机 `127.0.0.1:18888`。每次启动都会生成新的访问 token，重启后请使用新网址。终端按 `Ctrl+C` 停止服务。

## 其他运行方式

### 终端交互

```powershell
.\.venv\Scripts\python.exe -m mewcode
```

### 单次执行

```powershell
.\.venv\Scripts\python.exe -m mewcode -p "介绍一下这个项目的目录结构"
```

需要 NDJSON 事件流时：

```powershell
.\.venv\Scripts\python.exe -m mewcode -p "解释 mewcode/agent.py" --output-format stream-json
```

### 查看启动参数

```powershell
.\.venv\Scripts\python.exe -m mewcode --help
```

macOS / Linux 使用 `.venv/bin/python` 替换以上的 `.\.venv\Scripts\python.exe`，并使用 `cd code-python/mewcode-python` 进入项目目录。

## 可选 MCP 配置

需要 Context7 时，在配置文件中加入以下内容，并确保已安装 Node.js 和 npm：

```yaml
mcp_servers:
  - name: context7
    command: npx
    args: ["-y", "@upstash/context7-mcp"]
```

不使用 MCP 时，可以省略 `mcp_servers`。

## 常见问题

### 找不到 `.venv\Scripts\python.exe`

确认已经进入仓库中的 `mewcode-python` 子目录，并创建了虚拟环境。激活虚拟环境不会自动切换工作目录。

### `uv trampoline failed to canonicalize script path`

若 `mewcode.exe` 启动器报路径错误，可直接使用本文的模块入口：

```powershell
.\.venv\Scripts\python.exe -m mewcode --remote
```

### `401` / `invalid x-api-key`

检查 API Key 是否有效，以及 `protocol`、`base_url`、`model` 是否属于同一服务商。使用 DeepSeek 官方接口时，需要 DeepSeek 官方 API Key。

### `Network error: Connection error`

检查网络、代理和日志。若系统代理导致 DeepSeek 的 TLS 连接失败，而直连正常，可在当前 PowerShell 中设置绕过代理，再启动服务：

```powershell
$env:NO_PROXY = "api.deepseek.com,localhost,127.0.0.1"
.\.venv\Scripts\python.exe -m mewcode --remote
```

该设置只影响当前 PowerShell 及其启动的进程。仅在网络允许直连时使用。

### 为什么只输入“你好”，`In` 也有几千 Token？

输入还包括系统提示词、工具定义和会话上下文。`In` 表示输入 Token，`Out` 表示输出 Token，均不等同于汉字数量。

## 开发与测试

在 `mewcode-python` 目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio
.\.venv\Scripts\python.exe -m pytest
```

运行日志位于当前工作目录的 `.mewcode/debug.log`。

## 目录结构

```text
code-python/
├── README.md                 # 仓库使用说明
└── mewcode-python/
    ├── pyproject.toml        # 项目依赖与命令行入口
    ├── uv.lock               # uv 依赖锁定文件
    ├── mewcode/              # 应用源码
    │   ├── __main__.py       # 启动入口
    │   ├── app.py            # 终端界面
    │   ├── remote.py         # 本地浏览器服务
    │   ├── client.py         # 模型 API 客户端
    │   ├── tools/            # 工具实现
    │   ├── agents/           # 子代理
    │   ├── teams/            # 团队协作
    │   └── mcp/              # MCP 集成
    ├── tests/                # 测试
    └── docs/                 # 其他文档
```
