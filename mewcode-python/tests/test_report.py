"""Stage 6/7 — render_json / render_history 输出结构与字段测试。"""
from __future__ import annotations

import json

from mewcode.cost.ledger import CostLedger
from mewcode.cost.record import CostRecord
from mewcode.cost.report import (
    render_history,
    render_json,
    render_session_detail,
    render_text,
)
from mewcode.cost.store import CostSessionMeta


def _make_ledger() -> CostLedger:
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


def test_render_json_has_all_top_level_keys():
    """render_json 输出应含 total/by_tool/by_model/by_agent/records 5 个顶层 key。"""
    payload = json.loads(render_json(_make_ledger()))
    assert set(payload.keys()) == {"total", "by_tool", "by_model", "by_agent", "records"}


def test_render_json_total_block_contains_scalar_aggregates():
    payload = json.loads(render_json(_make_ledger()))
    total = payload["total"]
    assert total["record_count"] == 2
    assert total["total_input"] == 3000  # 1000 + 2000
    assert total["total_output"] == 1500
    assert total["total_cache_read"] == 100
    assert total["total_cache_creation"] == 200
    # cache_hit_rate = 100 / (3000 + 100 + 200) = 0.0322...
    assert total["cache_hit_rate"] > 0
    assert 0 < total["cache_hit_rate"] < 1
    # Sonnet + GPT-4o 都已知价，total_cost 应为非空 float
    assert total["total_cost"] is not None
    assert isinstance(total["total_cost"], float)
    # 都已知价，unknown_models 应为空 list
    assert total["unknown_models"] == []


def test_render_json_by_tool_groups_correctly():
    payload = json.loads(render_json(_make_ledger()))
    by_tool = payload["by_tool"]
    assert len(by_tool) == 2  # bash + grep
    keys = {row["key"] for row in by_tool}
    assert keys == {"bash", "grep"}


def test_render_json_by_model_groups_correctly():
    payload = json.loads(render_json(_make_ledger()))
    by_model = payload["by_model"]
    assert len(by_model) == 2
    keys = {row["key"] for row in by_model}
    assert keys == {"claude-3-5-sonnet", "gpt-4o"}


def test_render_json_records_section_contains_raw_records():
    payload = json.loads(render_json(_make_ledger()))
    records = payload["records"]
    assert len(records) == 2
    assert records[0]["model"] == "claude-3-5-sonnet"
    assert records[0]["tool_name"] == "bash"
    assert records[1]["agent_id"] == "worker-1"


def test_render_json_empty_ledger_returns_empty_lists_not_none():
    """空账本 JSON 输出应让 by_tool/by_model/by_agent/records 都是 []，total 字段仍存在。"""
    payload = json.loads(render_json(CostLedger()))
    assert payload["total"]["record_count"] == 0
    assert payload["by_tool"] == []
    assert payload["by_model"] == []
    assert payload["by_agent"] == []
    assert payload["records"] == []


def test_render_text_total_mode_still_works():
    """render_text 的 total 模式不能被 render_json 改动破坏。"""
    text = render_text(_make_ledger(), mode="total")
    assert "成本与延迟（总览）" in text
    assert "记录数: 2" in text


# ---------------------------------------------------------------------------
# Stage 7 — render_history / render_session_detail
# ---------------------------------------------------------------------------


def _make_meta(
    session_id: str = "sess-1",
    record_count: int = 5,
    total_cost: float | None = 0.01,
    first_ts: float = 1000.0,
    last_ts: float = 2000.0,
    mtime: float = 2000.0,
) -> CostSessionMeta:
    return CostSessionMeta(
        session_id=session_id,
        record_count=record_count,
        total_cost=total_cost,
        first_ts=first_ts,
        last_ts=last_ts,
        mtime=mtime,
    )


def test_render_history_empty_list_shows_hint():
    """空列表返回提示文案，不抛异常。"""
    text = render_history([])
    assert "尚无持久化的会话成本记录" in text


def test_render_history_lists_sessions_with_cost():
    """每个会话一行，含 session_id / 调用数 / 成本。"""
    metas = [
        _make_meta(session_id="session_a", record_count=3, total_cost=0.0123),
        _make_meta(session_id="session_b", record_count=1, total_cost=None),
    ]
    text = render_history(metas)
    assert "成本历史" in text
    assert "session_a" in text
    assert "session_b" in text
    assert "$0.0123" in text
    assert "未知" in text  # total_cost=None 的会话显示"未知"


def test_render_history_truncates_to_limit():
    """超过 limit 的会话只显示前 limit 个，并提示总数。"""
    metas = [_make_meta(session_id=f"s{i}") for i in range(5)]
    text = render_history(metas, limit=3)
    assert "s0" in text
    assert "s2" in text
    assert "s3" not in text  # 第 4 个被截断
    assert "共 5 个会话" in text


def test_render_session_detail_empty_records_shows_hint():
    """空记录列表返回提示文案。"""
    text = render_session_detail("no-data-sess", [])
    assert "无成本记录" in text


def test_render_session_detail_shows_aggregate():
    """单会话明细应复用 total 渲染，含记录数与成本。"""
    records = [
        CostRecord(
            timestamp=1.0, model="claude-3-5-sonnet",
            input_tokens=1000, output_tokens=500,
            cache_read=0, cache_creation=0,
            ttft_ms=42.0, duration_ms=500.0,
        ),
    ]
    text = render_session_detail("sess-1", records)
    assert "会话成本明细" in text
    assert "记录数: 1" in text
