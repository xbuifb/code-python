from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CostRecord:
    """单次 LLM 调用的成本原始记录。

    最小闭环只保留 8 个必要字段；按 tool / agent_id 聚合等扩展
    到后续迭代再加字段，避免提前铺满。
    """

    timestamp: float
    model: str
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_creation: int
    ttft_ms: float          # 首 chunk 到达时间
    duration_ms: float       # 整个 LLM 调用耗时
