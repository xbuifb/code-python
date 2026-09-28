"""成本价格表与单条成本计算的最小闭环单测。"""
from __future__ import annotations

import pytest

from mewcode.cost.pricing import compute_cost, price_for
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
    assert price_for("gpt-4o") is None


def test_compute_cost_basic():
    r = _record("claude-3-5-sonnet", inp=1_000_000, out=0)
    # 1M 输入 token × $3.0/M = $3.0
    assert compute_cost(r, price_for("claude-3-5-sonnet")) == pytest.approx(3.0)


def test_compute_cost_with_cache():
    r = _record("claude-3-5-sonnet", inp=0, out=0, cr=1_000_000, cc=0)
    # 1M 缓存读 × $0.30/M = $0.30
    assert compute_cost(r, price_for("claude-3-5-sonnet")) == pytest.approx(0.30)


def test_compute_cost_unknown_price_returns_none():
    r = _record("gpt-4o", inp=1000, out=500)
    assert compute_cost(r, price_for("gpt-4o")) is None
