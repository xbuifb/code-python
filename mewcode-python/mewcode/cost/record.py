from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CostRecord:
    """单次 LLM 调用的成本原始记录。

    agent_id 区分主 Agent / 子 Agent / worktree teammate；
    tool_name 触发该轮 LLM 调用的最后一个 tool call（可空，表示
    纯用户 prompt 触发）。这两个字段在阶段 3 接入 aggregate 分桶。
    """

    timestamp: float
    model: str
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_creation: int
    ttft_ms: float
    duration_ms: float
    agent_id: str = ""
    tool_name: str | None = None
