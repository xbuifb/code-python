from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType
from mewcode.cost.pricing import reload_pricing
from mewcode.cost.report import render_text


async def handle_cost(ctx: CommandContext) -> None:
    # 通过 ctx.agent.cost_ledger 间接访问，避免扩展 CommandContext。
    ledger = getattr(ctx.agent, "cost_ledger", None) if ctx.agent else None
    if ledger is None:
        ctx.ui.add_system_message("成本账本未启用（agent 未注入 cost_ledger）")
        return

    # 子命令：/cost（默认 total）、/cost by-tool、/cost by-model、/cost by-agent、/cost reload
    arg = (ctx.args or "").strip()
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

    mode_map = {
        "": "total",
        "total": "total",
        "by-tool": "by-tool",
        "by-tool": "by-tool",
        "by-model": "by-model",
        "by-agent": "by-agent",
    }
    mode = mode_map.get(arg)
    if mode is None:
        ctx.ui.add_system_message(
            f"未知子命令: {arg}\n"
            "可用: /cost, /cost by-tool, /cost by-model, /cost by-agent, /cost reload"
        )
        return

    try:
        ctx.ui.add_system_message(render_text(ledger, mode=mode))
    except (AttributeError, ValueError) as e:
        ctx.ui.add_system_message(f"渲染失败: {e}")


COST_COMMAND = Command(
    name="cost",
    aliases=["c"],
    description="显示本次会话累计成本与延迟，支持 by-tool / by-model / by-agent 分桶与 reload",
    usage="/cost [by-tool | by-model | by-agent | reload]",
    type=CommandType.LOCAL,
    handler=handle_cost,
)
