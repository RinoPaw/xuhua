# 四语种独立检索评测协议

本流程测量叙华检索模块对**独立编写、人工核验的问题**的表现。现有
`tools/evaluate_retrieval.py` 仍用于知识库内部生成的精确名称回归，不代表真实用户评测。

## 当前已实现

- `data/eval/retrieval_cases.json`：20 条候选问题，中文 / 英文 / 日文 / 韩文各 5 条。
- `tools/evaluate_labeled.py`：校验问题结构，调用现有语言识别、意图及检索逻辑，输出前五个候选。
- `server/tests/test_evaluate_labeled.py`：防止未核验的问题进入指标，确保无效 ID 被拒绝。
- GitHub Actions 自动校验候选问题及运行检索预览，不调用大模型、不使用人工或生产凭据。

**当前 20 条全部为 `draft`。因此 approved=0、metrics=null。任何对外展示都不能写成“20 题准确率 0% 或 100%”。**

## 如何标注

1. 独立查看当前问题，确认提问语言和预期查找目标；不要先把检索排名当成标准答案。
2. 从官方名录或仓库原始记录找到有依据的**具体子项 ID**。名称相同但保护单位、地域不同的记录不可随意合并。若合理答案涉及多个子项，可标注多个 ID。
3. 记录证据（官方项目详情 URL、来源记录编号或核验依据）和 `review_note`，并解释为什么这些 ID 与提问相关。外部网页与仓库记录不一致时先调查，不直接将模型答案当作真值。
4. 将标注后的 `status` 改为 `approved`，填入 `expected_item_ids`。对于意义模糊、宽泛推荐或不能确定全部合格项目的题目，继续保持 `draft`。
5. 再运行评测，将 approved 题目的指标独立报告；按语言和任务类别检查样本覆盖，不要凭几条题推断现实用户总体表现。

示例格式（以下使用**虚构的子项 ID**，仅解释结构，不要复制到真实数据）：

```json
{
  "id": "illustration-only",
  "language": "zh-CN",
  "task": "item_lookup",
  "question": "请介绍某个非遗项目。",
  "status": "approved",
  "expected_item_ids": ["replace-with-verified-real-id"],
  "evidence": "该子项对应官方详情页的实际 URL 或已核对的原始记录",
  "review_note": "明确指出标注子项与题目的关联"
}
```

未经核验的候选必须维持 `status=draft` 且 `expected_item_ids=[]`。

## 运行方式

```powershell
uv run python tools/evaluate_labeled.py --summary
uv run python tools/evaluate_labeled.py --output evaluation.json
# 需要正式的人工评测指标时，强制至少一条 approved：
uv run python tools/evaluate_labeled.py --require-approved --output evaluation.json
```

`--require-approved` 在所有候选仍未核验时退出非零，防止误发“正式评测通过”。

## 指标定义与边界

| 指标 | 定义 |
| --- | --- |
| Hit@1 | 前一条结果属于核验关联子项的题目比例 |
| Hit@5 | 前五条至少出现一条核验子项的题目比例 |
| Recall@5 | 每道题在前五条找到的核验子项数 / 该题核验子项总数，再取题目均值 |
| MRR@5 | 第一条相关结果排名倒数的平均值；前五条未命中计 0 |

所有指标只统计已核验题目，未核验题目仅生成候选预览。当前脚本覆盖检索链路，
**不评估 LLM 生成内容的事实准确率、来源引用可靠性、语音识别错误率、TTS 自然度或用户满意度**。
这些评价需要额外的人工标准答案或真实音频语料。

此外，脚本会输出 `retrieval_basis`、实际查询、检测语种、候选 ID 及耗时。
这能定位“意图识别失败 / 跨语种词条转换失败 / 召回失败”等不同问题，
但自动预览不等于人工审核。

## 数据卫生

不得把真实用户聊天记录、手机号、学校内部信息或 API 密钥直接上传到评测集。
建议仅使用公开非遗知识与经审核的模拟任务，并记录知识库版本和评测时间。
