#!/usr/bin/env python3
"""知识条目 5 维度质量评价工具。

用法:
    python hooks/check_quality.py <file.json> [file2.json ...]
    python hooks/check_quality.py knowledge/articles/*.json
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── 常量定义 ──────────────────────────────────────────────────────────────

VALID_STATUSES = frozenset({"draft", "review", "published", "archived"})
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*-\d{8}-\d{3}$", re.IGNORECASE)
URL_PATTERN = re.compile(r"^https?://\S+$")

STANDARD_TAGS: frozenset = frozenset({
    "ai-agents", "multi-agent", "agent-orchestration", "agent-harness",
    "coding-agent", "browser-agent", "security-agent", "trading-agent",
    "mcp", "mcp-server", "mcp-protocol", "model-context-protocol",
    "rag", "llm", "large-language-model", "small-language-model",
    "machine-learning", "deep-learning", "reinforcement-learning",
    "multimodal", "video-understanding", "computer-vision", "nlp",
    "natural-language-processing", "speech-recognition", "tts",
    "ai-security", "penetration-testing", "cybersecurity",
    "openai", "codex", "claude", "gemini", "deepseek", "qwen",
    "fine-tuning", "inference", "transformer", "diffusion",
    "vector-database", "embedding", "semantic-search",
    "python", "typescript", "javascript", "rust", "go",
    "agent-tools", "agent-optimization", "agent-infrastructure",
    "ai-education", "beginner", "tutorial", "course",
    "finance", "trading", "crypto", "quantitative",
    "visual-framework", "low-code", "no-code",
    "reasoning", "planning", "tool-use", "function-calling",
    "evaluation", "benchmark", "testing", "observability",
    "privacy", "safety", "alignment", "ethics",
    "design-system", "agent-ready", "ui", "ux",
    "api-design", "sdk", "cli", "plugin",
})

TECH_KEYWORDS = [
    "transformer", "attention", "neural network", "deep learning",
    "machine learning", "reinforcement learning", "language model",
    "llm", "gpt", "diffusion", "agent", "rag", "mcp",
    "fine-tuning", "embedding", "vector database",
    "pytorch", "tensorflow", "multimodal", "computer vision",
    "nlp", "natural language", "inference", "quantization",
    "distillation", "prompt engineering", "few-shot",
    "retrieval", "knowledge graph", "reasoning",
]

BUZZWORDS_CN = [
    "赋能", "抓手", "闭环", "打通", "全链路",
    "底层逻辑", "颗粒度", "对齐", "拉通", "沉淀", "强大的",
]

BUZZWORDS_EN = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "state-of-the-art", "paradigm shift", "disruptive", "next-generation",
    "world-class", "best-in-class", "industry-leading",
]

# ── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    detail: str = ""


@dataclass
class QualityReport:
    file: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    total: float = 0.0
    max_total: float = 100.0
    grade: str = "F"

    def compute_grade(self) -> str:
        if self.total >= 80:
            return "A"
        if self.total >= 60:
            return "B"
        return "C"


# ── 各维度评分 ────────────────────────────────────────────────────────────

def score_summary(item: dict) -> DimensionScore:
    MAX = 25.0
    summary = item.get("summary", "")
    if not isinstance(summary, str) or not summary:
        return DimensionScore("摘要质量", 0.0, MAX, "缺少摘要")

    length = len(summary)
    if length < 20:
        return DimensionScore("摘要质量", 0.0, MAX, f"摘要仅 {length} 字，不足 20 字")

    if length >= 50:
        base = 15.0
        detail = f"长度 {length} 字(满分)"
    else:
        base = 10.0 + 5.0 * (length - 20) / 30.0
        detail = f"长度 {length} 字(基本分)"

    summary_lower = summary.lower()
    found_keywords = [kw for kw in TECH_KEYWORDS if kw in summary_lower]
    bonus = min(len(found_keywords) * 2, 10.0)
    if bonus > 0:
        detail += f" + {len(found_keywords)} 个技术关键词(+{bonus:.0f})"

    total = min(base + bonus, MAX)
    return DimensionScore("摘要质量", round(total, 1), MAX, detail)


def score_depth(item: dict) -> DimensionScore:
    MAX = 25.0
    raw = item.get("score")
    if not isinstance(raw, (int, float)):
        return DimensionScore("技术深度", 0.0, MAX, "缺少 score 字段")

    if raw < 1 or raw > 10:
        return DimensionScore("技术深度", 0.0, MAX, f"score {raw} 超出 1-10 范围")

    s = raw * 2.5
    return DimensionScore("技术深度", round(s, 1), MAX, f"score={raw} → {s:.1f}")


def score_format(item: dict) -> DimensionScore:
    MAX = 20.0
    checks: list[tuple[str, bool]] = []

    ok_id = bool(isinstance(item.get("id"), str) and item["id"])
    checks.append(("id", ok_id))

    ok_title = bool(isinstance(item.get("title"), str) and item["title"])
    checks.append(("title", ok_title))

    raw_url = item.get("source_url")
    ok_url = bool(isinstance(raw_url, str) and URL_PATTERN.match(raw_url))
    checks.append(("source_url", ok_url))

    raw_status = item.get("status")
    ok_status = bool(isinstance(raw_status, str) and raw_status in VALID_STATUSES)
    checks.append(("status", ok_status))

    ts_fields = ["collected_at", "updated_at", "created_at"]
    ok_ts = any(
        isinstance(item.get(f), str) and bool(item[f])
        for f in ts_fields
    )
    checks.append(("timestamp", ok_ts))

    score = sum(4 for _, ok in checks if ok) * 1.0
    passed = [name for name, ok in checks if ok]
    failed = [name for name, ok in checks if not ok]
    parts = []
    if passed:
        parts.append(f"✓ {', '.join(passed)}")
    if failed:
        parts.append(f"✗ {', '.join(failed)}")

    return DimensionScore("格式规范", score, MAX, "; ".join(parts))


def score_tags(item: dict) -> DimensionScore:
    MAX = 15.0
    tags = item.get("tags")
    if not isinstance(tags, list) or len(tags) == 0:
        return DimensionScore("标签精度", 0.0, MAX, "无标签")

    valid_count = sum(1 for t in tags if isinstance(t, str) and t in STANDARD_TAGS)
    invalid_count = sum(1 for t in tags if isinstance(t, str) and t not in STANDARD_TAGS)
    total = len(tags)

    if total <= 3:
        base = 15.0
    elif total <= 5:
        base = 10.0
    else:
        base = 5.0

    deduction = invalid_count * 5.0
    score = max(base - deduction, 0.0)

    parts = [f"{total} 个标签, {valid_count} 合法"]
    if invalid_count:
        parts.append(f"{invalid_count} 非法")
    parts.append(f"基础 {base:.0f}")
    if deduction > 0:
        parts.append(f"扣 {deduction:.0f}")

    return DimensionScore("标签精度", round(score, 1), MAX, ", ".join(parts))


def score_buzzwords(item: dict) -> DimensionScore:
    MAX = 15.0
    summary = item.get("summary", "")
    title = item.get("title", "")
    if not isinstance(summary, str):
        summary = ""
    if not isinstance(title, str):
        title = ""

    text_cn = summary + title
    text_en = (summary + " " + title).lower()

    found: list[str] = []
    for bw in BUZZWORDS_CN:
        if bw in text_cn:
            found.append(bw)
    for bw in BUZZWORDS_EN:
        if bw in text_en:
            found.append(bw)

    if not found:
        return DimensionScore("空洞词检测", MAX, MAX, "无空洞词 ✓")

    deduction = min(len(found) * 5.0, MAX)
    score = MAX - deduction
    return DimensionScore(
        "空洞词检测",
        round(score, 1),
        MAX,
        f"发现 {len(found)} 个空洞词: {', '.join(found)}",
    )


# ── 核心流程 ──────────────────────────────────────────────────────────────

ALL_SCORERS = [
    score_summary,
    score_depth,
    score_format,
    score_tags,
    score_buzzwords,
]


def evaluate_entry(entry: dict) -> QualityReport:
    dims = [scorer(entry) for scorer in ALL_SCORERS]
    total = sum(d.score for d in dims)
    report = QualityReport(
        file="",
        dimensions=dims,
        total=round(total, 1),
        max_total=100.0,
    )
    report.grade = report.compute_grade()
    return report


def evaluate_file(filepath: Path) -> QualityReport | None:
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  [ERR] 读取失败: {e}", file=sys.stderr)
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [ERR] JSON 解析失败: {e}", file=sys.stderr)
        return None

    entries: list = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        items = data.get("items")
        entries = items if isinstance(items, list) else [data]

    if not entries:
        print(f"  [ERR] 无可评价的条目", file=sys.stderr)
        return None

    reports = [evaluate_entry(e) for e in entries]
    if len(reports) == 1:
        r = reports[0]
        r.file = str(filepath)
        return r

    dims = []
    total = 0.0
    for i in range(5):
        avg = sum(r.dimensions[i].score for r in reports) / len(reports)
        d = DimensionScore(
            name=reports[0].dimensions[i].name,
            score=round(avg, 1),
            max_score=reports[0].dimensions[i].max_score,
            detail=f"平均分 ({len(reports)} 条目)",
        )
        dims.append(d)
        total += avg

    report = QualityReport(
        file=str(filepath),
        dimensions=dims,
        total=round(total, 1),
        max_total=100.0,
    )
    report.grade = report.compute_grade()
    return report


# ── 进度条 ────────────────────────────────────────────────────────────────

def print_progress(current: int, total: int, bar_width: int = 30):
    fraction = current / total if total > 0 else 0
    filled = int(bar_width * fraction)
    bar = "█" * filled + "░" * (bar_width - filled)
    print(f"\r  进度: [{bar}] {fraction:>4.0%} ({current}/{total})", end="", file=sys.stderr)
    if current == total:
        print(file=sys.stderr)


# ── 路径解析 ──────────────────────────────────────────────────────────────

def resolve_paths(raw_args: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen = set()
    for arg in raw_args:
        if "*" in arg or "?" in arg:
            p = Path(arg)
            if p.is_absolute():
                expanded = list(p.parent.glob(p.name))
            else:
                expanded = list(Path().glob(arg))
        else:
            expanded = [Path(arg)]
        for p in expanded:
            resolved = p.resolve()
            if resolved not in seen:
                if p.exists():
                    seen.add(resolved)
                    paths.append(p)
                else:
                    print(f"  文件不存在: {p}", file=sys.stderr)
    return paths


# ── 输出 ──────────────────────────────────────────────────────────────────

DIM_ICONS = ["📝", "🔬", "📐", "🏷", "🚫"]


def print_report(report: QualityReport):
    grade_color = {"A": "A", "B": "B", "C": "C"}
    print(f"\n文件: {report.file}")
    for i, d in enumerate(report.dimensions):
        pct = d.score / d.max_score * 100 if d.max_score > 0 else 0
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(
            f"  {DIM_ICONS[i]} {d.name:<8} {d.score:>5.1f}/{d.max_score:<4.0f} "
            f"[{bar}]"
        )
        if d.detail:
            print(f"    └─ {d.detail}")
    print(f"  {'─' * 42}")
    print(f"  ★ 总分: {report.total:>5.1f}/100  等级: {grade_color[report.grade]}")
    print()


def print_summary(reports: list[QualityReport]):
    total = len(reports)
    a_count = sum(1 for r in reports if r.grade == "A")
    b_count = sum(1 for r in reports if r.grade == "B")
    c_count = sum(1 for r in reports if r.grade == "C")
    avg = sum(r.total for r in reports) / total if total else 0.0

    print("=" * 50)
    print("  质量评价汇总")
    print("=" * 50)
    print(f"  评价文件: {total}")
    print(f"  A 级:     {a_count}")
    print(f"  B 级:     {b_count}")
    print(f"  C 级:     {c_count}")
    print(f"  平均分:   {avg:.1f}")
    print("=" * 50)


# ── 主入口 ────────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if sys.argv[1:] and sys.argv[1] in ("-h", "--help") else 1

    filepaths = resolve_paths(sys.argv[1:])
    if not filepaths:
        print("错误: 未找到可评价的 JSON 文件", file=sys.stderr)
        return 1

    reports: list[QualityReport] = []
    n = len(filepaths)

    for i, fp in enumerate(filepaths):
        print_progress(i, n)
        report = evaluate_file(fp)
        if report is not None:
            reports.append(report)
        print_progress(i + 1, n)

    print()
    for r in reports:
        print_report(r)

    print_summary(reports)

    has_c = any(r.grade == "C" for r in reports)
    return 1 if has_c else 0


if __name__ == "__main__":
    sys.exit(main())
