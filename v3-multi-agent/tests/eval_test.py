"""eval_test.py — AI 知识库评估测试

测试 AI 分析流水线在各种输入场景下的表现：
  - 正面案例：技术文章 → 应有摘要、标签
  - 负面案例：无关内容 → 应低相关过滤
  - 边界案例：极短输入 → 不应崩溃
  - LLM-as-Judge：LLM 对自身输出打分
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

# ── 环境初始化 ─────────────────────────────────────────────────────────────

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workflows.model_client import chat  # noqa: E402

logger = logging.getLogger(__name__)

# ── 评估用例 ───────────────────────────────────────────────────────────────

EVAL_CASES: list[dict[str, Any]] = [
    {
        "name": "正面案例 — 技术文章分析",
        "input": (
            "标题: OpenAI发布GPT-5，支持多模态推理\n"
            "来源: techcrunch\n"
            "描述: OpenAI于2026年7月发布GPT-5，新模型支持文本、图像、音频的多模态推理，"
            "在MMLU基准测试上达到95.3%准确率，推理速度比GPT-4快3倍。"
            "开发者可通过API调用，价格降低40%。"
        ),
        "expected": {
            # summary 至少 20 字，含关键词
            "summary_len": (">=", 20),
            # 标签应包含相关技术词
            "tags_contain": lambda tags: any(
                t in [tag.lower() for tag in tags]
                for t in ["llm", "gpt", "openai", "model"]
            ),
            # 相关性应较高
            "relevance": (">=", 0.5),
        },
    },
    {
        "name": "负面案例 — 无关内容过滤",
        "input": (
            "标题: 2026年NBA总决赛回顾\n"
            "来源: espn\n"
            "描述: 2026年NBA总决赛第七场，湖人队以112-108击败凯尔特人，"
            "勒布朗·詹姆斯获得总决赛MVP，这是他职业生涯第五个总冠军。"
        ),
        "expected": {
            # 相关性应很低（体育无关 AI）
            "relevance": ("<=", 0.4),
        },
    },
    {
        "name": "边界案例 — 极短输入不崩溃",
        "input": (
            "标题: AI\n"
            "来源: unknown\n"
            "描述: AI"
        ),
        "expected": {
            # 不崩溃即可，有返回就算通过
            "no_crash": True,
            # summary 非空
            "summary_len": (">=", 1),
        },
    },
]

# ── 分析提示词 ─────────────────────────────────────────────────────────────

_ANALYZE_PROMPT = """分析以下内容，返回 JSON：

{input}

返回 JSON（relevance 为 0-1 的相关性评分）:
{{
  "summary": "2-3句中文技术摘要",
  "relevance": 0.85,
  "tags": ["标签1", "标签2"],
  "category": "分类"
}}

可用标签: agent, rag, mcp, llm, fine-tuning, prompt-engineering, multi-agent,
tool-use, evaluation, deployment, security, reasoning, code-generation, vision, audio

分类可选: agent-framework, llm-platform, rag-engine, developer-tool, research, other"""

# ── Judge 提示词 ───────────────────────────────────────────────────────────

_JUDGE_PROMPT = """你是一个评估专家。对以下 AI 分析结果的质量打分（1-10 整数）。

分析内容:
{input}

分析结果:
{output}

评估维度:
1. 摘要是否准确凝练，能否独立传达核心信息
2. 标签是否精确匹配内容
3. 相关性评分是否合理
4. 分类是否恰当

只返回 JSON:
{{"score": 8, "reason": "一句话理由"}}
{{"score": 8, "reason": "一句话理由"}}"""


# ── 工具函数 ───────────────────────────────────────────────────────────────


def _run_analysis(input_text: str) -> dict[str, Any]:
    """调用 LLM 分析单条输入，返回解析后的 dict。"""
    prompt = _ANALYZE_PROMPT.format(input=input_text)
    text, _usage = chat(prompt, system="你是一个 AI 技术分析专家。只返回 JSON，不要解释。", temperature=0.2)
    text = text.strip()
    if (start := text.find("{")) >= 0 and (end := text.rfind("}")) >= 0:
        text = text[start : end + 1]
    return json.loads(text)


def _check_expected(result: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """根据预期条件检查分析结果，返回失败信息列表。"""
    failures: list[str] = []

    for key, condition in expected.items():
        if key == "no_crash":
            continue

        if key == "summary_len":
            actual = len(result.get("summary", ""))
        elif key == "tags_contain":
            tags = result.get("tags", [])
            if callable(condition):
                if not condition(tags):
                    failures.append(f"tags 不满足条件: {tags}")
            continue
        else:
            actual = result.get(key)

        if callable(condition):
            if not condition(actual):
                failures.append(f"{key} 不满足自定义条件: {actual}")
        elif isinstance(condition, tuple):
            op, value = condition
            if actual is None:
                failures.append(f"{key} 值为 None")
            elif op == ">=" and actual < value:
                failures.append(f"{key} 应 >= {value}, 实际 {actual}")
            elif op == "<=" and actual > value:
                failures.append(f"{key} 应 <= {value}, 实际 {actual}")
            elif op == "==" and actual != value:
                failures.append(f"{key} 应为 {value}, 实际 {actual}")

    return failures


# ── 测试 1: 本地结构验证（不调 LLM）──────────────────────────────────────


class TestEvalCases:
    """验证 EVAL_CASES 用例结构是否正确。"""

    def test_eval_cases_count(self):
        """至少 3 个用例。"""
        assert len(EVAL_CASES) >= 3, f"EVAL_CASES 至少需要 3 个用例，当前 {len(EVAL_CASES)}"

    def test_eval_cases_structure(self):
        """每个用例包含必需字段。"""
        required = {"name", "input", "expected"}
        for i, case in enumerate(EVAL_CASES):
            missing = required - set(case.keys())
            assert not missing, f"用例 {i} ({case.get('name', '?')}) 缺少字段: {missing}"

    def test_all_cases_have_name(self):
        """所有用例有非空 name。"""
        for case in EVAL_CASES:
            assert case.get("name", "").strip(), "用例 name 不能为空"


# ── 测试 2: LLM 分析评估（标记 slow）──────────────────────────────────────


@pytest.mark.slow
class TestLLMAnalysis:
    """调用 LLM 对 EVAL_CASES 做分析并验证结果。"""

    @pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["name"])
    def test_analysis(self, case):
        """对每个用例调用 LLM 分析并验证预期。"""
        result = _run_analysis(case["input"])

        logger.info("[%s] result: %s", case["name"],
                    json.dumps(result, ensure_ascii=False)[:120])

        failures = _check_expected(result, case["expected"])
        assert not failures, (
            f"[{case['name']}] 检查失败:\n" + "\n".join(f"  - {f}" for f in failures)
        )

    def test_no_crash_on_empty(self):
        """空输入不崩溃。"""
        try:
            _run_analysis("标题: test\n来源: test\n描述: test")
        except Exception as e:
            pytest.fail(f"空输入不应崩溃: {e}")

    def test_returns_valid_json(self):
        """LLM 返回合法的 JSON 结构。"""
        result = _run_analysis(
            "标题: LangChain v1.0 发布\n"
            "来源: github\n"
            "描述: LangChain 发布 v1.0 正式版，新增 Agent 编排引擎。"
        )
        assert "summary" in result, "缺少 summary"
        assert "relevance" in result, "缺少 relevance"
        assert "tags" in result, "缺少 tags"
        assert isinstance(result["tags"], list), "tags 应为列表"


# ── 测试 3: LLM-as-Judge（标记 slow）───────────────────────────────────────


@pytest.mark.slow
class TestLLMJudge:
    """LLM 自评：让 LLM 对分析结果打分。"""

    _JUDGE_CASES = [
        {
            "input": (
                "标题: Anthropic发布Claude 4，支持200K上下文窗口\n"
                "来源: anthropic\n"
                "描述: Claude 4将上下文窗口扩展至200K tokens，"
                "在长文档理解和代码生成任务上显著提升，API延迟降低50%。"
            ),
        },
    ]

    @pytest.mark.parametrize("case", _JUDGE_CASES)
    def test_judge_score(self, case):
        """LLM-as-Judge: 自评分析结果，分数应 >= 5。"""
        analysis = _run_analysis(case["input"])

        judge_prompt = _JUDGE_PROMPT.format(
            input=case["input"],
            output=json.dumps(analysis, ensure_ascii=False, indent=2),
        )

        text, _usage = chat(
            judge_prompt,
            system="你是一个客观的评估专家。只返回 JSON，不要解释。",
            temperature=0.1,
        )
        text = text.strip()
        if (start := text.find("{")) >= 0 and (end := text.rfind("}")) >= 0:
            text = text[start : end + 1]
        judge_result = json.loads(text)

        score = int(judge_result.get("score", 0))
        reason = judge_result.get("reason", "")

        logger.info("[Judge] score=%d, reason=%s", score, reason)
        assert score >= 5, f"LLM-as-Judge 分数应 >= 5，实际 {score}: {reason}"
