from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from mewcode.cost.pricing import compute_cost, price_for
from mewcode.cost.record import CostRecord

if TYPE_CHECKING:
    from mewcode.cost.store import CostStore

log = logging.getLogger(__name__)


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


@dataclass
class AggregateRow:
    """分桶聚合行：按 tool/model/agent_id 任一维度切片后的单行结果。"""

    key: str
    record_count: int
    total_tokens: int
    total_cost: float | None
    avg_ttft_ms: float
    avg_duration_ms: float


class CostLedger:
    """会话级成本账本。

    单 Agent + 单事件循环模型下无需加锁；后续引入子 Agent 跨进程
    回传时再考虑锁或独立 ledger + merge。
    """

    def __init__(
        self,
        store: "CostStore | None" = None,
        session_id: str = "",
    ) -> None:
        self._records: list[CostRecord] = []
        # Stage 7: 跨会话持久化。store 为 None 时退化为纯内存模式
        # （测试 / 早期入口未注入 CostStore 的兜底路径）。
        self._store = store
        self.session_id = session_id

    def append(self, record: CostRecord) -> None:
        # 防御性校验：观测数据污染比丢数据更糟，负数 token 拒收。
        if record.input_tokens < 0 or record.output_tokens < 0:
            raise ValueError(f"negative token count: {record}")
        if record.cache_read < 0 or record.cache_creation < 0:
            raise ValueError(f"negative cache token count: {record}")
        self._records.append(record)
        # 持久化失败不阻断主流程：内存账本已记录，磁盘缺失只是历史查询
        # 少一条，比让 LLM 调用因观测落盘失败而中断更可接受。
        if self._store is not None:
            try:
                self._store.append(record, self.session_id)
            except (OSError, TypeError, ValueError) as e:
                log.warning("cost 持久化失败: %s", e, exc_info=False)

    def extend(self, records: list[CostRecord]) -> None:
        """批量 append，用于跨进程 cost_report 合并。

        单条失败不阻断整批，但会记录 warning，因为观测合并不能因一条坏数据
        丢掉整组 worker 数据。
        """
        import logging
        log = logging.getLogger(__name__)
        for r in records:
            try:
                self.append(r)
            except ValueError as e:
                log.warning("跳过坏记录: %s", e)

    def to_json(self) -> str:
        """序列化为 JSON 字符串，用于跨进程邮箱传输。"""
        from dataclasses import asdict
        return json.dumps(
            [asdict(r) for r in self._records],
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(payload: str) -> list[CostRecord]:
        """反序列化 JSON 字符串为 CostRecord 列表。

        静态方法：不要求 caller 持有 CostLedger 实例，drain_lead_mailbox
        可以用 CostLedger.from_json(msg.text) 解析。
        任何解析错误都抛 ValueError，由 caller catch 后跳过这条消息。
        """
        try:
            data = json.loads(payload)
            if not isinstance(data, list):
                raise ValueError("payload is not a list")
            records: list[CostRecord] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                # 容错：缺失字段用默认值，避免旧版本记录反序列化失败
                records.append(CostRecord(
                    timestamp=float(item.get("timestamp", 0.0)),
                    model=str(item.get("model", "")),
                    input_tokens=int(item.get("input_tokens", 0)),
                    output_tokens=int(item.get("output_tokens", 0)),
                    cache_read=int(item.get("cache_read", 0)),
                    cache_creation=int(item.get("cache_creation", 0)),
                    ttft_ms=float(item.get("ttft_ms", 0.0)),
                    duration_ms=float(item.get("duration_ms", 0.0)),
                    agent_id=str(item.get("agent_id", "")),
                    tool_name=item.get("tool_name"),
                ))
            return records
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise ValueError(f"invalid cost_report payload: {e}") from e

    def __len__(self) -> int:
        return len(self._records)

    @property
    def store(self) -> "CostStore | None":
        """暴露底层 CostStore，供 /cost history 命令查询历史。"""
        return self._store

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

    def aggregate(
        self,
        by: Literal["tool", "model", "agent_id"],
    ) -> list[AggregateRow]:
        """按维度分桶聚合。

        by="tool" 按 tool_name（None 归到 "(no tool)" 桶）；
        by="model" 按模型名；
        by="agent_id" 按 agent_id。
        每行返回该桶的记录数、token 总数、成本（桶内任一未知则 None）、
        平均 TTFT、平均 duration。
        """
        if not self._records:
            return []

        buckets: dict[str, list[CostRecord]] = defaultdict(list)
        for r in self._records:
            if by == "tool":
                key = r.tool_name if r.tool_name else "(no tool)"
            elif by == "model":
                key = r.model
            elif by == "agent_id":
                key = r.agent_id
            else:
                raise ValueError(f"unsupported aggregation key: {by}")
            buckets[key].append(r)

        rows: list[AggregateRow] = []
        for key, recs in buckets.items():
            n = len(recs)
            total_tokens = sum(r.input_tokens + r.output_tokens for r in recs)
            # 桶内任一记录价格未知 → total_cost = None
            cost: float | None = 0.0
            for r in recs:
                price = price_for(r.model)
                if price is None:
                    cost = None
                    break
                if cost is not None:
                    cost += compute_cost(r, price)
            rows.append(AggregateRow(
                key=key,
                record_count=n,
                total_tokens=total_tokens,
                total_cost=cost,
                avg_ttft_ms=sum(r.ttft_ms for r in recs) / n,
                avg_duration_ms=sum(r.duration_ms for r in recs) / n,
            ))
        # 按成本降序（None 视为 +inf 排前）
        rows.sort(key=lambda x: (x.total_cost is not None, -(x.total_cost or 0)), reverse=True)
        return rows
