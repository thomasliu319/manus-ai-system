"""
patterns/supervisor.py — Supervisor 监督模式

Worker → Supervisor 审核循环：
  1. Worker 接收任务，输出 JSON 分析报告
  2. Supervisor 对输出评分（准确性/深度/格式，各 1-10）
  3. 通过 (score >= 7) → 返回结果
  4. 不通过 → 带反馈重做（最多 3 轮）
  5. 超过 3 轮 → 强制返回 + 警告

依赖: pipeline/model_client.py 的 chat()
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.model_client import chat as _raw_chat  # noqa: E402

logger = logging.getLogger(__name__)


# ── 模型调用封装 ─────────────────────────────────────────────────────────

def chat(prompt: str, system: str = "你是一个 AI 助手。") -> tuple[str, dict[str, int]]:
    """调用 LLM，返回 (text, usage) 元组。"""
    result = _raw_chat(prompt, system=system)
    return result["content"], result["usage"]


def _extract_json(text: str) -> str:
    """从 LLM 响应中提取 JSON 对象。"""
    text = text.strip()
    if (start := text.find("{")) >= 0 and (end := text.rfind("}")) >= 0:
        text = text[start:end + 1]
    return text.replace("\x00", "").replace("\x08", "").replace("\x0c", "")


def chat_json(
    prompt: str,
    system: str = "你是一个 JSON 输出专家。",
) -> dict[str, Any]:
    """调用 LLM，解析返回的 JSON。"""
    text, _ = chat(prompt, system=system + "\n只返回 JSON，不要包含任何其他文本。")
    return json.loads(_extract_json(text))


# ── Worker Agent ──────────────────────────────────────────────────────────

_WORKER_SYSTEM = """你是一个专业的技术分析专家。请根据任务要求，输出完整的 JSON 分析报告。

输出格式（必须严格 JSON）：
{
  "title": "分析报告标题",
  "analysis": "500 字以上的详细分析，包含技术要点、业界对比、发展趋势",
  "key_points": ["关键发现 1", "关键发现 2", "关键发现 3"],
  "conclusion": "2-3 句话总结"
}"""

_WORKER_PROMPT = "任务：{task}"

_WORKER_RETRY_PROMPT = """任务：{task}

⚠️ 上次审核未通过，请根据反馈改进你的分析：

{feedback}

请重新输出完整的 JSON 分析报告，确保更准确、更深入、格式更规范。"""


def _worker(task: str, feedback: str | None = None) -> dict[str, Any]:
    """Worker Agent：生成 JSON 分析报告。"""
    if feedback:
        prompt = _WORKER_RETRY_PROMPT.format(task=task, feedback=feedback)
    else:
        prompt = _WORKER_PROMPT.format(task=task)
    return chat_json(prompt, system=_WORKER_SYSTEM)


# ── Supervisor Agent ─────────────────────────────────────────────────────

_SUPERVISOR_SYSTEM = """你是一个严格的质量审核专家。请对分析报告从三个维度评分（各 1-10 分）：

1. **准确性**：事实是否正确，引述是否可靠，推理是否严谨
2. **深度**：分析是否深入本质，是否有独到见解，是否覆盖关键维度
3. **格式**：结构是否清晰，JSON 是否规范，语言是否专业

综合评分 = 三项取整平均。只需返回 JSON，不要解释。"""

_SUPERVISOR_PROMPT = """请审核以下分析报告：

{report}

返回 JSON：
{{"passed": true/false, "score": 1-10 的整数, "accuracy": 1-10, "depth": 1-10, "format": 1-10, "feedback": "改进建议（若通过可为空字符串）"}}

passed 为 true 当且仅当 score >= 7。若未通过，feedback 必须给出具体的、可操作的改进方向。"""


def _supervisor(report: dict[str, Any]) -> dict[str, Any]:
    """Supervisor Agent：审核 Worker 输出。"""
    report_json = json.dumps(report, ensure_ascii=False, indent=2)
    prompt = _SUPERVISOR_PROMPT.format(report=report_json)
    return chat_json(prompt, system=_SUPERVISOR_SYSTEM)


# ── 审核循环 + 统一入口 ──────────────────────────────────────────────────

def supervisor(task: str, max_retries: int = 3) -> dict[str, Any]:
    """
    Supervisor 监督模式入口。

    Args:
        task: 需要分析的任务描述
        max_retries: 最大重试轮数（默认 3）

    Returns:
        {
            "output": dict,        # Worker 最终输出的 JSON 分析报告
            "attempts": int,       # 实际尝试次数
            "final_score": int,    # 最终评分
            "warning": str | None, # 超限警告（仅在超过 max_retries 时出现）
        }
    """
    if not task or not task.strip():
        raise ValueError("task 不能为空")

    output: dict[str, Any] = {}
    final_score = 0
    attempts = 0
    warning: str | None = None
    feedback: str | None = None

    for attempt in range(1, max_retries + 2):  # +1 初始 + retries
        attempts = attempt
        try:
            output = _worker(task, feedback)
        except Exception as e:
            logger.warning("Worker 调用失败 (第 %d 轮): %s", attempt, e)
            feedback = f"上次生成失败 ({e})，请重新生成完整的 JSON 分析报告。"
            continue

        try:
            review = _supervisor(output)
        except Exception as e:
            logger.warning("Supervisor 调用失败 (第 %d 轮): %s", attempt, e)
            # Supervisor 异常时退化为宽松通过（避免无限循环）
            final_score = 5
            output["_review_note"] = f"审核跳过（Supervisor 异常: {e}）"
            break

        score = int(review.get("score", 0))
        final_score = score

        if score >= 7:
            output["_review"] = review
            break

        feedback = review.get("feedback", "请提高分析的准确性和深度。")
        if attempt > max_retries:
            warning = f"已达最大重试次数 ({max_retries})，当前评分 {score}，强制返回最后结果。"
            output["_review"] = review
            break

    return {
        "output": output,
        "attempts": attempts,
        "final_score": final_score,
        "warning": warning,
    }


# ── 测试入口 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import textwrap

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Supervisor 监督模式测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        示例:
          python3 patterns/supervisor.py "分析 2026 年 AI Agent 框架的技术趋势"
          python3 patterns/supervisor.py --task "评测 LangChain 与 Dify 的差异"
          python3 patterns/supervisor.py --verbose
        """),
    )
    parser.add_argument("task", nargs="?", default="", help="分析任务描述")
    parser.add_argument("--max-retries", type=int, default=3, help="最大重试轮数（默认 3）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.task:
        result = supervisor(args.task, max_retries=args.max_retries)
    else:
        # 默认演示任务
        demo_task = "分析 2026 年 AI Agent 框架的技术趋势（LangChain、Dify、CrewAI 等）"
        print(f"📋 任务: {demo_task}\n")
        result = supervisor(demo_task, max_retries=args.max_retries)

    print(f"{'='*60}")
    print(f"✅ 完成 — 尝试 {result['attempts']} 轮，最终评分 {result['final_score']}/10")
    if result["warning"]:
        print(f"⚠️  {result['warning']}")
    print(f"{'='*60}")

    output = result["output"]
    print(f"\n📝 标题: {output.get('title', 'N/A')}")
    print(f"\n📊 分析:\n{output.get('analysis', 'N/A')[:400]}")
    if "key_points" in output:
        print(f"\n🔑 关键发现:")
        for kp in output["key_points"]:
            print(f"  • {kp}")
    print(f"\n💡 结论: {output.get('conclusion', 'N/A')}")

    if "_review" in output:
        review = output["_review"]
        print(f"\n{'─'*60}")
        print(f"📋 审核详情: 准确性={review.get('accuracy','?')}  深度={review.get('depth','?')}  格式={review.get('format','?')}")
        fb = review.get("feedback", "").strip()
        if fb:
            print(f"💬 反馈: {fb}")
