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

