"""Reviser Agent — 定向修改节点（只修改不评估）

Reviser 和 Reviewer 是两个独立 Agent —— 避免 Reviewer 给自己打高分。
"""

import json
import logging
from typing import Any

from workflows.model_client import accumulate_usage, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)


def revise_node(state: KBState) -> dict[str, Any]:
    """Reviser 节点：根据 Reviewer 反馈定向修改 analyses"""
    analyses = state.get("analyses", [])
    feedback = state.get("review_feedback", "")
    iteration = state.get("iteration", 0)
    tracker = state.get("cost_tracker", {})

    if not analyses or not feedback:
        logger.info("[Reviser] 无可修改内容，跳过")
        return {}

    prompt = f"""你是知识库编辑。以下是审核员的反馈，请据此修改这些分析结果。

【审核反馈】
{feedback}

【当前分析结果】
{json.dumps(analyses, ensure_ascii=False, indent=2)}

【修改要求】
- 重点改进反馈中提到的弱项维度
- 保留已经不错的部分
- 保持相同字段结构
- 返回修改后的 JSON 数组"""

    try:
        improved, usage = chat_json(
            prompt,
            system="你是经验丰富的知识库编辑。根据反馈定向修改，不要过度发散。",
            temperature=0.4,
        )
        accumulate_usage(tracker, usage)
        if isinstance(improved, list) and improved:
            logger.info("[Reviser] 定向修改 %d 条 analyses (迭代 %d)", len(improved), iteration)
            return {"analyses": improved, "cost_tracker": tracker}
    except Exception as e:
        logger.warning("[Reviser] 修改失败: %s", e)

    return {"cost_tracker": tracker}
