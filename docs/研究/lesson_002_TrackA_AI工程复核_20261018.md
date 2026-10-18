# lesson_002 Track A AI 工程复核（2026-10-18）

## 1. 复核性质与结论

- 复核对象：`20261018-lesson002-track-a-development-r3` 的不可变本地运行产物。
- 复核人：Codex（AI 工程复核）。
- 结论：`REJECT_R3_SOURCE_GROUNDING_AND_COVERAGE`。
- 本复核不是双人盲标、不是人工 gold、不能替代 agreement/adjudication，也不能支持方法优越性结论。
- r3 继续保留为失败证据，不直接编辑其中的 JSON。

## 2. 关键问题

| artifact | item_id | verdict | issue_type | evidence |
|---|---|---|---|---|
| proposition graph | kprop-001–008 | reject | wrong source reference | 均引用 `raw-unit-0001`，但该单元只是 Markdown 标题；直接证据实际位于 `raw-unit-0012/0013`。 |
| proposition graph | kprop-014–017 | reject | wrong source reference | 均引用标题单元；直接证据实际位于 `raw-unit-0013`。 |
| proposition graph | kprop-028–031 | reject | wrong source reference / unsupported strength | 均引用标题单元；其中“理解区块链就是理解信任本身”是修辞性结论，教材没有同强度表述。 |
| narration coverage | segments 1, 7, 8, 9 | reject | omitted substantive claims | 四段含教材可支持的事实或总结性主张，但 r3 没有生成任何 narration proposition。 |
| narration | segment 3 | revise | unsupported strengthening | “唯一”“篡改变得几乎不可能”强于教材的“简短哈希值”和“可发现篡改”。 |
| narration | segment 4 | revise | unsupported conclusion | “保证交易的可追溯性和安全性”没有由该 UTXO 例子直接推出。 |
| narration | segment 5 | revise | unsupported strengthening | “立刻被发现”强于教材的“很快能够被发现”。 |
| narration | segment 6 | revise | unsupported scope | “不再依赖银行或政府”扩大了教材的“非中心化金融机构”表述范围。 |
| source image | fig7-6 | accept with scope limit | visual scope | 图中可见区块、上一块哈希、随机数、输入与输出；不能单独证明唯一性、不可篡改性或发现速度。 |
| visual decisions | r3 all | reject as downstream set | tainted dependency | 25 条决策依赖上述不完整且部分错误引用的命题图，不能进入 Track B。 |

## 3. 修复要求

1. 中文证据检索必须使用中文词法特征，排除标题、元数据、章节名和图题等结构单元。
2. 命题只能引用本段提供的证据上下文，并且与被引文本至少存在可审计的词法落点。
3. 对有实质性教材重叠的段落，模型不得静默返回空命题集。
4. 脚本与 storyboard 讲稿必须逐段一致；将上述过强或无依据措辞改为教材可直接支持的版本。
5. 修复后必须使用新 run ID 从头运行；r3 不覆盖、不复用中间产物。

## 4. Gate 状态

- Track A r3：`REJECTED_BY_AI_ENGINEERING_REVIEW`。
- Gate 1A：仍为 `TESTED_MOCK`。
- Gate 1B：未正式通过。
- 允许的下一步：修复后运行新的 development r4，并再次进行 AI 工程复核。
- 禁止：把本报告写成人工复核通过、直接启动正式 pilot/validation/locked test、运行批量实验。
