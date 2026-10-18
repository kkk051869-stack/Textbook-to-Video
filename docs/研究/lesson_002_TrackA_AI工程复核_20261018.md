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

## 5. r4 运行中断记录

- r4 使用冻结模型 `ecnu-max`，在首个命题图 HTTP 调用上保持已建立网关连接超过 9 分钟，未写出任何 generation 产物，也未触发代码内 600 秒超时。
- 操作员在确认精确进程号与 r4 command line 后终止等待进程；`manifest.json` 和空输出目录保留，未覆盖、不重跑 r4。
- 使用 `ecnu-plus` 的独立最小 OpenAI-compatible 调用在 14 秒内返回，故创建新的 development r5 配置，显式冻结模型切换；该结果不与 r4 混合。

## 6. r5 运行中断与 r6 受限预算

- r5 的 `ecnu-plus` 也在首个完整命题图调用上超过 6 分钟无产物；精确进程经核对后终止，空运行目录保留。
- 使用真实第 1 段的 4,022 字符命题提示、`ecnu-plus`、`max_tokens=768` 和 60 秒网络超时做独立诊断，在 26 秒内返回 2,528 字符 JSON。
- r6 因此冻结为：主命题图请求 `max_tokens=1024`，两类修复请求 `max_tokens=512`。这改变的是可审计的输出预算而非回退或跳过；使用新 run ID，不能覆盖 r5。

## 7. r6 失败与 r7 语言约束

- r6 的请求预算修复生效并返回模型输出，但第 6 段出现英文 knowledge proposition；其中文 source passage 无词法落点，校验以 `knowledge proposition has no lexical grounding ... segment 6: kp5-p2` 停止运行并保留 `failure.json`。
- r7 在命题提示中明确要求：所有 knowledge/narration propositions 使用简体中文，并保留中文教材事实术语。该约束与原有 source grounding 一并冻结；不修改或复用 r6 产物。

## 8. r7 网关中断与 r8 请求超时

- r7 在顺序调用中持续超过 6 分钟且未落盘任何 generation 产物；连接仍保持到 ECNU 网关。为避免无界等待，操作员核对精确 command line 后终止两个 r7 Python 进程，保留 manifest 与空目录。
- r8 将命题图与修复调用的请求级超时统一冻结为 90 秒。该变更不增加回退或自动重试，只让失败在单个请求内可审计地结束。
