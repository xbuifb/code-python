from __future__ import annotations

from dataclasses import dataclass

from mewcode.cost.record import CostRecord


@dataclass(frozen=True)
class Price:
    """模型单价，单位 USD / 百万 token。

    cache_read 对应 Anthropic 缓存命中价（≈ input × 0.1）；
    cache_creation 对应 Anthropic 缓存写入价（≈ input × 1.25）。
    OpenAI 系列 cache_creation 固定 0。
    """

    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_creation_per_mtok: float


# 最小闭环仅覆盖 Claude 3.5 Sonnet 与 Haiku 两款，按 Anthropic 公开定价表。
# 找不到模型返回 None，由上层决定如何展示（默认显示「价格未知」）。
_PRICING_TABLE: dict[str, Price] = {
    "claude-3-5-sonnet": Price(
        input_per_mtok=3.0,
        output_per_mtok=15.0,
        cache_read_per_mtok=0.30,
        cache_creation_per_mtok=3.75,
    ),
    "claude-3-5-haiku": Price(
        input_per_mtok=0.80,
        output_per_mtok=4.0,
        cache_read_per_mtok=0.08,
        cache_creation_per_mtok=1.0,
    ),
}


def price_for(model: str) -> Price | None:
    """按精确名查表；不匹配返回 None（最小闭环不做模糊匹配 fallback）。"""
    return _PRICING_TABLE.get(model)


def compute_cost(record: CostRecord, price: Price | None) -> float | None:
    """把单条记录的 token 数换算成 USD。price 为 None 时返回 None。"""
    if price is None:
        return None
    mtok = 1_000_000.0
    return (
        record.input_tokens * price.input_per_mtok
        + record.output_tokens * price.output_per_mtok
        + record.cache_read * price.cache_read_per_mtok
        + record.cache_creation * price.cache_creation_per_mtok
    ) / mtok
