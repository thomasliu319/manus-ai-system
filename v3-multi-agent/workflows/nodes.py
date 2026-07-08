"""
workflows/nodes.py — LangGraph 工作流 5 个节点函数

节点调用链：
  collect → analyze → organize → review → (passed?) → save
                                    ↑                       │
                                    └── organize ←──────────┘ (retry)

每个节点是纯函数: KBState → dict（部分状态更新）
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
sys.path.insert(0, str(ROOT))

from workflows.state import KBState  # noqa: E402
from workflows.model_client import (  # noqa: E402
    accumulate_usage,
    chat,
    chat_json,
)

logger = logging.getLogger(__name__)

# ── GitHub API 配置 ────────────────────────────────────────────────────────

_GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "v3-workflow/1.0",
}

import os as _os  # noqa: E402

_token = _os.getenv("GITHUB_TOKEN", "")
if _token and _token not in ("ghp_your-github-token", ""):
    _GITHUB_HEADERS["Authorization"] = f"token {_token}"


# ── Prompt 模板 ─────────────────────────────────────────────────────────────

_ANALYZE_SYSTEM = "你是一个 AI 技术分析专家。请返回严格 JSON，不要包含任何解释。"

_ANALYZE_PROMPT = """分析以下内容，返回 JSON：

标题: {title}
来源: {source}
描述: {description}

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

_FIX_SYSTEM = _ANALYZE_SYSTEM

_FIX_PROMPT = """根据审核反馈修改以下知识条目，返回 JSON。

条目:
{article}

审核反馈: {feedback}

返回格式与原始条目相同，仅修改有问题的部分。"""

_REVIEW_SYSTEM = "你是一个严格的知识质量审核专家。只返回 JSON，不要解释。"

_REVIEW_PROMPT = """审核以下知识条目列表，从四个维度评分（各 0-1）:

1. summary_quality（摘要质量）: 摘要是否准确凝练，能否独立传达核心信息
2. tag_accuracy（标签准确）: 标签是否精确匹配内容主体
3. category_fit（分类合理）: 分类是否符合内容领域
4. consistency（一致性）: 摘要、标签、分类之间是否自洽

条目:
{articles}

返回 JSON:
{{"passed": true/false, "overall_score": 0-1, "feedback": "审核意见", "scores": {{"summary_quality": 0-1, "tag_accuracy": 0-1, "category_fit": 0-1, "consistency": 0-1}}}}

overall_score 取四个维度最低分。passed 为 true 当 overall_score >= 0.6。未通过时 feedback 必须给出具体改进方向。"""


# ── Node 1: collect_node ───────────────────────────────────────────────────

def collect_node(state: KBState) -> dict[str, Any]:
    """
    采集节点：调用 GitHub Search API 获取 AI 相关仓库。

    Returns:
        {"sources": list[dict]} — 采集到的原始数据
    """
    print("[CollectNode] 开始采集 GitHub 仓库...")

    query = "ai+agent+llm+stars:>100+pushed:>2026-06-01"
    url = f"{_GITHUB_SEARCH_URL}?q={query}&sort=stars&order=desc&per_page=5"

    try:
        req = urllib.request.Request(url, headers=_GITHUB_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        logger.error("GitHub API 调用失败: %s", e)
        return {"sources": []}

    items = data.get("items", [])
    sources: list[dict[str, Any]] = []
    for item in items:
        sources.append({
            "id": f"github-{datetime.now().strftime('%Y%m%d')}-{len(sources) + 1:03d}",
            "title": item["full_name"],
            "source": "github",
            "source_url": item["html_url"],
            "raw_description": (item.get("description") or "")[:300],
            "stars": item.get("stargazers_count", 0),
            "collected_at": datetime.now(timezone.utc).isoformat(),
        })

    print(f"[CollectNode] 采集完成: {len(sources)} 条")
    return {"sources": sources}


# ── Node 2: analyze_node ───────────────────────────────────────────────────

def analyze_node(state: KBState) -> dict[str, Any]:
    """
    分析节点：用 LLM 对每条数据生成中文摘要、标签、评分。

    Returns:
        {"analyses": list[dict], "cost_tracker": dict}
    """
    print("[AnalyzeNode] 开始分析...")

    sources: list[dict[str, Any]] = state.get("sources", [])
    if not sources:
        print("[AnalyzeNode] 无数据，跳过")
        return {"analyses": []}

    tracker: dict[str, Any] = state.get("cost_tracker", {})
    analyses: list[dict[str, Any]] = []

    for i, item in enumerate(sources):
        prompt = _ANALYZE_PROMPT.format(
            title=item["title"],
            source=item["source"],
            description=item.get("raw_description", "无描述"),
        )
        try:
            result, usage = chat_json(prompt, system=_ANALYZE_SYSTEM)
            accumulate_usage(tracker, usage)
            analysis = {
                **item,
                "summary": result.get("summary", ""),
                "relevance": float(result.get("relevance", 0.5)),
                "tags": result.get("tags", []),
                "category": result.get("category", "other"),
                "status": "analyzed",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }
            analyses.append(analysis)
            print(f"  [{i + 1}/{len(sources)}] {analysis['title'][:50]} "
                  f"relevance={analysis['relevance']:.2f}")
        except Exception as e:
            logger.warning("分析失败: %s — %s", item["title"], e)
            analyses.append({
                **item,
                "summary": item.get("raw_description", "")[:200],
                "relevance": 0.3,
                "tags": ["llm"],
                "category": "other",
                "status": "analysis_failed",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            })

    print(f"[AnalyzeNode] 分析完成: {len(analyses)} 条")
    return {"analyses": analyses, "cost_tracker": tracker}


# ── Node 3: organize_node ──────────────────────────────────────────────────

def organize_node(state: KBState) -> dict[str, Any]:
    """
    整理节点：过滤低分条目、按 source_url 去重、有反馈时 LLM 定向修正。

    Returns:
        {"articles": list[dict], "cost_tracker": dict}
    """
    print("[OrganizeNode] 开始整理...")

    analyses: list[dict[str, Any]] = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    tracker: dict[str, Any] = state.get("cost_tracker", {})

    # 1. 过滤低分（relevance < 0.6）
    filtered = [a for a in analyses if a.get("relevance", 0) >= 0.6]
    dropped = len(analyses) - len(filtered)
    if dropped:
        print(f"  ␡ 过滤低分: {dropped} 条")

    # 2. 按 source_url 去重
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for a in filtered:
        url = a.get("source_url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(a)
    dup = len(filtered) - len(unique)
    if dup:
        print(f"  ␡ 去重: {dup} 条")

    # 3. 有反馈时 LLM 定向修正
    articles: list[dict[str, Any]] = []
    if iteration > 0 and feedback:
        print(f"  ↻ 审核反馈: {feedback[:80]}...")
        for i, a in enumerate(unique):
            try:
                prompt = _FIX_PROMPT.format(
                    article=json.dumps(a, ensure_ascii=False, indent=2),
                    feedback=feedback,
                )
                result, usage = chat_json(prompt, system=_FIX_SYSTEM)
                accumulate_usage(tracker, usage)
                fixed = {**a, **result}
                fixed["status"] = "revised"
                fixed["revised_at"] = datetime.now(timezone.utc).isoformat()
                articles.append(fixed)
                print(f"  [{i + 1}/{len(unique)}] 已修正: {a['title'][:40]}")
            except Exception as e:
                logger.warning("修正失败: %s — %s", a["title"], e)
                articles.append(a)
    else:
        articles = unique
        for a in articles:
            a.setdefault("status", "organized")

    print(f"[OrganizeNode] 整理完成: {len(articles)} 条")
    return {"articles": articles, "cost_tracker": tracker}


# ── Node 4: review_node ────────────────────────────────────────────────────

def review_node(state: KBState) -> dict[str, Any]:
    """
    审核节点：LLM 四维度评分。iteration >= 2 强制通过。

    Returns:
        {"review_passed": bool, "review_feedback": str, "iteration": int, "cost_tracker": dict}
    """
    print("[ReviewNode] 开始审核...")

    articles: list[dict[str, Any]] = state.get("articles", [])
    iteration = state.get("iteration", 0)
    tracker: dict[str, Any] = state.get("cost_tracker", {})

    # 兜底：无条目直接通过
    if not articles:
        print("[ReviewNode] 无条目可审核，通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    # 超过重试上限，强制通过
    if iteration >= 2:
        print(f"[ReviewNode] iteration={iteration} >= 2，强制通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    # LLM 四维度评分
    try:
        prompt = _REVIEW_PROMPT.format(
            articles=json.dumps(articles, ensure_ascii=False, indent=2)
        )
        result, usage = chat_json(prompt, system=_REVIEW_SYSTEM)
        accumulate_usage(tracker, usage)

        overall = float(result.get("overall_score", 0))
        passed = bool(result.get("passed", overall >= 0.6))
        feedback = str(result.get("feedback", ""))
        scores = result.get("scores", {})

        print(f"  scores={json.dumps(scores, ensure_ascii=False)}")
        print(f"  overall={overall:.2f}  passed={passed}")
    except Exception as e:
        logger.warning("审核调用失败: %s，降级通过", e)
        overall = 0.6
        passed = True
        feedback = ""

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


# ── Node 5: save_node ──────────────────────────────────────────────────────

def save_node(state: KBState) -> dict[str, Any]:
    """
    保存节点：将 articles 写入 knowledge/articles/ 的 JSON 文件，更新 index.json。

    Returns:
        {} — 终端节点，无状态变更
    """
    print("[SaveNode] 开始保存...")

    articles: list[dict[str, Any]] = state.get("articles", [])
    if not articles:
        print("[SaveNode] 无条目可保存")
        return {}

    articles_dir = KNOWLEDGE_DIR / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)

    # 写入独立 JSON 文件
    for a in articles:
        fid = a.get("id", f"unknown-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        filepath = articles_dir / f"{fid}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(a, f, ensure_ascii=False, indent=2)

    # 更新 index.json
    index_file = articles_dir / "index.json"
    index: dict[str, Any] = {}
    if index_file.exists():
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                index = json.load(f)
        except json.JSONDecodeError:
            pass

    for a in articles:
        fid = a.get("id", "")
        if fid:
            index[fid] = {
                "title": a["title"],
                "source": a.get("source", ""),
                "source_url": a.get("source_url", ""),
                "relevance": a.get("relevance", 0),
                "tags": a.get("tags", []),
            }

    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"[SaveNode] 保存完成: {len(articles)} 文件, index {len(index)} 条")
    return {}


# ── 测试入口 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LangGraph 节点独立测试")
    parser.add_argument("--node", type=str, default="all", choices=["collect", "analyze", "organize", "review", "save", "all"])
    args = parser.parse_args()

    # 初始状态
    state: KBState = {
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "cost_tracker": {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "estimated_cost_usd": 0.0,
            "by_node": {},
        },
    }

    print("=" * 60)
    print("LangGraph 节点独立测试")
    print("=" * 60)

    def _merge(base: dict[str, Any], update: dict[str, Any]) -> None:
        for k, v in update.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                base[k].update(v)
            else:
                base[k] = v

    if args.node in ("collect", "all"):
        _merge(state, collect_node(state))

    if args.node in ("analyze", "all"):
        _merge(state, analyze_node(state))

    if args.node in ("organize", "all"):
        _merge(state, organize_node(state))
        # 模拟一次 review → 没通过 → 返回 feedback
        if state.get("articles"):
            _merge(state, review_node(state))
            if not state.get("review_passed"):
                # 模拟 feedback → 重新 organize
                state["review_feedback"] = "综合评分未达标，请改进摘要质量和标签准确性"
                _merge(state, organize_node(state))
                _merge(state, review_node(state))

    if args.node in ("save", "all"):
        if state.get("review_passed") or state.get("iteration", 0) >= 2:
            _merge(state, save_node(state))
        else:
            print("未通过审核，跳过保存")

    print(f"\n{'=' * 60}")
    print(f"流水线统计:")
    print(f"  采集: {len(state['sources'])} 条")
    print(f"  分析: {len(state['analyses'])} 条")
    print(f"  整理: {len(state['articles'])} 条")
    print(f"  审核: {'通过' if state['review_passed'] else '未通过'} (轮次: {state['iteration']})")
    print(f"  Token: {state['cost_tracker'].get('total_prompt_tokens', 0)} prompt "
          f"+ {state['cost_tracker'].get('total_completion_tokens', 0)} completion")
    print(f"  预估成本: ${state['cost_tracker'].get('estimated_cost_usd', 0):.6f}")
