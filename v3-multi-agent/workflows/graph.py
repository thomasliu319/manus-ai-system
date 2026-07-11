"""
workflows/graph.py — LangGraph 工作流组装

拓扑（7 节点完整版）:
  START → plan → collect → analyze → review ─┬──(passed)──────────→ organize → save → END
                                               ├──(not passed,<max)→ revise → review (loop)
                                               └──(not passed,≥max)→ human_flag → END

plan 节点根据目标采集量输出策略，下游通过 state["plan"] 读取 max_iterations 等参数。
"""


from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langgraph.graph import END, START, StateGraph

from workflows.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    save_node,
)
from workflows.state import KBState
from workflows.reviewer import review_node
from workflows.reviser import revise_node
from workflows.human_flag import human_flag_node
from workflows.planner import planner_node

logger = logging.getLogger(__name__)

# ── 路由器 ────────────────────────────────────────────────────────────────


def route_after_review(state: KBState) -> str:
    """条件路由：审核后 3 条出口，max_iterations 从 plan 读取"""
    plan = state.get("plan", {}) or {}
    max_iter = int(plan.get("max_iterations", 3))
    iteration = state.get("iteration", 0)

    if state.get("review_passed", False):
        return "organize"
    if iteration >= max_iter:
        return "human_flag"
    return "revise"


# ── 图构建 ────────────────────────────────────────────────────────────────


def build_graph() -> Any:
    """
    组装并编译 LangGraph 工作流。

    Returns:
        CompiledStateGraph — 已编译的可执行图
    """
    builder = StateGraph(KBState)

    # 注册节点
    builder.add_node("plan", planner_node)
    builder.add_node("collect", collect_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("organize", organize_node)
    builder.add_node("review", review_node)
    builder.add_node("revise", revise_node)
    builder.add_node("human_flag", human_flag_node)
    builder.add_node("save", save_node)

    # 入口：plan → collect → analyze → review
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "collect")
    builder.add_edge("collect", "analyze")
    builder.add_edge("analyze", "review")

    # 条件边：审核之后的分支
    builder.add_conditional_edges(
        "review",
        route_after_review,
        {
            "organize": "organize",
            "revise": "revise",
            "human_flag": "human_flag",
        },
    )

    # 修订后回审核，形成 review → revise 循环
    builder.add_edge("revise", "review")

    # 整理 → 保存 → 结束
    builder.add_edge("organize", "save")
    builder.add_edge("save", END)

    # 兜底退出
    builder.add_edge("human_flag", END)

    return builder.compile()


# ── 初始状态 ──────────────────────────────────────────────────────────────


def make_initial_state() -> KBState:
    """构建初始工作流状态。"""
    return KBState(
        plan={},
        sources=[],
        analyses=[],
        articles=[],
        review_feedback="",
        review_passed=False,
        iteration=0,
        needs_human_review=False,
        cost_tracker={
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "estimated_cost_usd": 0.0,
            "by_node": {},
        },
    )


# ── 测试入口 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    app = build_graph()
    initial = make_initial_state()

    print("=" * 60)
    print("LangGraph 工作流 — 采集 → 分析 → 审核 → 整理 → 保存")
    print("=" * 60)

    # invoke 执行全流水线（节点内部 print() 提供实时输出）
    final = app.invoke(initial)
    tracker = final.get("cost_tracker", {})

    print(f"\n{'=' * 60}")
    print(f"流水线完成")
    print(f"  采集: {len(final.get('sources', []))} 条")
    print(f"  分析: {len(final.get('analyses', []))} 条")
    print(f"  整理: {len(final.get('articles', []))} 条")
    print(
        f"  审核: {'通过' if final.get('review_passed') else '未通过'}"
        f"  (轮次: {final.get('iteration', 0)})"
    )
    print(
        f"  Token: {tracker.get('total_prompt_tokens', 0)} prompt"
        f" + {tracker.get('total_completion_tokens', 0)} completion"
    )
    print(f"  成本: ${tracker.get('estimated_cost_usd', 0):.6f}")
