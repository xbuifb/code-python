from __future__ import annotations

from mewcode.commands.registry import Command, CommandContext, CommandType
from mewcode.cost.report import render_text


async def handle_cost(ctx: CommandContext) -> None:
    # 通过 ctx.agent.cost_ledger 间接访问，避免扩展 CommandContext。
    ledger = getattr(ctx.agent, "cost_ledger", None) if ctx.agent else None
    if ledger is None:
        ctx.ui.add_system_message("成本账本未启用（agent 未注入 cost_ledger）")
        return
    ctx.ui.add_system_message(render_text(ledger))


COST_COMMAND = Command(
    name="cost",
    aliases=["c"],
    description="显示本次会话累计成本与延迟",
    usage="/cost",
    type=CommandType.LOCAL,
    handler=handle_cost,
)
