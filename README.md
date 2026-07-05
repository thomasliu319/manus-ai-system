所有工具均不可用，错误非我方能解决。请直接在终端执行：

cat > /home/thomas/mySpace/manus-ai-system/README.md << 'README_EOF'
# Manus AI 知识库系统

自动化技术情报采集、分析与整理流水线，持续追踪 AI/LLM/Agent 领域的高质量技术文章与开源项目。

## 架构
采集 (Collector) ---> 分析 (Analyzer) ---> 整理 (Organizer) | | | v v v GitHub / RSS DeepSeek LLM knowledge/articles/


### 三阶段流水线

| 阶段 | 职责 | 输出 |
|------|------|------|
| 采集 | 从 GitHub Trending、Hacker News、arXiv、技术博客等来源抓取原始数据 | knowledge/raw/*.json |
| 分析 | 调用 DeepSeek LLM 对每条内容进行评分、标签分类、摘要生成 | 结构化分析结果 |
| 整理 | 去重、质量门控(>=0.6)、生成知识条目 JSON | knowledge/articles/*.json |

## 快速开始

```bash
cd v2-automation

# 配置 API Key
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 运行全流水线（GitHub + RSS，每源 20 条）
python3 pipeline/pipeline.py --sources github,rss --limit 20

# 仅 GitHub，不限 LLM 分析
python3 pipeline/pipeline.py --sources github --limit 10 --dry-run

# 仅 RSS 并启动 LLM 分析
python3 pipeline/pipeline.py --sources rss --limit 5
核心组件
pipeline/model_client.py - 统一 LLM 客户端
支持 DeepSeek / Qwen / OpenAI 三家 API（OpenAI 兼容格式）
默认使用 deepseek-v4-pro 模型
指数退避重试（最多 3 次）
成本估算
零第三方依赖（仅 httpx）
pipeline/pipeline.py - 流水线编排
4 步可配置：--step 1 --step 2 --step 3 --step 4
模拟运行模式：--dry-run
详细日志：--verbose
pipeline/rss_reader.py - RSS 采集模块
多源并行采集配置（rss_sources.yaml）
简易 XML 解析，零第三方依赖
mcp_knowledge_server.py - MCP 知识库搜索服务
通过 MCP (Model Context Protocol) over stdio 提供 3 个工具：
工具	功能
search_articles(keyword, limit=5)	按关键词搜索标题/摘要/标签
get_article(article_id)	按 ID 获取完整文章
knowledge_stats()	统计信息（总数、来源分布、热门标签）
注册：opencode mcp add knowledge-server -- python3 $(pwd)/mcp_knowledge_server.py
质量门控
hooks/validate_json.py - JSON 条目格式校验（6 字段检查，exit 0/1）
hooks/check_quality.py - 5 维度质量评分（摘要/深度/格式/标签/空洞词），A/B/C 三级
hooks/.opencode/plugins/validate-hook.js
OpenCode 插件：写入 knowledge/articles/ 后自动触发验证
项目结构
v2-automation/
|-- pipeline/
|   |-- pipeline.py           # 流水线主编排
|   |-- model_client.py       # LLM 客户端封装
|   |-- rss_reader.py         # RSS 采集器
|   |-- rss_sources.yaml      # RSS 源配置
|-- hooks/
|   |-- validate_json.py      # JSON 条目校验
|   |-- check_quality.py      # 质量评分
|-- .opencode/
|   |-- agents/               # Agent 角色定义
|   |-- skills/               # 采集/分析技能定义
|   |-- plugins/              # OpenCode 插件
|-- knowledge/
|   |-- raw/                  # 原始采集数据
|   |-- articles/             # 知识条目 + index.json
|-- .env                      # API Key 配置
|-- mcp_knowledge_server.py   # MCP 搜索服务
|-- AGENTS.md                 # 项目记忆文件
技术栈
语言: Python 3.13+
依赖: httpx（LLM 调用）、python-dotenv（配置加载）
LLM: DeepSeek (deepseek-v4-pro)
协议: MCP (Model Context Protocol) over stdio
编码规范: PEP 8，JSON 2 空格缩进，注释/摘要用中文 README_EOF