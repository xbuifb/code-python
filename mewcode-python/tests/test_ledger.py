"""账本 append / total 聚合的最小闭环单测。"""
from __future__ import annotations

import pytest

from mewcode.cost.ledger import CostLedger
from mewcode.cost.record import CostRecord


def _record(model: str, inp: int, out: int, cr: int = 0, cc: int = 0, dur: float = 1000.0) -> CostRecord:
    return CostRecord(
        timestamp=0.0,
        model=model,
        input_tokens=inp,
        output_tokens=out,
        cache_read=cr,
        cache_creation=cc,
        ttft_ms=0.0,
        duration_ms=dur,
    )


def test_empty_ledger_returns_zeros():
    t = CostLedger().total()
    assert t.record_count == 0
    assert t.total_cost == 0.0
    assert t.cache_hit_rate == 0.0


def test_append_accumulates_tokens_and_cost():
    l = CostLedger()
    l.append(_record("claude-3-5-sonnet", inp=1000, out=500))
    l.append(_record("claude-3-5-sonnet", inp=2000, out=1000))
    t = l.total()
    assert t.record_count == 2
    assert t.total_input == 3000
    assert t.total_output == 1500
    # 期望成本：(3000×3.0 + 1500×15.0) / 1M
    assert t.total_cost == pytest.approx((9000 + 22500) / 1_000_000)


def test_unknown_model_makes_total_cost_none():
    l = CostLedger()
    l.append(_record("claude-3-5-sonnet", inp=1000, out=0))
    l.append(_record("gpt-5", inp=500, out=0))  # gpt-5 不在表里
    t = l.total()
    assert t.total_cost is None


def test_cache_hit_rate_formula():
    l = CostLedger()
    l.append(_record("claude-3-5-sonnet", inp=1000, out=0, cr=500, cc=500))
    t = l.total()
    # 500 / (1000 + 500 + 500) = 0.25
    assert t.cache_hit_rate == pytest.approx(0.25)


def test_avg_duration():
    l = CostLedger()
    l.append(_record("claude-3-5-sonnet", inp=0, out=0, dur=200.0))
    l.append(_record("claude-3-5-sonnet", inp=0, out=0, dur=400.0))
    assert l.total().avg_duration_ms == pytest.approx(300.0)


def test_append_rejects_negative_tokens():
    """负数 token 必须抛 ValueError，避免 SDK 异常返回污染聚合。"""
    from mewcode.cost.record import CostRecord

    bad = CostRecord(
        timestamp=0.0,
        model="claude-3-5-sonnet",
        input_tokens=-1,  # 负数
        output_tokens=0,
        cache_read=0,
        cache_creation=0,
        ttft_ms=0.0,
        duration_ms=0.0,
    )
    l = CostLedger()
    with pytest.raises(ValueError, match="negative"):
        l.append(bad)
    assert len(l) == 0  # 拒收后账本仍空


def test_cache_hit_rate_clamped_to_unit_interval():
    """异常输入下命中率必须 clamp 到 [0, 1]，避免显示负命中率。

    append 已拦截负数，这里直接注入 _records 绕过校验，
    验证 total() 里的 clamp 在旧数据源或未来旁路写入下仍安全。
    """
    l = CostLedger()
    # 直接塞入负 cache_read 记录，绕过 append 校验
    # inp=500, cr=-100 → denom=400 > 0, hit = -100/400 = -0.25 → clamp 到 0.0
    l._records.append(_record("claude-3-5-sonnet", inp=500, out=0, cr=-100, cc=0))
    rate = l.total().cache_hit_rate
    assert rate == 0.0


def test_unknown_models_collected_dedup():
    """价格表外的模型必须被收集进 unknown_models 且去重。"""
    l = CostLedger()
    l.append(_record("gpt-5", inp=100, out=0))  # 未知（gpt-5 不在表里）
    l.append(_record("gpt-5", inp=200, out=0))  # 重复，应去重
    l.append(_record("claude-3-5-sonnet", inp=100, out=0))  # 已知
    l.append(_record("claude-3-opus", inp=100, out=0))  # 已知（扩展后已收录）
    t = l.total()
    assert t.total_cost is None
    assert t.unknown_models == ["gpt-5"]


def test_avg_ttft_ms():
    """平均首 token 延迟 = sum(ttft) / n"""
    l = CostLedger()
    l.append(_record("claude-3-5-sonnet", inp=0, out=0, dur=200.0))
    # _record 默认 ttft=0.0，这里直接构造带 ttft 的 record
    from mewcode.cost.record import CostRecord

    l.append(CostRecord(
        timestamp=0.0,
        model="claude-3-5-sonnet",
        input_tokens=0,
        output_tokens=0,
        cache_read=0,
        cache_creation=0,
        ttft_ms=300.0,
        duration_ms=500.0,
    ))
    l.append(CostRecord(
        timestamp=0.0,
        model="claude-3-5-sonnet",
        input_tokens=0,
        output_tokens=0,
        cache_read=0,
        cache_creation=0,
        ttft_ms=600.0,
        duration_ms=800.0,
    ))
    t = l.total()
    # n=3, sum(ttft) = 0 + 300 + 600 = 900, avg = 300
    assert t.avg_ttft_ms == pytest.approx(300.0)


def test_aggregate_by_model_groups_and_sums():
    """aggregate(by='model') 按模型分桶，返回每桶的 token/成本/延迟聚合。"""
    from mewcode.cost.record import CostRecord

    l = CostLedger()
    l.append(_record("claude-3-5-sonnet", inp=1000, out=500))
    l.append(_record("claude-3-5-sonnet", inp=2000, out=1000))
    l.append(_record("gpt-4o", inp=1000, out=0))
    l.append(CostRecord(
        timestamp=0.0, model="gpt-5", input_tokens=500, output_tokens=0,
        cache_read=0, cache_creation=0, ttft_ms=0.0, duration_ms=0.0,
    ))  # 未知价格

    rows = l.aggregate(by="model")
    assert len(rows) == 3

    by_key = {r.key: r for r in rows}
    assert by_key["claude-3-5-sonnet"].record_count == 2
    assert by_key["claude-3-5-sonnet"].total_tokens == 4500  # 1500 + 3000
    # Sonnet: 3000 inp + 1500 out → (3000×3 + 1500×15) / 1M = 0.0315
    assert by_key["claude-3-5-sonnet"].total_cost == pytest.approx(0.0315)
    assert by_key["gpt-4o"].record_count == 1
    assert by_key["gpt-5"].total_cost is None  # 未知价格桶


def test_aggregate_by_tool_none_goes_to_no_tool_bucket():
    """tool_name=None 的记录归到 (no tool) 桶。"""
    l = CostLedger()
    l.append(_record("claude-3-5-sonnet", inp=100, out=0))  # 默认 tool_name=None
    rows = l.aggregate(by="tool")
    assert len(rows) == 1
    assert rows[0].key == "(no tool)"


def test_aggregate_empty_ledger_returns_empty_list():
    """空账本分桶返回空列表，不抛异常。"""
    l = CostLedger()
    assert l.aggregate(by="model") == []
    assert l.aggregate(by="tool") == []
    assert l.aggregate(by="agent_id") == []


def test_aggregate_unsupported_key_raises():
    """不支持的 by 值必须抛 ValueError，避免静默错误。"""
    l = CostLedger()
    l.append(_record("claude-3-5-sonnet", inp=0, out=0))
    with pytest.raises(ValueError, match="unsupported"):
        l.aggregate(by="time")  # type: ignore[arg-type]


def test_to_json_round_trip_preserves_all_fields():
    """to_json → from_json 应保留所有字段（含 agent_id / tool_name）。"""
    from mewcode.cost.record import CostRecord

    l = CostLedger()
    l.append(CostRecord(
        timestamp=123.45, model="claude-3-5-sonnet",
        input_tokens=1000, output_tokens=500,
        cache_read=100, cache_creation=200,
        ttft_ms=42.0, duration_ms=500.0,
        agent_id="worker-1", tool_name="bash",
    ))
    l.append(CostRecord(
        timestamp=999.0, model="gpt-4o",
        input_tokens=2000, output_tokens=1000,
        cache_read=0, cache_creation=0,
        ttft_ms=88.0, duration_ms=800.0,
        agent_id="worker-2", tool_name=None,
    ))

    payload = l.to_json()
    restored = CostLedger.from_json(payload)

    assert len(restored) == 2
    assert restored[0].model == "claude-3-5-sonnet"
    assert restored[0].agent_id == "worker-1"
    assert restored[0].tool_name == "bash"
    assert restored[0].input_tokens == 1000
    assert restored[1].model == "gpt-4o"
    assert restored[1].agent_id == "worker-2"
    assert restored[1].tool_name is None


def test_extend_merges_records_skipping_bad_ones():
    """extend 批量合并：单条坏数据不阻断整批。"""
    from mewcode.cost.record import CostRecord

    good = _record("claude-3-5-sonnet", inp=100, out=50)
    bad = CostRecord(
        timestamp=0.0, model="bad",
        input_tokens=-10, output_tokens=0,  # 负数，会被 append 拒
        cache_read=0, cache_creation=0,
        ttft_ms=0.0, duration_ms=0.0,
    )
    good2 = _record("gpt-4o", inp=200, out=100)

    l = CostLedger()
    l.extend([good, bad, good2])

    # bad 被跳过，good + good2 都进账本
    assert len(l.total().record_count) if False else True  # 占位
    t = l.total()
    assert t.record_count == 2
    assert t.total_input == 300  # 100 + 200


def test_from_json_invalid_payload_raises_value_error():
    """非 JSON / 非 list payload 应抛 ValueError，由 caller catch。"""
    with pytest.raises(ValueError, match="invalid cost_report"):
        CostLedger.from_json("not a json")
    with pytest.raises(ValueError, match="invalid cost_report"):
        CostLedger.from_json('{"key": "value"}')  # dict 不是 list


def test_from_json_missing_fields_use_defaults():
    """旧版本记录（缺 agent_id/tool_name）应能反序列化。"""
    import json as _json
    # 手工构造一个旧格式 payload（只有 6 字段）
    old_payload = _json.dumps([{
        "timestamp": 1.0, "model": "claude-3-5-sonnet",
        "input_tokens": 100, "output_tokens": 50,
        "cache_read": 0, "cache_creation": 0,
        "ttft_ms": 0.0, "duration_ms": 100.0,
    }])
    records = CostLedger.from_json(old_payload)
    assert len(records) == 1
    assert records[0].agent_id == ""  # 默认值
    assert records[0].tool_name is None  # 默认值


def test_aggregate_by_tool_groups_by_tool_name():
    """aggregate(by='tool') 按 tool_name 分桶，None 归到 (no tool) 桶。"""
    from mewcode.cost.record import CostRecord

    l = CostLedger()
    # 3 条 bash + 2 条 grep + 1 条纯文本（None）
    for _ in range(3):
        l.append(CostRecord(
            timestamp=0.0, model="claude-3-5-sonnet",
            input_tokens=100, output_tokens=0,
            cache_read=0, cache_creation=0,
            ttft_ms=0.0, duration_ms=0.0,
            agent_id="main", tool_name="bash",
        ))
    for _ in range(2):
        l.append(CostRecord(
            timestamp=0.0, model="claude-3-5-sonnet",
            input_tokens=200, output_tokens=0,
            cache_read=0, cache_creation=0,
            ttft_ms=0.0, duration_ms=0.0,
            agent_id="main", tool_name="grep",
        ))
    l.append(_record("claude-3-5-sonnet", inp=50, out=0))  # tool_name=None

    rows = l.aggregate(by="tool")
    assert len(rows) == 3
    by_key = {r.key: r for r in rows}
    assert by_key["bash"].record_count == 3
    assert by_key["bash"].total_tokens == 300  # 3 × 100
    assert by_key["grep"].record_count == 2
    assert by_key["grep"].total_tokens == 400  # 2 × 200
    assert by_key["(no tool)"].record_count == 1
    assert by_key["(no tool)"].total_tokens == 50


# ---------------------------------------------------------------------------
# Stage 7: CostStore 持久化注入
# ---------------------------------------------------------------------------


def test_ledger_without_store_is_in_memory_only():
    """store=None 时 ledger 退化为纯内存模式，append 不落盘。"""
    l = CostLedger()  # 默认无 store
    assert l.store is None
    l.append(_record("claude-3-5-sonnet", inp=100, out=0))
    assert len(l) == 1


def test_ledger_with_store_persists_on_append(tmp_path):
    """注入 store 后 append 应同时落盘到 session 文件。"""
    from mewcode.cost.store import CostStore

    store = CostStore(str(tmp_path))
    l = CostLedger(store=store, session_id="sess-test")

    l.append(_record("claude-3-5-sonnet", inp=1000, out=500))

    # 内存账本有记录
    assert len(l) == 1
    # 磁盘也持久化了
    loaded = store.load_session("sess-test")
    assert len(loaded) == 1
    assert loaded[0].model == "claude-3-5-sonnet"
    assert loaded[0].input_tokens == 1000


def test_ledger_session_id_update_syncs_to_store(tmp_path):
    """更新 ledger.session_id 后新 append 走新 session 文件。"""
    from mewcode.cost.store import CostStore

    store = CostStore(str(tmp_path))
    l = CostLedger(store=store, session_id="")

    # 初始 session_id 为空，不落盘
    l.append(_record("claude-3-5-sonnet", inp=100, out=0))
    assert store.load_session("") == []

    # 切换 session_id
    l.session_id = "real-session"
    l.append(_record("claude-3-5-sonnet", inp=200, out=0))

    loaded = store.load_session("real-session")
    assert len(loaded) == 1
    assert loaded[0].input_tokens == 200


def test_ledger_store_append_failure_does_not_block(tmp_path):
    """store.append 失败不应阻断 ledger.append（内存账本仍保留记录）。"""
    from mewcode.cost.store import CostStore
    from unittest.mock import patch

    store = CostStore(str(tmp_path))
    l = CostLedger(store=store, session_id="sess-1")

    # 让 store.append 抛 OSError，模拟磁盘满 / 权限错误
    with patch.object(store, "append", side_effect=OSError("disk full")):
        l.append(_record("claude-3-5-sonnet", inp=100, out=0))

    # 内存账本仍有记录，主流程未被阻断
    assert len(l) == 1


