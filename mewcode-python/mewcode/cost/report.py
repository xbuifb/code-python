from __future__ import annotations

from typing import Literal

from mewcode.cost.ledger import CostLedger


def render_text(
    ledger: CostLedger,
    mode: Literal["total", "by-tool", "by-model", "by-agent"] = "total",
) -> str:
    """把账本渲染成 /cost 命令的文本输出。

    mode:
      - "total"    : 标量总览（默认）
      - "by-tool"  : 按工具分桶
      - "by-model" : 按模型分桶
      - "by-agent" : 按 agent_id 分桶
    """
    if mode == "total":
        return _render_total(ledger)
    if mode in ("by-tool", "by-model", "by-agent"):
        return _render_aggregate(ledger, mode)
    raise ValueError(f"unsupported mode: {mode}")


def _render_total(ledger: CostLedger) -> str:
    t = ledger.total()
    lines = ["成本与延迟（总览）", "─────────────"]

    if t.record_count == 0:
        lines.append("尚无 LLM 调用记录")
        return "\n".join(lines)

    lines.append(f"记录数: {t.record_count}")

    if t.total_cost is None:
        lines.append("总成本: 价格未知（含未在价格表的模型）")
    else:
        lines.append(f"总成本: ${t.total_cost:.4f}")

    lines.append(
        f"Token: 输入 {t.total_input:,} · 输出 {t.total_output:,} · "
        f"缓存读 {t.total_cache_read:,} · 缓存写 {t.total_cache_creation:,}"
    )
    lines.append(f"缓存命中率: {t.cache_hit_rate * 100:.1f}%")
    lines.append(f"平均首 token 延迟: {t.avg_ttft_ms:.0f} ms")
    lines.append(f"平均总耗时: {t.avg_duration_ms:.0f} ms")
    if t.unknown_models:
        lines.append(f"未知价格模型: {', '.join(t.unknown_models)}")
    return "\n".join(lines)


def _render_aggregate(ledger: CostLedger, mode: str) -> str:
    """按维度分桶渲染表格。"""
    key_label = {
        "by-tool": "工具",
        "by-model": "模型",
        "by-agent": "Agent",
    }[mode]

    rows = ledger.aggregate(by=mode.split("-", 1)[1])
    title = f"成本分桶（按 {key_label}）"
    lines = [title, "─────────────────────────────────────────────"]

    if not rows:
        lines.append("尚无 LLM 调用记录")
        return "\n".join(lines)

    # 表头：key | 调用次数 | Token | 成本 | 平均 TTFT | 平均 duration
    lines.append(f"{key_label:<20} 调用数   Token      成本          平均TTFT  平均耗时")
    for row in rows:
        if row.total_cost is None:
            cost_str = "未知"
        else:
            cost_str = f"${row.total_cost:.4f}"
        # 截断过长 key
        key_display = row.key if len(row.key) <= 20 else row.key[:17] + "..."
        lines.append(
            f"{key_display:<20} {row.record_count:<6}   "
            f"{row.total_tokens:<8,}   "
            f"{cost_str:<12} "
            f"{row.avg_ttft_ms:>6.0f}ms  "
            f"{row.avg_duration_ms:>6.0f}ms"
        )
    return "\n".join(lines)
