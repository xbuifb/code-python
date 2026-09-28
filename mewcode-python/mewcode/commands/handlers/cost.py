from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType
from mewcode.cost.pricing import reload_pricing
from mewcode.cost.report import (
    render_history,
    render_json,
    render_session_detail,
    render_text,
)


async def handle_cost(ctx: CommandContext) -> None:
    # Stage 6 起 /cost 命令优先走 ctx.cost_ledger，但保留 getattr 兜底，
    # 因为 -p 模式早期入口可能还没注入 cost_ledger。
    ledger = ctx.cost_ledger
    if ledger is None:
        ledger = getattr(ctx.agent, "cost_ledger", None) if ctx.agent else None
    if ledger is None:
        ctx.ui.add_system_message("成本账本未启用（agent 未注入 cost_ledger）")
        return

    arg = (ctx.args or "").strip()

    # /cost history [session_id] — 跨会话历史查询（Stage 7）
    if arg == "history" or arg.startswith("history "):
        _handle_history(ctx, ledger, arg)
        return

    # /cost reload — 运行时重新加载 ~/.mewcode/pricing.yaml
    if arg == "reload":
        try:
            count = reload_pricing()
            ctx.ui.add_system_message(
                f"价格表已重载，共 {count} 条模型记录\n"
                f"来源：~/.mewcode/pricing.yaml（覆盖默认表同名模型）"
            )
        except Exception as e:
            ctx.ui.add_system_message(f"价格表重载失败: {e}")
        return

    # /cost json — 导出账本为 JSON（含每条原始记录，供离线分析）
    if arg == "json":
        try:
            ctx.ui.add_system_message(render_json(ledger))
        except Exception as e:
            ctx.ui.add_system_message(f"JSON 导出失败: {e}")
        return

    mode_map = {
        "": "total",
        "total": "total",
        "by-tool": "by-tool",
        "by-model": "by-model",
        "by-agent": "by-agent",
    }
    mode = mode_map.get(arg)
    if mode is None:
        ctx.ui.add_system_message(
            f"未知子命令: {arg}\n"
            "可用: /cost, /cost by-tool, /cost by-model, /cost by-agent, "
            "/cost reload, /cost json, /cost history [session_id]"
        )
        return

    try:
        ctx.ui.add_system_message(render_text(ledger, mode=mode))
    except (AttributeError, ValueError) as e:
        ctx.ui.add_system_message(f"渲染失败: {e}")


def _handle_history(ctx: CommandContext, ledger, arg: str) -> None:
    """处理 /cost history [session_id]。

    无参数：列出持久化会话汇总；有参数：渲染指定会话的明细。
    store 未启用时（ledger 无 store）给出明确提示，而不是静默返回空列表。
    """
    store = ledger.store
    if store is None:
        ctx.ui.add_system_message(
            "成本持久化未启用（agent 未绑定 CostStore）"
        )
        return

    # 解析 session_id 参数："/cost history <id>" → arg = "history <id>"
    parts = arg.split(None, 1)
    session_id = parts[1].strip() if len(parts) > 1 else ""

    if not session_id:
        # 列出所有持久化会话
        try:
            metas = store.list_sessions()
            ctx.ui.add_system_message(render_history(metas))
        except Exception as e:
            ctx.ui.add_system_message(f"历史查询失败: {e}")
        return

    # 单会话明细
    try:
        records = store.load_session(session_id)
        ctx.ui.add_system_message(render_session_detail(session_id, records))
    except Exception as e:
        ctx.ui.add_system_message(f"会话查询失败: {e}")


COST_COMMAND = Command(
    name="cost",
    aliases=[],  # /compact 已用 "c" 别名，cost 不抢
    description=(
        "显示本次会话累计成本与延迟，支持 by-tool / by-model / by-agent 分桶，"
        "reload 重载价格表，json 导出原始记录，history 查询跨会话历史"
    ),
    usage="/cost [by-tool | by-model | by-agent | reload | json | history [session_id]]",
    type=CommandType.LOCAL,
    handler=handle_cost,
)
