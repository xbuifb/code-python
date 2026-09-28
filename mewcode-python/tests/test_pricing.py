"""成本价格表与单条成本计算的最小闭环单测。"""
from __future__ import annotations

import pytest

from mewcode.cost.pricing import Price, compute_cost, price_for
from mewcode.cost.record import CostRecord


def _record(model: str, inp: int, out: int, cr: int = 0, cc: int = 0) -> CostRecord:
    return CostRecord(
        timestamp=0.0,
        model=model,
        input_tokens=inp,
        output_tokens=out,
        cache_read=cr,
        cache_creation=cc,
        ttft_ms=0.0,
        duration_ms=0.0,
    )


def test_price_for_known_model():
    p = price_for("claude-3-5-sonnet")
    assert p is not None
    assert p.input_per_mtok == 3.0
    assert p.output_per_mtok == 15.0


def test_price_for_unknown_model_returns_none():
    # gpt-5 在 2025 年公开定价表里未收录
    assert price_for("gpt-5") is None


def test_compute_cost_basic():
    r = _record("claude-3-5-sonnet", inp=1_000_000, out=0)
    # 1M 输入 token × $3.0/M = $3.0
    assert compute_cost(r, price_for("claude-3-5-sonnet")) == pytest.approx(3.0)


def test_compute_cost_with_cache():
    r = _record("claude-3-5-sonnet", inp=0, out=0, cr=1_000_000, cc=0)
    # 1M 缓存读 × $0.30/M = $0.30
    assert compute_cost(r, price_for("claude-3-5-sonnet")) == pytest.approx(0.30)


def test_compute_cost_unknown_price_returns_none():
    r = _record("gpt-5", inp=1000, out=500)
    assert compute_cost(r, price_for("gpt-5")) is None


def test_price_for_gpt4o_and_dated_variants():
    """GPT-4o 主版本与日期版本都能查到，价格符合 2025 年公开定价。"""
    assert price_for("gpt-4o") == Price(2.50, 10.0, 1.25, 0.0)
    assert price_for("gpt-4o-2024-08-06") == Price(2.50, 10.0, 1.25, 0.0)
    # 早版本定价更高（5/15）测试覆盖
    assert price_for("gpt-4o-2024-05-13") == Price(5.0, 15.0, 2.50, 0.0)


def test_price_for_claude_opus_and_haiku_3():
    """扩展覆盖 Claude 3 Opus / Haiku / Sonnet 历代模型。"""
    assert price_for("claude-3-opus").input_per_mtok == 15.0
    assert price_for("claude-3-haiku").input_per_mtok == 0.25
    assert price_for("claude-3-sonnet").input_per_mtok == 3.0


def test_compute_cost_gpt4o_cache_read():
    """GPT-4o 输入 1000 + cache_read 500 → 0.0025 + 0.000625 = 0.003125"""
    r = _record("gpt-4o", inp=1000, out=0, cr=500)
    p = price_for("gpt-4o")
    assert compute_cost(r, p) == pytest.approx(0.003125)


def test_reload_pricing_returns_count_and_keeps_built_in():
    """reload_pricing() 应返回条目数，且内置表条目仍可查到。"""
    from mewcode.cost.pricing import reload_pricing

    count = reload_pricing()
    assert count > 0
    # 内置表条目不受 reload 影响
    assert price_for("claude-3-5-sonnet") is not None
    assert price_for("gpt-4o") is not None
