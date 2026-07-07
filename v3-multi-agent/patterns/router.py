"""
patterns/router.py — Router 路由模式

两层意图分类 → 三种意图分发：
  第一层：关键词快速匹配（零成本，不调 LLM）
  第二层：LLM 分类兜底（处理模糊意图）

意图 → 处理器：
  - github_search   → GitHub Search API (urllib.request)
  - knowledge_query → 本地 knowledge/articles/ 检索
  - general_chat    → LLM 直接回答

依赖: pipeline/model_client.py 的 chat() 和 chat_json()
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "knowledge" / "articles"

sys.path.insert(0, str(ROOT))
from pipeline.model_client import chat as _raw_chat  # noqa: E402

logger = logging.getLogger(__name__)


# ── 模型调用封装 ─────────────────────────────────────────────────────────

def chat(prompt: str, system: str = "你是一个 AI 助手。") -> tuple[str, dict[str, int]]:
    """调用 LLM，返回 (text, usage) 元组。"""
    result = _raw_chat(prompt, system=system)
    return result["content"], result["usage"]


def chat_json(prompt: str, system: str = "你是一个 JSON 输出专家。") -> dict[str, Any]:
    """调用 LLM，解析返回的 JSON。"""
    text, _ = chat(prompt, system=system + "\n只返回 JSON，不要包含任何其他文本。")
    text = text.strip()
    if (start := text.find("{")) >= 0 and (end := text.rfind("}")) >= 0:
        text = text[start:end + 1]
    text = text.replace("\x00", "").replace("\x08", "").replace("\x0c", "")
    return json.loads(text)


# ── 第一层：关键词快速匹配 ─────────────────────────────────────────────

INTENT_KEYWORDS: dict[str, list[str]] = {
    "github_search": [
        "github", "github.", "仓库", "开源项目", "repo", "repos",
        "搜索github", "找项目", "github上", "在github", "star数",
        "开源库", "github搜索",
    ],
    "knowledge_query": [
        "知识库", "已收录", "我们库里", "本地文章", "查一下",
        "我们的文章", "统计", "热门标签", "知识库里有",
    ],
}


def classify_by_keyword(query: str) -> str | None:
    """第一层：关键词匹配，返回意图名或 None。大小写不敏感。"""
    q = query.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                return intent
    return None


# ── 第二层：LLM 分类兜底 ───────────────────────────────────────────────

_CLASSIFY_PROMPT = """根据用户输入判断意图，只返回 JSON：

{"intent": "github_search | knowledge_query | general_chat"}

- github_search: 用户想搜索 GitHub 上的开源项目或仓库
- knowledge_query: 用户想查本地知识库中已收录的内容
- general_chat: 其他所有情况

用户输入: {query}"""


def classify_by_llm(query: str) -> str:
    """第二层：LLM 分类兜底。"""
    try:
        result = chat_json(_CLASSIFY_PROMPT.format(query=query))
        intent = result.get("intent", "general_chat")
        return intent if intent in ("github_search", "knowledge_query", "general_chat") else "general_chat"
    except Exception:
        return "general_chat"


# ── 意图分类统一入口 ──────────────────────────────────────────────────

def classify_intent(query: str) -> str:
    """两层分类：关键词 → LLM 兜底。"""
    intent = classify_by_keyword(query)
    return intent if intent else classify_by_llm(query)


# ── 处理器：github_search ─────────────────────────────────────────────

_GITHUB_API = "https://api.github.com/search/repositories"
_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "v3-router/1.0",
}
# 尝试从环境变量读 token，没有则使用匿名访问（限速 10 次/分钟）
import os as _os
_token = _os.getenv("GITHUB_TOKEN", "")
if _token and _token != "ghp_your-github-token":
    _GITHUB_HEADERS["Authorization"] = f"token {_token}"


# ── 搜索词清洗 ────────────────────────────────────────────────────────────

_SEARCH_STOP_TOKENS = {
    "搜索", "找一下", "有没有", "最热门", "上最", "请帮", "帮我",
    "上", "的", "了", "在", "是", "有", "我们", "你", "我",
    "search", "find", "lookup", "github上", "在github",
    "知识库里", "里面", "关于", "相关", "内容", "什么",
    "github", "查找", "帮我找", "请问",
}
_SEARCH_STOP_TOKENS.update(kw.lower() for keywords in INTENT_KEYWORDS.values() for kw in keywords)


def _clean_search_terms(query: str) -> str:
    """从自然语言查询中提取有效搜索词（去停用词 + 过滤纯中文）。"""
    tokens = query.lower().split()
    cleaned = [t for t in tokens if t not in _SEARCH_STOP_TOKENS and len(t) >= 2]
    # GitHub Search API 主要索引英文，过滤纯中文 token
    cleaned = [t for t in cleaned if any(c.isascii() and c.isalpha() for c in t)]
    return " ".join(cleaned) if cleaned else query


def handle_github_search(query: str) -> str:
    """调用 GitHub Search API 搜索仓库。query 使用 urllib.parse.quote 编码。"""
    search_term = _clean_search_terms(query)
    encoded = urllib.parse.quote(search_term)
    url = f"{_GITHUB_API}?q={encoded}&sort=stars&order=desc&per_page=5"

    try:
        req = urllib.request.Request(url, headers=_GITHUB_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        return f"GitHub API 错误: {e.code} — {body}"
    except Exception as e:
        return f"GitHub 搜索失败: {e}"

    items = data.get("items", [])
    if not items:
        return f"未找到与「{query}」相关的 GitHub 仓库。"

    lines = [f'GitHub 搜索「{query}」— 共 {data.get("total_count", 0)} 个仓库，Top {len(items)}:']
    for i, repo in enumerate(items, 1):
        desc = (repo.get("description") or "无描述")[:120]
        lines.append(
            f"\n{i}. **{repo['full_name']}** ⭐{repo['stargazers_count']}\n"
            f"   {desc}\n"
            f"   🔗 {repo['html_url']}"
        )
    return "\n".join(lines)


# ── 处理器：knowledge_query ───────────────────────────────────────────

def _load_articles() -> list[dict[str, Any]]:
    """加载 knowledge/articles/ 下所有 JSON 文件。"""
    articles: list[dict[str, Any]] = []
    if not ARTICLES_DIR.exists():
        return articles
    for f in sorted(ARTICLES_DIR.iterdir()):
        if f.suffix != ".json" or f.name == "index.json":
            continue
        try:
            with open(f, "r", encoding="utf-8") as fh:
                articles.append(json.load(fh))
        except (json.JSONDecodeError, IOError):
            pass
    return articles


def handle_knowledge_query(query: str) -> str:
    """从本地知识库检索文章（分词 + 标题/摘要/标签评分排序）。"""
    articles = _load_articles()
    if not articles:
        return "知识库中没有文章，请先运行流水线采集数据。"

    # 分词：按空格切分，过滤过短的 token
    tokens = [t.lower() for t in query.split() if len(t) >= 2]

    scored: list[tuple[int, dict[str, Any]]] = []
    for a in articles:
        score = 0
        title = (a.get("title") or "").lower()
        summary = (a.get("summary") or "").lower()
        tags = [t.lower() for t in a.get("tags", [])]
        for token in tokens:
            if token in title:
                score += 10
            if token in summary:
                score += 5
            if any(token in t for t in tags):
                score += 3
        if score > 0:
            scored.append((score, a))

    scored.sort(key=lambda x: -x[0])

    if not scored:
        return f'知识库中未找到与「{query}」相关的内容。'

    lines = [f'知识库检索「{query}」— 匹配 {len(scored)} 篇:']
    for _, a in scored[:5]:
        tags_str = ", ".join(a.get("tags", []))
        lines.append(
            f"\n📄 [{a.get('id', '-')}] **{a['title']}** (评分: {a.get('score', '-')})\n"
            f"   {a.get('summary', '无摘要')[:120]}\n"
            f"   标签: {tags_str} | 来源: {a.get('source', '-')}"
        )
    return "\n".join(lines)


# ── 处理器：general_chat ──────────────────────────────────────────────

def handle_general_chat(query: str) -> str:
    """直接调用 LLM 回答。"""
    text, _usage = chat(query)
    return text


# ── 路由入口 ─────────────────────────────────────────────────────────

_HANDLERS = {
    "github_search": handle_github_search,
    "knowledge_query": handle_knowledge_query,
    "general_chat": handle_general_chat,
}


def route(query: str) -> str:
    """统一入口：意图识别 → 分发 → 返回结果。"""
    if not query or not query.strip():
        return "请提供查询内容。"

    intent = classify_intent(query.strip())
    logger.info("路由: [%s] → %s", query[:50], intent)

    handler = _HANDLERS.get(intent, handle_general_chat)
    try:
        return handler(query)
    except Exception as e:
        logger.exception("处理器异常: %s", e)
        return f"处理失败 ({intent}): {type(e).__name__}: {e}"


# ── 测试入口 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Router 路由模式测试")
    parser.add_argument("query", nargs="?", default="", help="查询内容")
    parser.add_argument("--intent-only", action="store_true", help="仅显示意图分类结果")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.query:
        intent = classify_intent(args.query)
        print(f"[意图: {intent}]\n")
        if not args.intent_only:
            print(route(args.query))
    else:
        tests = [
            "搜索 GitHub 上最热门的 AI agent 项目",
            "知识库里有没有关于 Dify 的内容",
            "解释一下什么是 RAG 检索增强生成",
            "github trending 本周热门项目",
            "最近有什么新的 LLM 框架发布",
        ]
        for t in tests:
            intent = classify_intent(t)
            print(f"Q: {t}")
            print(f"   → 意图: {intent}")
            if not args.intent_only:
                result = route(t)
                print(f"   → 结果: {result[:200]}...")
            print()
