from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from mewcode.cost.record import CostRecord

log = logging.getLogger(__name__)


@dataclass
class CostSessionMeta:
    """持久化会话的轻量元数据，用于 /cost history 列表展示。

    由 list_sessions 在读取时按需计算，不单独落盘 — 保持最小闭环：
    单个 jsonl 文件即为会话唯一数据源。
    """

    session_id: str
    record_count: int
    total_cost: float | None
    first_ts: float
    last_ts: float
    mtime: float


class CostStore:
    """跨会话成本记录持久化。

    存储布局：.mewcode/cost/{session_id}.jsonl，每行一条 CostRecord 的 JSON。
    与 session.py 的 .mewcode/sessions/{session_id}.jsonl 同构，便于审计对账。

    单 Agent + 单事件循环模型下无需加锁；append 走追加写 + flush，崩溃
    最多丢最后一条未 flush 的记录，可接受。list_sessions 用文件 mtime 排序，
    不预读内容以降低大目录下的列表成本。
    """

    def __init__(self, work_dir: str) -> None:
        self._dir = Path(work_dir) / ".mewcode" / "cost"
        # 尽早创建目录，但失败不抛异常：观测系统不能因目录创建失败
        # 拖垮整个 Agent（work_dir 可能为只读 / 沙箱受限路径）。
        # append 时会再次尝试创建，最终写入失败由 ledger 的 try/except 兜底。
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.jsonl"

    def append(self, record: CostRecord, session_id: str) -> None:
        """追加一条记录到会话的 jsonl 文件。

        session_id 为空时跳过 — 早期 Agent 未绑定 session 时不应落盘，
        否则会产生名为 .jsonl 的孤儿文件。
        """
        if not session_id:
            return
        path = self._path(session_id)
        # 懒创建目录：__init__ 可能因权限失败跳过，这里再试一次。
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(record), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()

    def load_session(self, session_id: str) -> list[CostRecord]:
        """读取单个会话的全部记录。

        坏行（JSON 解析失败 / 字段缺失）跳过并 warning，不抛异常 —
        观测历史查询不能因一条坏数据让整个会话不可读。
        """
        path = self._path(session_id)
        if not path.exists():
            return []
        records: list[CostRecord] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = _parse_record(line)
                if rec is not None:
                    records.append(rec)
        return records

    def list_sessions(self) -> list[CostSessionMeta]:
        """列出所有有 cost 数据的会话，按 mtime 降序。

        不预读记录内容；total_cost 等聚合字段在列表阶段按需计算，
        因为典型场景下会话数有限（数十到数百），全量计算可接受。
        """
        metas: list[CostSessionMeta] = []
        for path in self._dir.glob("*.jsonl"):
            session_id = path.stem
            records = self.load_session(session_id)
            stat = path.stat()
            if not records:
                # 空文件保留 mtime，record_count=0，仍列出便于清理
                metas.append(CostSessionMeta(
                    session_id=session_id,
                    record_count=0,
                    total_cost=0.0,
                    first_ts=0.0,
                    last_ts=0.0,
                    mtime=stat.st_mtime,
                ))
                continue
            # 延迟导入避免循环依赖
            from mewcode.cost.pricing import price_for, compute_cost
            cost: float | None = 0.0
            for r in records:
                price = price_for(r.model)
                if price is None:
                    cost = None
                    break
                if cost is not None:
                    cost += compute_cost(r, price)
            metas.append(CostSessionMeta(
                session_id=session_id,
                record_count=len(records),
                total_cost=cost,
                first_ts=min(r.timestamp for r in records),
                last_ts=max(r.timestamp for r in records),
                mtime=stat.st_mtime,
            ))
        metas.sort(key=lambda m: m.mtime, reverse=True)
        return metas


def _parse_record(line: str) -> CostRecord | None:
    """解析单行 JSON 为 CostRecord，失败返回 None。

    容错策略与 SessionRecord.from_jsonl 一致：缺失字段用默认值，
    避免旧版本记录或字段重命名导致整行丢失。
    """
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        log.warning("跳过坏 cost 行: %s", line[:80])
        return None
    if not isinstance(item, dict):
        return None
    try:
        return CostRecord(
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
        )
    except (TypeError, ValueError) as e:
        log.warning("跳过坏 cost 记录: %s", e)
        return None
