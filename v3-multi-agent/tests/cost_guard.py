"""CostGuard — 多 Agent 预算守卫（三重保护机制）

每记录一次 LLM 调用就累加成本，在：
  1. 接近预算 (>= alert_threshold) 时返回 warning
  2. 超出预算时抛出 BudgetExceededError
  3. 提供 get_report / save_report 用于事后审计
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 异常类 ─────────────────────────────────────────────────────────────────


class BudgetExceededError(RuntimeError):
    """预算超出异常"""

    def __init__(self, total_cost: float, budget: float):
        self.total_cost = total_cost
        self.budget = budget
        super().__init__(
            f"预算超限: 已花费 {total_cost:.4f} / 预算 {budget:.2f}"
        )


# ── 数据类 ─────────────────────────────────────────────────────────────────


@dataclass
class CostRecord:
    """单次 LLM 调用成本记录"""

    timestamp: str
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""


# ── 预算守卫 ───────────────────────────────────────────────────────────────


class CostGuard:
    """多 Agent 预算守卫，三重保护：记录 → 预警 → 超限"""

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ):
        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million

        self._records: list[CostRecord] = []
        self._total_prompt: int = 0
        self._total_completion: int = 0
        self._total_cost: float = 0.0

    # ── record ──────────────────────────────────────────────────────────

    def record(
        self,
        node_name: str,
        usage: dict[str, int],
        model: str = "",
    ) -> CostRecord:
        """记录一次 LLM 调用的 token 用量。

        Args:
            node_name: 调用节点名称（如 "analyze", "review"）
            usage: {"prompt_tokens": int, "completion_tokens": int}
            model: 模型名称，默认空字符串

        Returns:
            本次记录的 CostRecord
        """
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)

        cost = (
            pt * self.input_price_per_million / 1_000_000
            + ct * self.output_price_per_million / 1_000_000
        )

        record = CostRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            node_name=node_name,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_yuan=round(cost, 6),
            model=model,
        )

        self._records.append(record)
        self._total_prompt += pt
        self._total_completion += ct
        self._total_cost += cost

        return record

    # ── check ───────────────────────────────────────────────────────────

    def check(self) -> dict[str, Any]:
        """检查预算状态。

        Returns:
            {"status": "ok"|"warning"|"exceeded", "total_cost": float,
             "budget": float, "usage_ratio": float, "message": str}

        Raises:
            BudgetExceededError: 超出预算时
        """
        usage_ratio = self._total_cost / self.budget_yuan

        if self._total_cost >= self.budget_yuan:
            raise BudgetExceededError(self._total_cost, self.budget_yuan)

        if usage_ratio >= self.alert_threshold:
            return {
                "status": "warning",
                "total_cost": round(self._total_cost, 4),
                "budget": self.budget_yuan,
                "usage_ratio": round(usage_ratio, 4),
                "message": (
                    f"预算告警: 已使用 {usage_ratio:.1%} "
                    f"({self._total_cost:.4f} / {self.budget_yuan:.2f})"
                ),
            }

        return {
            "status": "ok",
            "total_cost": round(self._total_cost, 4),
            "budget": self.budget_yuan,
            "usage_ratio": round(usage_ratio, 4),
            "message": f"预算正常: 已使用 {usage_ratio:.1%}",
        }

    # ── get_report ──────────────────────────────────────────────────────

    def get_report(self) -> dict[str, Any]:
        """生成按节点分组的成本报告。

        Returns:
            {
                "summary": {...},
                "by_node": {
                    "analyze": {"prompt": int, "completion": int, "cost": float, "count": int},
                    ...
                }
            }
        """
        by_node: dict[str, dict[str, Any]] = {}
        for r in self._records:
            if r.node_name not in by_node:
                by_node[r.node_name] = {
                    "prompt": 0,
                    "completion": 0,
                    "cost": 0.0,
                    "count": 0,
                }
            b = by_node[r.node_name]
            b["prompt"] += r.prompt_tokens
            b["completion"] += r.completion_tokens
            b["cost"] = round(b["cost"] + r.cost_yuan, 6)
            b["count"] += 1

        return {
            "summary": {
                "total_prompt_tokens": self._total_prompt,
                "total_completion_tokens": self._total_completion,
                "total_cost_yuan": round(self._total_cost, 6),
                "budget_yuan": self.budget_yuan,
                "usage_ratio": round(self._total_cost / self.budget_yuan, 4),
                "call_count": len(self._records),
            },
            "by_node": by_node,
        }

    # ── save_report ─────────────────────────────────────────────────────

    def save_report(self, path: str | Path | None = None) -> Path:
        """保存成本报告到 JSON 文件。

        Args:
            path: 目标路径，默认 tests/cost_reports/{timestamp}.json

        Returns:
            写入的文件路径
        """
        if path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            report_dir = Path(__file__).resolve().parent / "cost_reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            path = report_dir / f"cost-{ts}.json"
        else:
            path = Path(path)

        report = self.get_report()
        report["generated_at"] = datetime.now(timezone.utc).isoformat()

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info("成本报告已保存: %s", path)
        return path

    # ── 属性 ────────────────────────────────────────────────────────────

    @property
    def total_prompt_tokens(self) -> int:
        return self._total_prompt

    @property
    def total_completion_tokens(self) -> int:
        return self._total_completion

    @property
    def total_cost_yuan(self) -> float:
        return round(self._total_cost, 6)

    @property
    def call_count(self) -> int:
        return len(self._records)


# ── 测试入口 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    logger.info("=" * 60)
    logger.info("CostGuard 预算守卫测试")
    logger.info("=" * 60)

    # ── 测试 1: 成本追踪正确性 ──
    logger.info("--- 测试 1: 成本追踪正确性 ---")

    guard = CostGuard(
        budget_yuan=5.0,
        alert_threshold=0.8,
        input_price_per_million=1.0,
        output_price_per_million=2.0,
    )

    guard.record("analyze", {"prompt_tokens": 500_000, "completion_tokens": 200_000})
    guard.record("review", {"prompt_tokens": 300_000, "completion_tokens": 100_000})

    assert guard.total_prompt_tokens == 800_000, \
        f"total_prompt_tokens 应为 800000，实际 {guard.total_prompt_tokens}"
    expected_cost = (800_000 * 1.0 + 300_000 * 2.0) / 1_000_000
    assert abs(guard.total_cost_yuan - expected_cost) < 0.001, \
        f"total_cost_yuan 应为 {expected_cost:.4f}，实际 {guard.total_cost_yuan}"
    logger.info("  total_prompt=%d, total_completion=%d, total_cost=%.4f",
                guard.total_prompt_tokens, guard.total_completion_tokens, guard.total_cost_yuan)
    logger.info("  通过")

    # ── 测试 2: 预算正常 (status=ok) ──
    logger.info("--- 测试 2: 预算正常 (status=ok) ---")

    result = guard.check()
    assert result["status"] == "ok", f"预期 ok，实际 {result['status']}"
    assert result["usage_ratio"] < 0.8, f"预期 usage_ratio < 0.8"
    logger.info("  status=%s, cost=%.4f, ratio=%.2f%%",
                result["status"], result["total_cost"], result["usage_ratio"] * 100)
    logger.info("  通过")

    # ── 测试 3: 预警触发 (status=warning) ──
    logger.info("--- 测试 3: 预警阈值触发 (status=warning) ---")

    guard.record("organize", {"prompt_tokens": 1_500_000, "completion_tokens": 600_000})

    result = guard.check()
    assert result["status"] == "warning", f"预期 warning，实际 {result['status']}"
    assert result["usage_ratio"] >= 0.8, f"预期 usage_ratio >= 0.8"
    logger.info("  status=%s, cost=%.4f, ratio=%.2f%%",
                result["status"], result["total_cost"], result["usage_ratio"] * 100)
    logger.info("  %s", result["message"])
    logger.info("  通过")

    # ── 测试 4: 超限异常 ──
    logger.info("--- 测试 4: 预算超限异常 ---")

    try:
        guard.record("analyze", {"prompt_tokens": 4_000_000, "completion_tokens": 1_000_000})
        guard.check()
        logger.info("  FAIL: 应抛出 BudgetExceededError")
    except BudgetExceededError as e:
        logger.info("  正确抛出异常: %s", e)
        logger.info("  通过")

    # ── 测试 5: 报告生成 ──
    logger.info("--- 测试 5: 报告生成与保存 ---")

    report = guard.get_report()
    assert "summary" in report, "缺少 summary"
    assert "by_node" in report, "缺少 by_node"
    assert "analyze" in report["by_node"], "缺少 analyze 节点统计"
    logger.info("  summary: %s", json.dumps(report["summary"], ensure_ascii=False))
    logger.info("  by_node keys: %s", list(report["by_node"].keys()))
    logger.info("  通过")

    saved = guard.save_report()
    assert saved.exists(), f"文件未创建: {saved}"
    logger.info("  报告已保存: %s", saved)
    logger.info("  通过")

    logger.info("=" * 60)
    logger.info("全部测试通过")
    logger.info("=" * 60)
