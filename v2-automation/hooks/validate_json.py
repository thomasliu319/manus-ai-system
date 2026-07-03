#!/usr/bin/env python3
"""知识条目 JSON 校验工具。

用法:
    python hooks/validate_json.py <file.json> [file2.json ...]
    python hooks/validate_json.py knowledge/articles/*.json
"""

import json
import re
import sys
from pathlib import Path

REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = frozenset({"draft", "review", "published", "archived"})
VALID_AUDIENCES = frozenset({"beginner", "intermediate", "advanced"})

ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*-\d{8}-\d{3}$", re.IGNORECASE)
URL_PATTERN = re.compile(r"^https?://\S+$")


def extract_entries(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
        return [data]
    return []


def validate_id(item: dict, prefix: str) -> list[str]:
    errors = []
    raw = item.get("id")
    if not isinstance(raw, str):
        return errors
    if not ID_PATTERN.match(raw):
        errors.append(
            f"  {prefix}ID 格式错误: '{raw}' "
            f"(期望 {{source}}-{{YYYYMMDD}}-{{NNN}}, 如 github-20260317-001)"
        )
    return errors


def validate_status(item: dict, prefix: str) -> list[str]:
    errors = []
    raw = item.get("status")
    if not isinstance(raw, str):
        return errors
    if raw not in VALID_STATUSES:
        valid = "/".join(sorted(VALID_STATUSES))
        errors.append(f"  {prefix}status 值无效: '{raw}' (期望 {valid})")
    return errors


def validate_url(item: dict, prefix: str) -> list[str]:
    errors = []
    raw = item.get("source_url")
    if not isinstance(raw, str):
        return errors
    if not URL_PATTERN.match(raw):
        errors.append(f"  {prefix}source_url 格式错误: '{raw}' (期望 https://...)")
    return errors


def validate_summary(item: dict, prefix: str) -> list[str]:
    errors = []
    raw = item.get("summary")
    if not isinstance(raw, str):
        return errors
    if len(raw) < 20:
        errors.append(
            f"  {prefix}summary 长度不足: {len(raw)} 字符 (最少 20)"
        )
    return errors


def validate_tags(item: dict, prefix: str) -> list[str]:
    errors = []
    raw = item.get("tags")
    if not isinstance(raw, list):
        return errors
    if len(raw) == 0:
        errors.append(f"  {prefix}tags 为空 (至少 1 个标签)")
    for i, tag in enumerate(raw):
        if not isinstance(tag, str):
            errors.append(
                f"  {prefix}tags[{i}] 类型错误: 期望 str, 实际 {type(tag).__name__}"
            )
    return errors


def validate_optional_score(item: dict, prefix: str) -> list[str]:
    errors = []
    if "score" not in item:
        return errors
    raw = item["score"]
    if not isinstance(raw, (int, float)):
        errors.append(
            f"  {prefix}score 类型错误: 期望 int/float, 实际 {type(raw).__name__}"
        )
    elif raw < 1 or raw > 10:
        errors.append(f"  {prefix}score 超出范围: {raw} (期望 1-10)")
    return errors


def validate_optional_audience(item: dict, prefix: str) -> list[str]:
    errors = []
    if "audience" not in item:
        return errors
    raw = item["audience"]
    if raw not in VALID_AUDIENCES:
        valid = "/".join(sorted(VALID_AUDIENCES))
        errors.append(f"  {prefix}audience 值无效: '{raw}' (期望 {valid})")
    return errors


def validate_item(item: dict, prefix: str) -> list[str]:
    errors = []

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in item:
            errors.append(f"  {prefix}缺少必填字段: {field}")
        elif not isinstance(item[field], expected_type):
            errors.append(
                f"  {prefix}字段 '{field}' 类型错误: "
                f"期望 {expected_type.__name__}, "
                f"实际 {type(item[field]).__name__}"
            )

    errors.extend(validate_id(item, prefix))
    errors.extend(validate_status(item, prefix))
    errors.extend(validate_url(item, prefix))
    errors.extend(validate_summary(item, prefix))
    errors.extend(validate_tags(item, prefix))
    errors.extend(validate_optional_score(item, prefix))
    errors.extend(validate_optional_audience(item, prefix))

    return errors


def validate_file(filepath: Path) -> tuple[str, list[str]]:
    label = str(filepath)
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return label, [f"  文件读取失败: {e}"]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return label, [f"  JSON 解析错误: {e}"]

    entries = extract_entries(data)
    if not entries:
        return label, ["  JSON 内容为空或结构无法识别"]

    all_errors = []
    for idx, entry in enumerate(entries):
        prefix = f"[条目 {idx}]" if len(entries) > 1 else ""
        all_errors.extend(validate_item(entry, prefix))

    return label, all_errors


def resolve_paths(raw_args: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen = set()
    for arg in raw_args:
        expanded = list(Path().glob(arg)) if ("*" in arg or "?" in arg) else [Path(arg)]
        for p in expanded:
            resolved = p.resolve()
            if resolved not in seen:
                if p.exists():
                    seen.add(resolved)
                    paths.append(p)
                else:
                    print(f"  文件不存在: {p}", file=sys.stderr)
    return paths


def print_summary(results: list[tuple[str, list[str]]]) -> tuple[int, int]:
    total_files = len(results)
    passed = sum(1 for _, errs in results if not errs)
    failed = total_files - passed
    total_errors = sum(len(errs) for _, errs in results)

    print()
    print("=== 校验统计 ===")
    print(f"  文件总数: {total_files}")
    print(f"  通过:      {passed}")
    print(f"  失败:      {failed}")
    print(f"  错误总数:  {total_errors}")

    return failed, total_errors


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if sys.argv[1:] and sys.argv[1] in ("-h", "--help") else 1

    filepaths = resolve_paths(sys.argv[1:])
    if not filepaths:
        print("错误: 未找到可校验的 JSON 文件", file=sys.stderr)
        return 1

    results: list[tuple[str, list[str]]] = []
    for fp in filepaths:
        label, errors = validate_file(fp)
        results.append((label, errors))

    any_failed = False
    for label, errors in results:
        status = "PASS" if not errors else "FAIL"
        print(f"[{status}] {label}")
        for err in errors:
            print(err)
        if errors:
            any_failed = True
        print()

    failed_count, total_errors = print_summary(results)

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
