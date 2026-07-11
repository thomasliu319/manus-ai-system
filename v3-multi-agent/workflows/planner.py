"""Planner — 策略规划节点

根据目标采集量返回三档采集策略，下游节点通过 state["plan"] 读取。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workflows.state import KBState  # noqa: E402

logger = logging.getLogger(__name__)

# ── 三档策略 ──────────────────────────────────────────────────────────────

_STRATEGIES = {
    "lite": {
        "per_source_limit": 5,
        "relevance_threshold": 0.7,
        "max_iterations": 1,
        "rationale": "目标量少 (<10)，优先保证质量，高门槛筛选",
    },
    "standard": {
        "per_source_limit": 10,
        "relevance_threshold": 0.5,
        "max_iterations": 2,
        "rationale": "目标量适中 (10-19)，平衡质量与数量",
    },
    "full": {
        "per_source_limit": 20,
        "relevance_threshold": 0.4,
        "max_iterations": 3,
        "rationale": "目标量大 (>=20)，降低门槛覆盖更多内容",
    },
}


def plan_strategy(target_count: int | None = None) -> dict[str, Any]:
    """根据目标采集量返回策略 dict。

    Args:
        target_count: 目标采集条目数，None 时从环境变量 PLANNER_TARGET_COUNT 读取（默认 10）

    Returns:
        三档之一: lite / standard / full
    """
    if target_count is None:
        target_count = int(os.getenv("PLANNER_TARGET_COUNT", "10"))

    if target_count < 10:
        tier = "lite"
    elif target_count < 20:
        tier = "standard"
    else:
        tier = "full"

    plan = {"tier": tier, **{k: v for k, v in _STRATEGIES[tier].items()}}
    logger.info("[Planner] target=%d → 策略: %s | %s", target_count, tier, plan["rationale"])
    return plan


def planner_node(state: KBState) -> dict[str, Any]:
    """LangGraph 节点包装：调 plan_strategy 生成 plan 并写入 state。

    Returns:
        {"plan": dict}
    """
    plan = plan_strategy()
    return {"plan": plan}
