from __future__ import annotations

from mewcode.cost.ledger import CostLedger, LedgerTotal


def render_text(ledger: CostLedger) -> str:
    """把账本渲染成 /cost 命令的文本输出。

    最小闭环只支持 total 模式（默认），无子模式参数。
    """
    t = ledger.total()
    lines = ["成本与延迟", "─────────────"]

    if t.record_count == 0:
        lines.append("尚无 LLM 调用记录")
        return "\n".join(lines)

    lines.append(f"记录数: {t.record_count}")

    # 成本展示：None 表示存在模型价格未知
    if t.total_cost is None:
        lines.append("总成本: 价格未知（含未在价格表的模型）")
    else:
        lines.append(f"总成本: ${t.total_cost:.4f}")

    lines.append(
        f"Token: 输入 {t.total_input:,} · 输出 {t.total_output:,} · "
        f"缓存读 {t.total_cache_read:,} · 缓存写 {t.total_cache_creation:,}"
    )
    lines.append(f"缓存命中率: {t.cache_hit_rate * 100:.1f}%")
    # TTFT 暂未在 agent.py 主路径测量，等后续接上 first_chunk_perf 后再展示。
    lines.append(f"平均耗时: {t.avg_duration_ms:.0f} ms")
    if t.unknown_models:
        lines.append(f"未知价格模型: {', '.join(t.unknown_models)}")
    return "\n".join(lines)
