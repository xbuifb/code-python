from __future__ import annotations

from dataclasses import dataclass, field

from mewcode.cost.pricing import compute_cost, price_for
from mewcode.cost.record import CostRecord


@dataclass
class LedgerTotal:
    """账本聚合结果（标量视图）。

    total_cost 为 None 表示存在至少一条记录的模型价格未知；
    unknown_models 列出这些模型名（去重），上层据此提示用户。
    """

    record_count: int
    total_input: int
    total_output: int
    total_cache_read: int
    total_cache_creation: int
    cache_hit_rate: float
    avg_ttft_ms: float
    avg_duration_ms: float
    total_cost: float | None
    unknown_models: list[str] = field(default_factory=list)


class CostLedger:
    """会话级成本账本。

    单 Agent + 单事件循环模型下无需加锁；后续引入子 Agent 跨进程
    回传时再考虑锁或独立 ledger + merge。
    """

    def __init__(self) -> None:
        self._records: list[CostRecord] = []

    def append(self, record: CostRecord) -> None:
        # 防止 SDK 异常返回负数 token 污染聚合。抛 ValueError 会被
        # agent.py 的 except 收住，主流程不阻断，但 ledger 不收脏数据。
        if record.input_tokens < 0 or record.output_tokens < 0:
            raise ValueError(f"negative token count: {record}")
        if record.cache_read < 0 or record.cache_creation < 0:
            raise ValueError(f"negative cache count: {record}")
        self._records.append(record)

    def __len__(self) -> int:
        return len(self._records)

    def total(self) -> LedgerTotal:
        n = len(self._records)
        if n == 0:
            return LedgerTotal(
                record_count=0,
                total_input=0,
                total_output=0,
                total_cache_read=0,
                total_cache_creation=0,
                cache_hit_rate=0.0,
                avg_ttft_ms=0.0,
                avg_duration_ms=0.0,
                total_cost=0.0,
                unknown_models=[],
            )

        ti = sum(r.input_tokens for r in self._records)
        to = sum(r.output_tokens for r in self._records)
        tcr = sum(r.cache_read for r in self._records)
        tcc = sum(r.cache_creation for r in self._records)
        # 缓存命中率：命中 / 真实 prompt 总规模，clamp 到 [0, 1]
        denom = ti + tcr + tcc
        hit = tcr / denom if denom > 0 else 0.0
        hit = max(0.0, min(1.0, hit))

        # 成本聚合：任一记录价格未知 → total_cost = None，并收集未知模型名
        unknown_models: list[str] = []
        cost_sum: float | None = 0.0
        for r in self._records:
            price = price_for(r.model)
            if price is None:
                if r.model not in unknown_models:
                    unknown_models.append(r.model)
                cost_sum = None
                continue  # 不 break，继续收集所有未知模型
            if cost_sum is not None:
                cost_sum += compute_cost(r, price)

        return LedgerTotal(
            record_count=n,
            total_input=ti,
            total_output=to,
            total_cache_read=tcr,
            total_cache_creation=tcc,
            cache_hit_rate=hit,
            avg_ttft_ms=sum(r.ttft_ms for r in self._records) / n,
            avg_duration_ms=sum(r.duration_ms for r in self._records) / n,
            total_cost=cost_sum,
            unknown_models=unknown_models,
        )
