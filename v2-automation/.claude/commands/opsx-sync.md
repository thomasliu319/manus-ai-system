---
description: 将变更中的 delta spec 同步到主规格文件
---

调用 skill: `openspec-sync-specs` 来同步 delta spec。

该技能会：
- 选择包含 delta spec 的变更
- 智能合并 delta spec 到主规格
- 保留主规格中未被提及的内容
- 确保幂等性操作
