#!/usr/bin/env python3
"""
知识库 MCP Server — 让 AI 工具通过 MCP 搜索和查询本地知识库文章。

提供 3 个工具：
  - search_articles: 按关键词搜索文章
  - get_article: 按 ID 获取文章详情
  - knowledge_stats: 查看知识库统计信息

运行方式：
    python3 mcp_knowledge_server.py

配置到 OpenCode（opencode.json）：
    {
      "mcpServers": {
        "knowledge": {
          "command": "python3",
          "args": ["mcp_knowledge_server.py"]
        }
      }
    }
"""

import json
import sys
from pathlib import Path

# ── 知识库路径 ──────────────────────────────────────────────────────────────

ARTICLES_DIR = Path(__file__).parent / "knowledge" / "articles"


def load_articles() -> list[dict]:
    """加载所有文章 JSON 文件。"""
    articles = []
    if not ARTICLES_DIR.exists():
        return articles
    for f in sorted(ARTICLES_DIR.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                articles.append(json.load(fh))
        except (json.JSONDecodeError, OSError):
            continue
    return articles


# ── 工具实现 ────────────────────────────────────────────────────────────────

def search_articles(keyword: str, limit: int = 5) -> list[dict]:
    """按关键词搜索文章（匹配标题和摘要）。"""
    keyword_lower = keyword.lower()
    results = []
    for article in load_articles():
        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        tags = str(article.get("tags", "")).lower()
        if keyword_lower in title or keyword_lower in summary or keyword_lower in tags:
            results.append({
                "id": article.get("id", ""),
                "title": article.get("title", ""),
                "score": article.get("score", ""),
                "tags": article.get("tags", []),
                "summary": article.get("summary", "")[:120] + "...",
            })
    return results[:limit]


def get_article(article_id: str) -> dict | None:
    """按 ID 获取文章完整内容。"""
    for article in load_articles():
        if article.get("id") == article_id:
            return article
    return None


def knowledge_stats() -> dict:
    """返回知识库统计信息。"""
    articles = load_articles()
    sources = {}
    tags_count = {}
    for a in articles:
        src = a.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1
        for tag in a.get("tags", []):
            if isinstance(tag, str):
                tags_count[tag] = tags_count.get(tag, 0) + 1
    top_tags = sorted(tags_count.items(), key=lambda x: -x[1])[:10]
    return {
        "total_articles": len(articles),
        "sources": sources,
        "top_tags": top_tags,
    }


# ── MCP 协议实现（JSON-RPC 2.0 over stdio） ────────────────────────────────

TOOLS = [
    {
        "name": "search_articles",
        "description": "按关键词搜索知识库文章，匹配标题、摘要和标签",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词，如 agent、RAG、LLM",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量上限，默认 5",
                    "default": 5,
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "按文章 ID 获取完整内容",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "文章 ID，例如 github-20260704-001",
                },
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "查看知识库统计信息：文章总数、来源分布、热门标签",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def handle_request(request: dict) -> dict:
    """处理单个 JSON-RPC 请求。"""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "knowledge-base",
                    "version": "1.0.0",
                },
            },
        }

    if method == "notifications/initialized":
        return None  # 通知无需响应

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        if tool_name == "search_articles":
            result = search_articles(
                keyword=args.get("keyword", ""),
                limit=args.get("limit", 5),
            )
            text = json.dumps(result, ensure_ascii=False, indent=2)
        elif tool_name == "get_article":
            result = get_article(article_id=args.get("article_id", ""))
            text = json.dumps(result, ensure_ascii=False, indent=2) if result else "文章未找到"
        elif tool_name == "knowledge_stats":
            result = knowledge_stats()
            text = json.dumps(result, ensure_ascii=False, indent=2)
        else:
            text = f"未知工具: {tool_name}"

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": text}],
            },
        }

    # 未知方法
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    """MCP Server 主循环：从 stdin 读 JSON-RPC，向 stdout 写响应。"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
