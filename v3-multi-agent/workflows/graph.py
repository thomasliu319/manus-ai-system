"""
workflows/graph.py — LangGraph 工作流组装

拓扑:
  START → collect → analyze → organize → review ─→ save → END
                                    ↑                  │
                                    └──────────────────┘ (review_passed=False)

使用真实的 LangGraph API: StateGraph / START / END / add_conditional_edges
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
    review_node,
    save_node,
)
from workflows.state import KBState

logger = logging.getLogger(__name__)

# ── 路由器 ────────────────────────────────────────────────────────────────

def _review_router(state: KBState) -> str:
    """条件路由：审核通过 → save，未通过 → organize 重新修正。"""
    if state.get("review_passed"):
        return "save"
    return "organize"


# ── 图构建 ────────────────────────────────────────────────────────────────

def build_graph() -> Any:
    """
    组装并编译 LangGraph 工作流。

    Returns:
        CompiledStateGraph — 已编译的可执行图
    """
    builder = StateGraph(KBState)

    # 注册节点
    builder.add_node("collect", collect_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("organize", organize_node)
    builder.add_node("review", review_node)
    builder.add_node("save", save_node)

    # 线性边
    builder.add_edge(START, "collect")
    builder.add_edge("collect", "analyze")
    builder.add_edge("analyze", "organize")
    builder.add_edge("organize", "review")

    # 条件边：review 之后的分支
    builder.add_conditional_edges(
        "review",
        _review_router,
        {
            "save": "save",
            "organize": "organize",
        },
    )

    # 终端边
    builder.add_edge("save", END)

    return builder.compile()


# ── 初始状态 ──────────────────────────────────────────────────────────────

def make_initial_state() -> KBState:
    """构建初始工作流状态。"""
    return KBState(
        sources=[],
        analyses=[],
        articles=[],
        review_feedback="",
        review_passed=False,
        iteration=0,
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
    print("LangGraph 工作流 — 采集 → 分析 → 整理 → 审核 → 保存")
    print("=" * 60)

    # invoke 执行全流水线（节点内部 print() 提供实时输出）
    final = app.invoke(initial)
    tracker = final.get("cost_tracker", {})

    print(f"\n{'=' * 60}")
    print(f"流水线完成")
    print(f"  采集: {len(final.get('sources', []))} 条")
    print(f"  分析: {len(final.get('analyses', []))} 条")
    print(f"  整理: {len(final.get('articles', []))} 条")
    print(f"  审核: {'通过' if final.get('review_passed') else '未通过'}"
          f"  (轮次: {final.get('iteration', 0)})")
    print(f"  Token: {tracker.get('total_prompt_tokens', 0)} prompt"
          f" + {tracker.get('total_completion_tokens', 0)} completion")
    print(f"  成本: ${tracker.get('estimated_cost_usd', 0):.6f}")
