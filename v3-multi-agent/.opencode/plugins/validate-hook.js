/**
 * validate-hook.js — tool.execute.after Hook 插件
 *
 * 在 write/edit 工具执行后自动校验 knowledge/articles/ 下的 JSON 文件。
 * 校验失败时通过 console.warn 向 Agent 反馈错误详情。
 *
 * 插件生命周期:
 *   Agent 写文件 → tool.execute.after 触发 → 调用 validate_json.py
 *   → 校验失败? → console.warn 输出错误 → Agent 看到反馈 → 修正 → 再次触发
 */

export const JsonValidationHook = async ({ $ }) => {
  return {
    "tool.execute.after": async (input, output) => {
      const targetTools = new Set(["write", "edit"]);
      if (!targetTools.has(input.tool)) return;

      const text = [output?.title, output?.output].filter(Boolean).join(" ");
      if (!text.includes("knowledge/articles")) return;

      const result = await $`python3 hooks/validate_json.py knowledge/articles/*.json`.nothrow();
      const stdout = await result.text();

      if (result.exitCode !== 0) {
        console.warn("\n" + "=".repeat(60));
        console.warn("  ⚠️  tool.execute.after Hook — 知识条目校验未通过");
        console.warn("=".repeat(60));
        console.warn(stdout);
        console.warn("=".repeat(60));
        console.warn("  ↪  Agent 应根据以上错误修正 JSON 文件");
        console.warn("=".repeat(60) + "\n");
      }
    },
  };
};
