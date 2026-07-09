"""
workflows/model_client.py — LLM 调用封装（thin wrapper）

对 pipeline/model_client.py 做轻量适配：
  - chat() 返回 (text, usage) 元组
  - chat_json() 返回 (parsed_json, usage) 元组
  - accumulate_usage() 累加 token 统计到 cost_tracker
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.model_client import chat as _raw_chat  # noqa: E402

# DeepSeek 定价（$/1K tokens）
_PROMPT_COST_PER_1K = 0.001
_COMPLETION_COST_PER_1K = 0.002


def chat(
    prompt: str,
    system: str = "你是一个 AI 助手。",
    temperature: float = 0.7,
) -> tuple[str, dict[str, int]]:
    """调用 LLM，返回 (text, usage) 元组。"""
    result = _raw_chat(prompt, system=system, temperature=temperature)
    return result["content"], result["usage"]


def chat_json(
    prompt: str,
    system: str = "你是一个 JSON 输出专家。",
    temperature: float = 0.7,
) -> tuple[dict[str, Any], dict[str, int]]:
    """调用 LLM 并解析 JSON，返回 (parsed_dict, usage) 元组。"""
    text, usage = chat(
        prompt,
        system=system + "\n只返回 JSON，不要包含任何其他文本。",
        temperature=temperature,
    )
    text = text.strip()
    if (start := text.find("{")) >= 0 and (end := text.rfind("}")) >= 0:
        text = text[start : end + 1]
    text = text.replace("\x00", "").replace("\x08", "").replace("\x0c", "")
    return json.loads(text), usage


def accumulate_usage(tracker: dict[str, Any], usage: dict[str, int]) -> None:
    """将单次调用的 token 用量累加到 cost_tracker 中。"""
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    tracker["total_prompt_tokens"] = tracker.get("total_prompt_tokens", 0) + pt
    tracker["total_completion_tokens"] = tracker.get("total_completion_tokens", 0) + ct
    cost = pt * _PROMPT_COST_PER_1K / 1000 + ct * _COMPLETION_COST_PER_1K / 1000
    tracker["estimated_cost_usd"] = round(
        tracker.get("estimated_cost_usd", 0.0) + cost, 6
    )
