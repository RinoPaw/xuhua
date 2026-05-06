# 任务规划：叙华

## 当前状态

- **项目：** 叙华 — 非遗传播任务型 AI 智能体
- **技术栈：** Python 3.10+ / Flask / Jinja2 / Vanilla JS
- **分支：** `main`
- **未提交变更：** 22 文件，含大量格式化（核心变更约 6 个代码模块 + 前端 + 测试）
- **基线测试：** 92 passed ✅

## 阶段

### 阶段 0：现状评估 ✅
- [x] Review 当前未提交的 diff，理解变更范围和目的
- [x] 确定这些变更是继续推进还是需要重新规划
- [x] 运行现有测试，确认当前基线（92 passed）

**Diff 分析总结：**
- **agent.py** — 新 Agent 架构：IntentRouter 8 种任务类型、3 个 MVP 处理器（Browse/Recommend/Exhibition）纯规则引擎已实现，含寒暄检测和 SoftLabels 推荐评分
- **retriever.py** — 新 QueryAnalyzer：从原始查询提取 province/category/level/city/scenario/audience，产出结构化 QueryAnalysis
- **extractor.py** — 新增 FieldEvidence 溯源追踪、StructuredMeta 扩展到 history/features/cultural_value，Schema v1→v2
- **web.py** — /api/items 新增 province/level/district 过滤，/api/ask 改为 SSE 流式 dispatch_stream
- **ai.py / search.py / dataset.py** — 格式化 + 过滤增强 + SoftLabels/StructuredMeta 支持
- **前端 (app.js/index.html/styles.css)** — SSE 流式进度展示、数字人状态机、语音播报控制、水墨风 UI
- **测试** — 全面扩充 agent intent routing、retriever analysis、web API 测试

### 阶段 1：决策下一步
- [x] 明确本轮目标：继续完成未完成的 Agent 任务处理器 + pinyin 模糊搜索
- [ ] 产出具体的实现任务列表
- [ ] 同音字模糊搜索：用 pypinyin 做拼音索引，输入"落山"能搜到"罗山"

### 阶段 2：实现
- [x] 实现 COMPARISON 任务处理器（双条目结构化对比，含表格 + 叙事 + 小结，纯规则无 LLM）
- [x] 实现 STUDY_TASK 任务处理器（五环节教案模板：导入→讲解→探究→体验→评价，含教学目标/重点难点/拓展建议）
- [x] 实现 CONTENT_TRANSFORM 任务处理器（翻译/年轻化/文创文案/改写，有 API 时调 LLM 自定义 prompt，无 API 时模板兜底）
- [x] 实现 pinyin 模糊搜索（pypinyin 索引 + 同音召回，搜索「落山」→「罗山皮影戏」，支持纯拼音输入「luoshan」）
- [ ] 每项完成后运行测试验证

### 阶段 3：收尾
- [ ] 全量测试
- [ ] 代码审查
- [ ] 提交 / PR

---

## 决策记录

| 日期 | 决策 | 原因 |
|------|------|------|
| 2026-05-06 | 阶段 0 完成，变更均为同一方向（Agent 架构升级），继续推进不重建 | diff 核心变更一致：意图路由 → 查询分析 → 任务分发 |
| 2026-05-06 | 搜索结果质量门控交给 LLM 判断，不做硬阈值 | 硬阈值无法区分 "hello"（无关）和 "桐柏山歌"（相关），LLM 自己判断搜索结果是否可用 |
| 2026-05-06 | Agent 自主决定是否检索：收到输入后先判断需不需要查资料，而不是无条件搜索 | 更接近真实智能体行为——寒暄/闲聊直接回答，知识类问题才检索 |
