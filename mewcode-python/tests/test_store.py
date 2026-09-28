"""CostStore 跨会话持久化的最小闭环单测。"""
from __future__ import annotations

import os
import time

import pytest

from mewcode.cost.record import CostRecord
from mewcode.cost.store import CostStore


def _record(
    model: str = "claude-3-5-sonnet",
    inp: int = 1000,
    out: int = 500,
    ts: float = 1000.0,
    agent_id: str = "main",
    tool_name: str | None = None,
) -> CostRecord:
    return CostRecord(
        timestamp=ts,
        model=model,
        input_tokens=inp,
        output_tokens=out,
        cache_read=0,
        cache_creation=0,
        ttft_ms=0.0,
        duration_ms=1000.0,
        agent_id=agent_id,
        tool_name=tool_name,
    )


def test_append_then_load_round_trip(tmp_path):
    """append 写入的记录应能被 load_session 完整读回。"""
    store = CostStore(str(tmp_path))
    r1 = _record(inp=1000, out=500, ts=1000.0)
    r2 = _record(model="gpt-4o", inp=2000, out=100, ts=2000.0)

    store.append(r1, "sess-1")
    store.append(r2, "sess-1")

    loaded = store.load_session("sess-1")
    assert len(loaded) == 2
    assert loaded[0].model == "claude-3-5-sonnet"
    assert loaded[0].input_tokens == 1000
    assert loaded[1].model == "gpt-4o"
    assert loaded[1].timestamp == 2000.0


def test_append_empty_session_id_skips(tmp_path):
    """session_id 为空时不落盘，避免产生 .jsonl 孤儿文件。"""
    store = CostStore(str(tmp_path))
    store.append(_record(), "")
    # 目录下不应有任何 jsonl 文件
    assert not list((tmp_path / ".mewcode" / "cost").glob("*.jsonl"))


def test_load_nonexistent_session_returns_empty(tmp_path):
    """读取不存在的会话返回空列表，不抛异常。"""
    store = CostStore(str(tmp_path))
    assert store.load_session("nope") == []


def test_sessions_isolated_per_session_id(tmp_path):
    """不同 session_id 的记录隔离到不同文件。"""
    store = CostStore(str(tmp_path))
    store.append(_record(inp=100), "sess-a")
    store.append(_record(inp=200), "sess-b")
    store.append(_record(inp=300), "sess-a")

    a = store.load_session("sess-a")
    b = store.load_session("sess-b")
    assert len(a) == 2
    assert len(b) == 1
    assert a[0].input_tokens == 100
    assert a[1].input_tokens == 300
    assert b[0].input_tokens == 200


def test_list_sessions_returns_metas_sorted_by_mtime(tmp_path):
    """list_sessions 返回每个会话的元数据，按 mtime 降序。"""
    store = CostStore(str(tmp_path))
    store.append(_record(inp=100, ts=1000.0), "old-session")
    # 触发 mtime 差异：等待文件系统时间精度
    time.sleep(0.01)
    store.append(_record(inp=200, ts=2000.0), "new-session")

    metas = store.list_sessions()
    assert len(metas) == 2
    # 新会话 mtime 更大，应排第一
    assert metas[0].session_id == "new-session"
    assert metas[0].record_count == 1
    assert metas[1].session_id == "old-session"
    assert metas[1].record_count == 1


def test_list_sessions_computes_total_cost(tmp_path):
    """list_sessions 的 total_cost 应按价格表聚合。"""
    store = CostStore(str(tmp_path))
    store.append(_record(inp=1000, out=500), "sess-1")  # claude-3-5-sonnet

    metas = store.list_sessions()
    assert len(metas) == 1
    # (1000×3.0 + 500×15.0) / 1M = 0.0105
    assert metas[0].total_cost == pytest.approx(0.0105)


def test_list_sessions_unknown_model_makes_total_cost_none(tmp_path):
    """会话含未知价格模型时 total_cost 为 None。"""
    store = CostStore(str(tmp_path))
    store.append(_record(model="gpt-5", inp=100), "sess-x")  # gpt-5 不在表里

    metas = store.list_sessions()
    assert len(metas) == 1
    assert metas[0].total_cost is None


def test_list_sessions_empty_dir_returns_empty(tmp_path):
    """空目录（无任何会话）返回空列表。"""
    store = CostStore(str(tmp_path))
    assert store.list_sessions() == []


def test_load_session_skips_bad_lines(tmp_path):
    """坏行（非法 JSON / 字段缺失）跳过，不阻断整文件读取。"""
    store = CostStore(str(tmp_path))
    # 正常写入两条
    store.append(_record(inp=100), "bad-sess")
    store.append(_record(inp=200), "bad-sess")
    # 手工追加坏行
    path = tmp_path / ".mewcode" / "cost" / "bad-sess.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write("this is not json\n")
        f.write('{"model": "incomplete"}\n')  # 缺字段，用默认值容错
    store.append(_record(inp=300), "bad-sess")  # 坏行后仍能追加

    loaded = store.load_session("bad-sess")
    # 2 原始 + 1 容错(缺字段用默认) + 1 末尾 = 4，坏 json 行被跳过
    assert len(loaded) == 4
    # 第三条是缺字段的容错记录
    assert loaded[2].model == "incomplete"
    assert loaded[2].input_tokens == 0  # 缺字段默认值


def test_store_creates_cost_dir(tmp_path):
    """构造 CostStore 应自动创建 .mewcode/cost 目录。"""
    work = tmp_path / "workspace"
    assert not work.exists()
    store = CostStore(str(work))
    assert (work / ".mewcode" / "cost").is_dir()
    # 空目录也应能正常列出
    assert store.list_sessions() == []


def test_list_sessions_first_and_last_ts(tmp_path):
    """first_ts / last_ts 应反映会话内最早 / 最晚记录时间戳。"""
    store = CostStore(str(tmp_path))
    store.append(_record(ts=5000.0), "s1")
    store.append(_record(ts=1000.0), "s1")
    store.append(_record(ts=3000.0), "s1")

    metas = store.list_sessions()
    assert len(metas) == 1
    assert metas[0].first_ts == 1000.0
    assert metas[0].last_ts == 5000.0
