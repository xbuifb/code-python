"""Slash Command 框架测试——registry、parser、补全、handler。"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mewcode.commands.parser import complete, parse_command
from mewcode.commands.registry import (
    Command,
    CommandContext,
    CommandRegistry,
    CommandType,
    UIController,
)

# ---------------------------------------------------------------------------
# 测试夹具（Fixtures）
# ---------------------------------------------------------------------------

def _make_command(
    name: str,
    aliases: list[str] | None = None,
    hidden: bool = False,
    handler: Any = None,
    arg_prompt: str = "",
) -> Command:
    return Command(
        name=name,
        aliases=aliases or [],
        description=f"Test {name}",
        type=CommandType.LOCAL,
        handler=handler or AsyncMock(),
        hidden=hidden,
        arg_prompt=arg_prompt,
    )

class MockUI:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.sent_messages: list[str] = []
        self._plan_mode = False

    def add_system_message(self, text: str) -> None:
        self.messages.append(text)

    def send_user_message(self, text: str) -> None:
        self.sent_messages.append(text)

    def set_plan_mode(self, enabled: bool) -> None:
        self._plan_mode = enabled

    def get_token_count(self) -> tuple[int, int]:
        return 10000, 5000

    def refresh_status(self) -> None:
        pass

def _make_context(args: str = "", ui: MockUI | None = None) -> CommandContext:
    return CommandContext(
        args=args,
        agent=None,
        conversation=None,
        session=None,
        session_manager=None,
        memory_manager=None,
        ui=ui or MockUI(),
        config={},
    )

# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------

class TestParseCommand:
    def test_normal_command(self) -> None:
        name, args, is_cmd = parse_command("/help")
        assert is_cmd is True
        assert name == "help"
        assert args == ""

    def test_command_with_args(self) -> None:
        name, args, is_cmd = parse_command("/compact 保留数据库相关内容")
        assert is_cmd is True
        assert name == "compact"
        assert args == "保留数据库相关内容"

    def test_command_case_insensitive(self) -> None:
        name, args, is_cmd = parse_command("/HELP")
        assert name == "help"
        assert is_cmd is True

    def test_only_slash(self) -> None:
        name, args, is_cmd = parse_command("/")
        assert is_cmd is True
        assert name == ""
        assert args == ""

    def test_not_a_command(self) -> None:
        name, args, is_cmd = parse_command("hello world")
        assert is_cmd is False
        assert name == ""
        assert args == ""

    def test_empty_input(self) -> None:
        name, args, is_cmd = parse_command("")
        assert is_cmd is False

    def test_whitespace_input(self) -> None:
        name, args, is_cmd = parse_command("   ")
        assert is_cmd is False

    def test_command_with_leading_spaces(self) -> None:
        name, args, is_cmd = parse_command("  /help  ")
        assert is_cmd is True
        assert name == "help"

    def test_command_with_multiple_args(self) -> None:
        name, args, is_cmd = parse_command("/session resume abc123")
        assert name == "session"
        assert args == "resume abc123"

# ---------------------------------------------------------------------------
# CommandRegistry
# ---------------------------------------------------------------------------

class TestCommandRegistry:
    def test_register_and_find(self) -> None:
        registry = CommandRegistry()
        cmd = _make_command("help", aliases=["h", "?"])
        registry.register_sync(cmd)
        assert registry.find("help") is cmd

    def test_find_by_alias(self) -> None:
        registry = CommandRegistry()
        cmd = _make_command("help", aliases=["h", "?"])
        registry.register_sync(cmd)
        assert registry.find("h") is cmd
        assert registry.find("?") is cmd

    def test_find_unknown(self) -> None:
        registry = CommandRegistry()
        assert registry.find("nonexistent") is None

    def test_list_commands_excludes_hidden(self) -> None:
        registry = CommandRegistry()
        registry.register_sync(_make_command("visible"))
        registry.register_sync(_make_command("secret", hidden=True))
        cmds = registry.list_commands()
        assert len(cmds) == 1
        assert cmds[0].name == "visible"

    def test_alias_conflict_raises(self) -> None:
        registry = CommandRegistry()
        registry.register_sync(_make_command("help", aliases=["h"]))
        with pytest.raises(ValueError, match="conflicts"):
            registry.register_sync(_make_command("hints", aliases=["h"]))

    def test_name_conflict_raises(self) -> None:
        registry = CommandRegistry()
        registry.register_sync(_make_command("help"))
        with pytest.raises(ValueError, match="conflicts"):
            registry.register_sync(_make_command("help"))

    def test_name_alias_cross_conflict(self) -> None:
        registry = CommandRegistry()
        registry.register_sync(_make_command("help", aliases=["h"]))
        with pytest.raises(ValueError, match="conflicts"):
            registry.register_sync(_make_command("h"))

    @pytest.mark.asyncio
    async def test_async_register(self) -> None:
        registry = CommandRegistry()
        cmd = _make_command("test")
        await registry.register(cmd)
        assert registry.find("test") is cmd

    @pytest.mark.asyncio
    async def test_async_register_conflict(self) -> None:
        registry = CommandRegistry()
        await registry.register(_make_command("test"))
        with pytest.raises(ValueError, match="conflicts"):
            await registry.register(_make_command("test"))

# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------

class TestComplete:
    def _build_registry(self) -> CommandRegistry:
        registry = CommandRegistry()
        registry.register_sync(_make_command("help", aliases=["h", "?"]))
        registry.register_sync(_make_command("compact", aliases=["c"]))
        registry.register_sync(_make_command("session"))
        registry.register_sync(_make_command("status", aliases=["s"]))
        registry.register_sync(_make_command("secret", hidden=True))
        return registry

    @staticmethod
    def _values(matches: list[tuple[str, str]]) -> list[str]:
        return [v for _, v in matches]

    def test_empty_prefix(self) -> None:
        registry = self._build_registry()
        matches = complete(registry, "/")
        values = self._values(matches)
        assert "/help" in values
        assert "/compact" in values
        assert "/secret" not in values

    def test_prefix_match(self) -> None:
        registry = self._build_registry()
        matches = complete(registry, "/com")
        assert self._values(matches) == ["/compact"]

    def test_multiple_matches(self) -> None:
        registry = self._build_registry()
        matches = complete(registry, "/s")
        values = self._values(matches)
        assert "/session" in values
        assert "/status" in values

    def test_alias_match(self) -> None:
        registry = self._build_registry()
        matches = complete(registry, "/h")
        values = self._values(matches)
        assert "/help" in values

    def test_no_match(self) -> None:
        registry = self._build_registry()
        matches = complete(registry, "/xyz")
        assert matches == []

    def test_hidden_excluded(self) -> None:
        registry = self._build_registry()
        matches = complete(registry, "/sec")
        assert matches == []

# ---------------------------------------------------------------------------
# Handler 测试
# ---------------------------------------------------------------------------

class TestHelpHandler:
    @pytest.mark.asyncio
    async def test_list_all(self) -> None:
        from mewcode.commands.handlers import register_all_commands
        from mewcode.commands.handlers.help import handle_help

        registry = CommandRegistry()
        register_all_commands(registry)
        ui = MockUI()
        ctx = _make_context(args="", ui=ui)
        ctx.config = {"registry": registry}
        await handle_help(ctx)
        assert len(ui.messages) == 1
        assert "可用命令" in ui.messages[0]
        assert "/help" in ui.messages[0]
        assert "/compact" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_help_specific_command(self) -> None:
        from mewcode.commands.handlers import register_all_commands
        from mewcode.commands.handlers.help import handle_help

        registry = CommandRegistry()
        register_all_commands(registry)
        ui = MockUI()
        ctx = _make_context(args="compact", ui=ui)
        ctx.config = {"registry": registry}
        await handle_help(ctx)
        assert len(ui.messages) == 1
        assert "compact" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_help_unknown_command(self) -> None:
        from mewcode.commands.handlers import register_all_commands
        from mewcode.commands.handlers.help import handle_help

        registry = CommandRegistry()
        register_all_commands(registry)
        ui = MockUI()
        ctx = _make_context(args="nonexistent", ui=ui)
        ctx.config = {"registry": registry}
        await handle_help(ctx)
        assert "未知命令" in ui.messages[0]

class TestPlanDoHandlers:

    @pytest.mark.asyncio
    async def test_plan_switches_mode(self) -> None:
        from mewcode.commands.handlers.plan import handle_plan

        ui = MockUI()
        ctx = _make_context(args="", ui=ui)
        await handle_plan(ctx)
        assert ui._plan_mode is True
        assert "Plan 模式" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_plan_with_args_sends_message(self) -> None:
        from mewcode.commands.handlers.plan import handle_plan

        ui = MockUI()
        ctx = _make_context(args="设计登录模块", ui=ui)
        await handle_plan(ctx)
        assert ui._plan_mode is True
        assert "设计登录模块" in ui.sent_messages

class TestSkillHandler:
    @pytest.mark.asyncio
    async def test_skill_list_no_loader(self) -> None:
        from mewcode.commands.handlers.skill import handle_skill

        ui = MockUI()
        ctx = _make_context(args="list", ui=ui)
        await handle_skill(ctx)
        assert "未初始化" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_skill_list_with_loader(self) -> None:
        from mewcode.commands.handlers.skill import handle_skill

        ui = MockUI()
        ctx = _make_context(args="list", ui=ui)
        loader = MagicMock()
        loader.get_catalog.return_value = [("commit", "分析 git diff")]
        loader.get_source_label.return_value = "builtin"
        ctx.config = {"skill_loader": loader}
        await handle_skill(ctx)
        assert "commit" in ui.messages[0]
        assert "builtin" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_skill_unknown_subcmd(self) -> None:
        from mewcode.commands.handlers.skill import handle_skill

        ui = MockUI()
        ctx = _make_context(args="foobar", ui=ui)
        loader = MagicMock()
        ctx.config = {"skill_loader": loader}
        await handle_skill(ctx)
        assert "未知子命令" in ui.messages[0]

class TestStatusHandler:

    @pytest.mark.asyncio
    async def test_status_output(self) -> None:
        from mewcode.commands.handlers.status import handle_status

        ui = MockUI()
        agent = MagicMock()
        agent.permission_mode = MagicMock()
        agent.permission_mode.value = "default"
        agent.context_window = 200_000
        agent.registry = MagicMock()
        agent.registry.list_tools.return_value = []
        agent.registry.is_enabled.return_value = True
        agent.work_dir = "/test"

        ctx = _make_context(args="", ui=ui)
        ctx.agent = agent
        ctx.memory_manager = MagicMock()
        ctx.memory_manager.load.return_value = ""

        await handle_status(ctx)
        assert "MewCode 状态" in ui.messages[0]
        assert "default" in ui.messages[0]

class TestSessionHandler:
    @pytest.mark.asyncio
    async def test_session_no_manager(self) -> None:
        from mewcode.commands.handlers.session import handle_session

        ui = MockUI()
        ctx = _make_context(args="", ui=ui)
        ctx.session_manager = None
        await handle_session(ctx)
        assert "未初始化" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_session_list_empty(self) -> None:
        from mewcode.commands.handlers.session import handle_session

        ui = MockUI()
        sm = MagicMock()
        sm.list.return_value = []
        ctx = _make_context(args="list", ui=ui)
        ctx.session_manager = sm
        await handle_session(ctx)
        assert "没有已保存的会话" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_session_unknown_sub(self) -> None:
        from mewcode.commands.handlers.session import handle_session

        ui = MockUI()
        ctx = _make_context(args="foobar", ui=ui)
        ctx.session_manager = MagicMock()
        await handle_session(ctx)
        assert "用法" in ui.messages[0]

class TestMemoryHandler:
    @pytest.mark.asyncio
    async def test_memory_display(self) -> None:
        from mewcode.commands.handlers.memory import handle_memory

        ui = MockUI()
        mm = MagicMock()
        mm.get_display_text.return_value = "记忆内容"
        ctx = _make_context(args="", ui=ui)
        ctx.memory_manager = mm
        await handle_memory(ctx)
        assert "记忆内容" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_memory_clear(self) -> None:
        from mewcode.commands.handlers.memory import handle_memory

        ui = MockUI()
        mm = MagicMock()
        ctx = _make_context(args="clear", ui=ui)
        ctx.memory_manager = mm
        await handle_memory(ctx)
        mm.clear.assert_called_once()
        assert "清空" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_memory_no_manager(self) -> None:
        from mewcode.commands.handlers.memory import handle_memory

        ui = MockUI()
        ctx = _make_context(args="", ui=ui)
        ctx.memory_manager = None
        await handle_memory(ctx)
        assert "未初始化" in ui.messages[0]

# ---------------------------------------------------------------------------
# /cost 命令 handler 测试
# ---------------------------------------------------------------------------

class TestCostHandler:
    """覆盖 /cost 命令的 7 个分支：total / by-tool / json / reload /
    history(无 store) / 未知子命令 / ledger 未注入。

    这些是用户入口的唯一证据——之前 tests/ 里 0 个 handle_cost 测试，
    7 个分支全未验证。
    """

    @staticmethod
    def _make_ledger():
        from mewcode.cost.ledger import CostLedger
        from mewcode.cost.record import CostRecord
        l = CostLedger()
        l.append(CostRecord(
            timestamp=1.0, model="claude-3-5-sonnet",
            input_tokens=1000, output_tokens=500,
            cache_read=100, cache_creation=200,
            ttft_ms=42.0, duration_ms=500.0,
            agent_id="main", tool_name="bash",
        ))
        l.append(CostRecord(
            timestamp=2.0, model="gpt-4o",
            input_tokens=2000, output_tokens=1000,
            cache_read=0, cache_creation=0,
            ttft_ms=88.0, duration_ms=800.0,
            agent_id="worker-1", tool_name="grep",
        ))
        return l

    @pytest.mark.asyncio
    async def test_cost_total_default(self) -> None:
        from mewcode.commands.handlers.cost import handle_cost
        ui = MockUI()
        ctx = _make_context(args="", ui=ui)
        ctx.cost_ledger = self._make_ledger()
        await handle_cost(ctx)
        assert len(ui.messages) == 1
        assert "成本与延迟（总览）" in ui.messages[0]
        assert "记录数: 2" in ui.messages[0]
        # 两个模型都已知价，应显示 $ 金额而非"未知"
        assert "$" in ui.messages[0]
        assert "未知" not in ui.messages[0]

    @pytest.mark.asyncio
    async def test_cost_by_tool(self) -> None:
        from mewcode.commands.handlers.cost import handle_cost
        ui = MockUI()
        ctx = _make_context(args="by-tool", ui=ui)
        ctx.cost_ledger = self._make_ledger()
        await handle_cost(ctx)
        assert "成本分桶（按 工具）" in ui.messages[0]
        # 两个 tool_name 都应出现
        assert "bash" in ui.messages[0]
        assert "grep" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_cost_json(self) -> None:
        import json as _json
        from mewcode.commands.handlers.cost import handle_cost
        ui = MockUI()
        ctx = _make_context(args="json", ui=ui)
        ctx.cost_ledger = self._make_ledger()
        await handle_cost(ctx)
        payload = _json.loads(ui.messages[0])
        assert set(payload.keys()) == {
            "total", "by_tool", "by_model", "by_agent", "records"
        }
        assert payload["total"]["record_count"] == 2
        assert len(payload["records"]) == 2

    @pytest.mark.asyncio
    async def test_cost_reload(self) -> None:
        from mewcode.commands.handlers.cost import handle_cost
        ui = MockUI()
        ctx = _make_context(args="reload", ui=ui)
        ctx.cost_ledger = self._make_ledger()
        await handle_cost(ctx)
        assert "价格表已重载" in ui.messages[0]
        assert "条模型记录" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_cost_history_no_store_shows_hint(self) -> None:
        """store=None（纯内存 ledger）时 /cost history 应给出明确提示，不静默空。"""
        from mewcode.commands.handlers.cost import handle_cost
        ui = MockUI()
        ctx = _make_context(args="history", ui=ui)
        # _make_ledger 返回的 CostLedger() 无 store 注入
        ctx.cost_ledger = self._make_ledger()
        await handle_cost(ctx)
        assert "成本持久化未启用" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_cost_unknown_subcommand(self) -> None:
        from mewcode.commands.handlers.cost import handle_cost
        ui = MockUI()
        ctx = _make_context(args="foobar", ui=ui)
        ctx.cost_ledger = self._make_ledger()
        await handle_cost(ctx)
        assert "未知子命令" in ui.messages[0]
        # 提示里应列出可用子命令
        assert "by-tool" in ui.messages[0]
        assert "history" in ui.messages[0]

    @pytest.mark.asyncio
    async def test_cost_no_ledger_shows_hint(self) -> None:
        """ledger 未注入（ctx.agent 也无）应提示而非 AttributeError。"""
        from mewcode.commands.handlers.cost import handle_cost
        ui = MockUI()
        ctx = _make_context(args="", ui=ui)
        # ctx.cost_ledger 默认 None，ctx.agent 也默认 None
        await handle_cost(ctx)
        assert "成本账本未启用" in ui.messages[0]


# ---------------------------------------------------------------------------
# 集成测试：register_all_commands
# ---------------------------------------------------------------------------

class TestRegisterAllCommands:
    def test_all_commands_registered(self) -> None:
        from mewcode.commands.handlers import register_all_commands

        registry = CommandRegistry()
        register_all_commands(registry)
        cmds = registry.list_commands()
        names = {c.name for c in cmds}
        expected = {
            "help", "compact", "clear", "cost", "plan",
            "session", "mcp", "memory", "permission",
            "sandbox", "rewind", "status", "skill",
        }
        assert names == expected

    def test_no_alias_conflicts(self) -> None:
        from mewcode.commands.handlers import register_all_commands

        registry = CommandRegistry()
        register_all_commands(registry)

    def test_aliases_work(self) -> None:
        from mewcode.commands.handlers import register_all_commands

        registry = CommandRegistry()
        register_all_commands(registry)
        assert registry.find("h") is not None
        assert registry.find("h").name == "help"
        assert registry.find("c").name == "compact"
        assert registry.find("p").name == "plan"
        assert registry.find("s").name == "status"
        assert registry.find("?").name == "help"
