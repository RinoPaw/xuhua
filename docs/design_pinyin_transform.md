# 拼音模糊搜索 & CONTENT_TRANSFORM 设计概要

## 1. 拼音模糊搜索

### 目标
用户输入同音字也能命中目标条目。例：输入"落山"(luò shān) → 召回"罗山"(luó shān)。

### 方案
- 引入 `pypinyin`，取 **lazy style**（无调号拼音）
- 对 `HeritageItem.title` 预建拼音索引：`{ "luo": [...ids], "shan": [...ids], ... }`
- `tokenize()` 产出的每个 token 额外派生同音 pinyin token，参与 `score_item()` 打分
- 同音命中加分权重低于精确字面命中（建议精确字面 > 同音，大约 1:0.4）

### 改动范围
| 文件 | 改动 |
|------|------|
| `search.py` | 新增 `build_pinyin_index()`、`tokenize()` 产出拼音 token |
| `indexer.py` 或新文件 | KB 构建阶段调用 pinyin 索引生成 |
| `requirements.txt` | 加 `pypinyin` |
| `tests/test_search.py` | 同音召回用例 |

### 混合搜索调权
- 拼音命中只走 lexical 打分，不走 embedding
- RRF 融合时 `LEXICAL_RANK_WEIGHT` 从 1.0 上调到 **1.3**，防止 semantic（1.35）把拼音同音结果压下去

### 不做的
- 不做模糊音（前后鼻音等），阶段太复杂
- 不做编辑距离排序

## 2. CONTENT_TRANSFORM 任务处理器

### 目标
对指定非遗条目做内容改写，走提示词模板。

### 改写方向
- **年轻化** — 把官方/学术文本改成 Z 世代语言
- **双语** — 中英对照输出
- **精简** — 长文缩到 200 字以内
- **故事化** — 把条目资料改写成叙事体

### 方案
- Agent 新增 `_handle_content_transform()` handler
- 根据用户自然语言判断方向（不需要显式选模式，LLM 自己从"翻译成英文""说得生动点"等表述里推断）
- 与现有 `_handle_browse()` 的区别：browse 是汇总多个条目，transform 是对 **指定条目** 的单一文本做风格变换

### 改动范围
| 文件 | 改动 |
|------|------|
| `agent.py` | 新增 `_handle_content_transform()` |
| `tests/test_agent.py` | 风格改写用例 |
