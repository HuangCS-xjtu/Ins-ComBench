# Data Contract

本目录采用统一数据契约：每层一个目录，每层都包含 `questions.jsonl` 和 `scoring_key.jsonl`。

## Public Model Input

`questions.jsonl` 是唯一传给被测模型的文件。

- Layer 1/2: 题干、场景、选项和风险点元数据。
- Layer 3: 案情、结论任务、法条/推理任务。
- Layer 4: 多轮用户输入、风险点、攻击策略和场景。

## Evaluator-Only Key

`scoring_key.jsonl` 只用于 scorer 或 judge。

- Layer 1/2: 标准答案、解析、引用依据。
- Layer 3: 结论标签、法条机检键、推理金标和 10 分制评分结构。
- Layer 4: 合规边界、法律依据、目标违规行为和合规替代表现。

## Published Dataset

公开版本仅分发经过校验的 canonical JSONL，不包含内部原始材料或中间构建文件。数据完整性可通过以下命令验证：

```powershell
python -m ins_combench.validate
```

`scoring_key.jsonl` 虽随仓库发布以支持透明复现，但不得拼接到待测模型上下文、检索库或系统提示词中。正式评测必须保证目标模型只接收对应的 `questions.jsonl` 内容。

## License

`data/` 下由项目整理、标注和编排形成的数据集采用 [CC BY 4.0](../DATA_LICENSE)。该许可仅适用于项目有权许可的原创部分，不改变法律法规、司法文书及其他第三方来源内容原有的权利状态。
