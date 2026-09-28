from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


# 覆盖 Anthropic / OpenAI 主流模型，按 2025 年公开定价表（USD / 1M token）。
# Anthropic cache_read ≈ input × 0.1，cache_creation ≈ input × 1.25。
# OpenAI 系列 cache_creation 固定 0（自动 prompt caching 不额外收费）。
_DEFAULT_PRICING: dict[str, Price] = {
    # Anthropic Claude 系列
    "claude-3-5-sonnet": Price(3.0, 15.0, 0.30, 3.75),
    "claude-3-5-sonnet-20241022": Price(3.0, 15.0, 0.30, 3.75),
    "claude-3-5-haiku": Price(0.80, 4.0, 0.08, 1.0),
    "claude-3-5-haiku-20241022": Price(0.80, 4.0, 0.08, 1.0),
    "claude-3-opus": Price(15.0, 75.0, 1.50, 18.75),
    "claude-3-opus-20240229": Price(15.0, 75.0, 1.50, 18.75),
    "claude-3-haiku": Price(0.25, 1.25, 0.025, 0.3125),
    "claude-3-sonnet": Price(3.0, 15.0, 0.30, 3.75),
    # OpenAI 系列（GPT-4o / 4o-mini / 4-turbo）
    # GPT-4o cache_read = input × 0.5（prompt caching 命中价半价）
    "gpt-4o": Price(2.50, 10.0, 1.25, 0.0),
    "gpt-4o-2024-08-06": Price(2.50, 10.0, 1.25, 0.0),
    "gpt-4o-2024-05-13": Price(5.0, 15.0, 2.50, 0.0),
    "gpt-4o-mini": Price(0.15, 0.60, 0.075, 0.0),
    "gpt-4o-mini-2024-07-18": Price(0.15, 0.60, 0.075, 0.0),
    "gpt-4-turbo": Price(10.0, 30.0, 5.0, 0.0),
}


def _load_user_pricing() -> dict[str, Price]:
    """从 ~/.mewcode/pricing.yaml 加载用户自定义价格表。

    失败（文件不存在 / PyYAML 未安装 / 解析失败 / 字段缺失）一律返回空表，
    绝不阻断启动 — 观测系统不能让价格表加载失败拖垮整个 Agent。
    """
    log = logging.getLogger(__name__)
    try:
        path = Path.home() / ".mewcode" / "pricing.yaml"
        if not path.exists():
            return {}
        try:
            import yaml
        except ImportError:
            log.warning("PyYAML 未安装，跳过 %s 加载", path)
            return {}
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        result: dict[str, Price] = {}
        for model, entry in data.items():
            if not isinstance(entry, dict):
                continue
            try:
                result[str(model)] = Price(
                    input_per_mtok=float(entry["input_per_mtok"]),
                    output_per_mtok=float(entry["output_per_mtok"]),
                    cache_read_per_mtok=float(entry.get("cache_read_per_mtok", 0.0)),
                    cache_creation_per_mtok=float(entry.get("cache_creation_per_mtok", 0.0)),
                )
            except (KeyError, TypeError, ValueError):
                log.warning("跳过坏条目: %s", model)
                continue
        log.info("从 %s 加载了 %d 条价格", path, len(result))
        return result
    except Exception as e:
        log.warning("加载用户价格表失败，回退默认表: %s", e)
        return {}


# 启动时合并：用户表覆盖同名模型，新增模型追加
_PRICING_TABLE: dict[str, Price] = {**_DEFAULT_PRICING, **_load_user_pricing()}


def reload_pricing() -> int:
    """运行时重新加载 ~/.mewcode/pricing.yaml 并合并到当前 _PRICING_TABLE。

    用于 /cost reload 子命令：用户改完 yaml 后不必重启 Agent。
    返回合并后价格表的总条目数，供命令回显。
    """
    global _PRICING_TABLE
    _PRICING_TABLE = {**_DEFAULT_PRICING, **_load_user_pricing()}
    return len(_PRICING_TABLE)


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
