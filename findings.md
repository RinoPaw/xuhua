# 调研与发现

## 项目概况

- **代码库：** `src/heritage_explorer/` 包含 agent、extractor、retriever、search、web 五个核心模块
- **前端：** `templates/index.html` + `static/app.js` + `static/styles.css`
- **测试：** `tests/` 对应四个模块的测试文件
- **数据：** `data/` 目录含 demo_cases.json 和 processed/audit_report.json

## 当前未提交变更（12 文件，+2694/-436）

| 模块 | 变更行数 | 类型 |
|------|---------|------|
| agent.py | +483 | 核心逻辑 |
| extractor.py | +361 | 提取器 |
| retriever.py | +391 | 检索器 |
| search.py | +54 | 搜索 |
| web.py | +77 | Web 层 |
| app.js | +465 | 前端逻辑 |
| styles.css | +543 | 样式 |
| index.html | +63 | 模板 |
| test_agent.py | +167 | 测试 |
| test_extractor.py | +12 | 测试 |
| test_retriever.py | +200 | 测试 |
| test_web.py | +314 | 测试 |

## 已知问题

<!-- 调研过程中发现的问题记录 -->
