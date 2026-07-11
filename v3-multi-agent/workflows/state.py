"""
workflows/state.py — LangGraph 工作流共享状态定义

「报告式通信」原则：
  每个字段都是下游节点可直接消费的结构化摘要，不包含原始日志、API 响应、
  中间计算碎片或调试信息。上游产出什么格式，下游就按什么格式消费。
"""

from __future__ import annotations

from typing import TypedDict


class KBState(TypedDict):
    """
    LangGraph 知识库流水线共享状态。

    字段命名约定：
      - 复数名词表示可迭代的同类条目集合（sources / analyses / articles）
      - 布尔字段以 _passed 结尾表示审核/校验结果
      - 追踪类字段以 _tracker 结尾表示累积统计
    """

    # ── 采集层 ──────────────────────────────────────────────────────────
    sources: list[dict]
    """
    采集到的原始数据（结构化摘要，非 API 原始 JSON）。
    每个元素格式：
      {
        "id": "github-20260704-001",        # 唯一标识
        "title": "langgenius/dify",         # 项目/文章标题
        "source": "github",                 # 数据来源
        "source_url": "https://...",        # 原始 URL
        "raw_description": "...",           # 原始描述（≤200 字摘要）
        "collected_at": "2026-07-04T...",   # ISO 8601 采集时间戳
      }
    """

    # ── 分析层 ──────────────────────────────────────────────────────────
    analyses: list[dict]
    """
    LLM 分析后的结构化结果，在 sources 基础上追加分析字段。
    每个元素格式：
      {
        ...sources 的所有字段,
        "summary": "LLM 生成的 2-3 句技术摘要",
        "score": 7,                        # 1-10 技术质量评分
        "tags": ["agent", "llm"],          # 技术标签列表
        "audience": "intermediate",        # beginner|intermediate|advanced
        "analyzed_at": "2026-07-04T...",   # 分析完成时间戳
      }
    """

    # ── 整理层 ──────────────────────────────────────────────────────────
    articles: list[dict]
    """
    去重、校验、格式化后的最终知识条目，直接写入 knowledge/articles/。
    每个元素格式：
      {
        "id": "github-20260704-001",
        "title": "langgenius/dify",
        "source": "github",
        "source_url": "https://...",
        "summary": "Dify 是一个生产级平台...",
        "score": 7,
        "tags": ["agent", "llm"],
        "audience": "intermediate",
        "published_at": "2026-07-04T...",
        "collected_at": "2026-07-04T...",
        "analyzed_at": "2026-07-04T...",
      }
    """

    # ── 审核层 ──────────────────────────────────────────────────────────
    review_feedback: str
    """
    审核反馈的结构化文本（非原始 Supervisor JSON）。
    格式约定：
      "通过" — 审核通过时返回空字符串 ""
      "不通过 — 深度不足，缺少 LangChain/Dify 的技术对比细节" — 包含维度+具体方向
    下游 Worker 可直接将本字段注入 _WORKER_RETRY_PROMPT 的 {feedback} 占位。
    """

    review_passed: bool
    """
    审核是否通过（score >= 7）。
    True  → 跳出审核循环，进入保存阶段
    False → 继续下一轮，或触发强制退出（iteration >= max_retries）
    """

    iteration: int
    """
    当前审核循环次数。
    初始为 0，每次 review_node 被调用则 +1。
    """

    needs_human_review: bool
    """
    是否需要人工审核介入。
    HumanFlag 节点在审核循环达到上限时设为 True，
    表示当前 analyses 质量不达标，已写入 pending_review/ 等人工处理。
    """

    # ── 成本追踪 ────────────────────────────────────────────────────────
    cost_tracker: dict
    """
    Token 用量与成本累积追踪。
    格式：
      {
        "total_prompt_tokens": 15000,
        "total_completion_tokens": 8000,
        "estimated_cost_usd": 0.045,
        "by_node": {
          "collect":  {"prompt": 0,    "completion": 0,    "cost": 0},
          "analyze":  {"prompt": 12000, "completion": 6000, "cost": 0.036},
          "organize": {"prompt": 0,    "completion": 0,    "cost": 0},
          "review":   {"prompt": 3000,  "completion": 2000, "cost": 0.009},
        },
      }
    by_node 按工作流节点拆分，便于定位成本瓶颈。
    """
