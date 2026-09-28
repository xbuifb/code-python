from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal

from mewcode.cost.ledger import CostLedger
from mewcode.cost.store import CostSessionMeta


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


def render_json(ledger: CostLedger) -> str:
    """把账本导出为 JSON 字符串，含 total + by-tool + by-model + by-agent + 原始记录。

    用于 /cost json 子命令，供离线分析（jupyter / 外部 BI 工具消费）。
    输出结构稳定，新增字段时通过加新 key 保持向后兼容。
    """
    total = ledger.total()
    payload = {
        "total": {
            "record_count": total.record_count,
            "total_input": total.total_input,
            "total_output": total.total_output,
            "total_cache_read": total.total_cache_read,
            "total_cache_creation": total.total_cache_creation,
            "cache_hit_rate": total.cache_hit_rate,
            "avg_ttft_ms": total.avg_ttft_ms,
            "avg_duration_ms": total.avg_duration_ms,
            "total_cost": total.total_cost,
            "unknown_models": total.unknown_models,
        },
        "by_tool": [asdict(r) for r in ledger.aggregate(by="tool")] if total.record_count else [],
        "by_model": [asdict(r) for r in ledger.aggregate(by="model")] if total.record_count else [],
        "by_agent": [asdict(r) for r in ledger.aggregate(by="agent_id")] if total.record_count else [],
        "records": [asdict(r) for r in ledger._records],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_history(metas: list[CostSessionMeta], limit: int = 20) -> str:
    """渲染 /cost history 列表：每个持久化会话一行汇总。

    metas 已按 mtime 降序排好（由 CostStore.list_sessions 保证）；
    limit 仅截断展示行数，不改变排序。空列表返回提示文案。
    """
    lines = ["成本历史（按最近使用排序）", "─────────────────────────────────────────────"]
    if not metas:
        lines.append("尚无持久化的会话成本记录")
        return "\n".join(lines)

    shown = metas[:limit]
    lines.append(f"{'会话 ID':<32} 调用数   成本          首次调用            最后调用")
    for m in shown:
        if m.total_cost is None:
            cost_str = "未知"
        elif m.record_count == 0:
            cost_str = "-"
        else:
            cost_str = f"${m.total_cost:.4f}"
        first = _fmt_ts(m.first_ts) if m.first_ts else "-"
        last = _fmt_ts(m.last_ts) if m.last_ts else "-"
        # 截断过长 session_id（保留尾部更独特的 4 位随机后缀）
        sid = m.session_id if len(m.session_id) <= 32 else "..." + m.session_id[-29:]
        lines.append(f"{sid:<32} {m.record_count:<6}   {cost_str:<12} {first}   {last}")

    if len(metas) > limit:
        lines.append(f"... 共 {len(metas)} 个会话，仅显示最近 {limit} 个")
    return "\n".join(lines)


def render_session_detail(session_id: str, records: list) -> str:
    """渲染 /cost history <session_id>：单会话明细。

    records 为 CostStore.load_session 返回的 CostRecord 列表。
    用临时 CostLedger 复用已有 total / aggregate 渲染逻辑，
    避免在 report 层重写聚合公式。
    """
    lines = [f"会话成本明细：{session_id}", "─────────────────────────────────────────────"]
    if not records:
        lines.append("该会话无成本记录（可能早于 Stage 7 持久化上线）")
        return "\n".join(lines)

    # 用临时 ledger 复用 total 渲染，避免重复实现聚合
    tmp = CostLedger()
    tmp._records = list(records)
    lines.append(_render_total(tmp))
    return "\n".join(lines)


def _fmt_ts(ts: float) -> str:
    """把 epoch 秒格式成本地可读时间，用于历史列表展示。"""
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "-"
