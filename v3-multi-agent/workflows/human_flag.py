"""HumanFlag Agent — 人工介入节点（异常终点）"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from workflows.state import KBState

logger = logging.getLogger(__name__)


def human_flag_node(state: KBState) -> dict[str, Any]:
    """审核循环超过上限时的兜底 —— 写入 pending_review/ 目录"""
    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")

    logger.warning("[HumanFlag] 达到 %d 次审核仍未通过", iteration)
    logger.warning("[HumanFlag] 最后反馈: %s", feedback[:200])

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pending_dir = os.path.join(base, "knowledge", "pending_review")
    os.makedirs(pending_dir, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    filepath = os.path.join(pending_dir, f"pending-{today}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": today,
            "iterations_used": iteration,
            "last_feedback": feedback,
            "analyses": analyses,
        }, f, ensure_ascii=False, indent=2)

    logger.warning("[HumanFlag] 已保存到 %s", filepath)
    return {"needs_human_review": True}
