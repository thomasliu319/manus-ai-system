---
description: 实施 OpenSpec 变更中的任务 — 逐个执行待办任务
---

调用 skill: `openspec-apply-change` 来实施变更中的任务。

该技能会：
- 选择要实施的变更
- 读取上下文产物（proposal, design, specs, tasks）
- 逐个实现任务并标记完成状态
- 遇到阻塞时暂停并报告
