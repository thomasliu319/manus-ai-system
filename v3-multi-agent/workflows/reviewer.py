"""
workflows/reviewer.py — 审核节点

审核 state["analyses"] 的前 5 条，5 维度评分 + 加权重算。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workflows.state import KBState  # noqa: E402
from workflows.model_client import (  # noqa: E402
    accumulate_usage,
    chat_json,
)

logger = logging.getLogger(__name__)

# ── 维度和权重 ──
_WEIGHTS: dict[str, float] = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}

_MAX_ANALYSES = 5
_PASS_THRESHOLD = 9.0  # 临时提高以触发 revise 分支

_REVIEW_SYSTEM = "你是一个严格的知识质量审核专家。只返回 JSON，不要解释。"

_REVIEW_PROMPT = """审核以下技术分析条目，从 5 个维度独立评分（各 1-10 分，整数）:

1. summary_quality（摘要质量）: 摘要是否准确凝练，能否独立传达核心信息
2. technical_depth（技术深度）: 分析是否触及技术本质，有无深层洞察
3. relevance（相关性）: 内容与 AI/LLM/Agent 领域的相关程度
4. originality（原创性）: 内容是否独特，非泛泛而谈
5. formatting（格式规范）: 标签、分类、摘要格式是否规范一致

条目:
{analyses}

返回 JSON:
{{
  "scores": {{
    "summary_quality": 8,
    "technical_depth": 7,
    "relevance": 9,
    "originality": 6,
    "formatting": 8
  }},
  "feedback": "审核意见（未通过时必须给出具体改进方向）"
}}"""


def review_node(state: KBState) -> dict[str, Any]:
    """
    审核节点：对前 5 条 analyses 做 5 维度评分，代码重算加权总分。

    Returns:
        {"review_passed": bool, "review_feedback": str, "iteration": int, "cost_tracker": dict}
    """
    print("[ReviewNode] 开始审核 analyses...")

    analyses: list[dict[str, Any]] = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    tracker: dict[str, Any] = state.get("cost_tracker", {})
    plan = state.get("plan", {}) or {}
    max_iter = int(plan.get("max_iterations", 3))

    if not analyses:
        print("[ReviewNode] 无数据可审核，通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    if iteration >= max_iter:
        logger.info("[ReviewNode] iteration=%d >= max_iter=%d，强制通过", iteration, max_iter)
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    review_items = analyses[:_MAX_ANALYSES]
    print(f"[ReviewNode] 审核前 {len(review_items)}/{len(analyses)} 条")

    prompt = _REVIEW_PROMPT.format(
        analyses=json.dumps(review_items, ensure_ascii=False, indent=2)
    )

    try:
        result, usage = chat_json(prompt, system=_REVIEW_SYSTEM, temperature=0.1)
        accumulate_usage(tracker, usage)

        scores = result.get("scores", {})
        llm_feedback = str(result.get("feedback", ""))

        weighted_total = 0.0
        for dim, weight in _WEIGHTS.items():
            weighted_total += float(scores.get(dim, 0)) * weight

        passed = weighted_total >= _PASS_THRESHOLD
        feedback = llm_feedback

        print(f"  scores={json.dumps(scores, ensure_ascii=False)}")
        print(f"  weighted_total={weighted_total:.2f}  passed={passed}")
    except Exception as e:
        logger.warning("审核调用失败: %s，自动通过", e)
        passed = True
        feedback = ""

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }
