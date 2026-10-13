# A 视觉支持判定标注协议 v4.2

## 1. 用途与边界

本协议只服务于 A 任务：判定一个知识命题是否需要视觉支持，以及已有源图是否已经足够。它不判定 B 任务的语义绑定、画面时序或镜头级对齐，也不把检索结果质量当作本协议的金标准。

本轮版本号：`t2v-visual-decision-formal-pilot-v0.4.2`。

每条输出必须使用以下固定枚举，不能把解释性文字写入标签字段：

- `proposition_boundary`：`accept` 或 `uncertain`；选择 `uncertain` 时必须填写 `abstain_reason`；
- `visual_support_need`：`none`、`source-sufficient`、`extra-support-needed` 或 `uncertain`；
- `retrieval_need`：`no`、`retrieve`、`generation-candidate` 或 `uncertain`；
- `visual_function`：`explain`、`organize`、`signal`、`example`、`decorative`、`uncertain`，或在 `visual_support_need=none` 时填 `null`。

若 `visual_support_need=none`，`retrieval_need` 必须为 `no`，`visual_function` 必须为 `null`。若
`visual_support_need=source-sufficient`，`retrieval_need` 必须为 `no`；若为
`extra-support-needed`，`retrieval_need` 必须在 `retrieve` 和 `generation-candidate` 中选择。

## 2. 核心判定顺序

对每个命题按以下顺序判断：

1. 先确定命题边界，不能把同段背景材料、例子或邻近结论并入命题。
2. 做“必要性反事实测试”：如果只保留命题文字和旁白，学习者是否仍能核查命题要求的对象、关系、步骤、比较和结论？仅仅“有图更直观”“有图更好看”不构成需要视觉支持的理由。
3. 但反事实测试不能把“结构/轨迹/证据链的图形承载”误判为文字复述。若命题的核心是对象的空间、拓扑、字段布局、轨迹或可审计链条，必须继续检查这些关系是否需要由视觉结构直接承载。
4. 最后区分 `source-sufficient` 和 `extra-support-needed`：已有源图直接承载核心关系时用前者；没有源图承载而命题确实需要视觉证据时用后者。

## 3. `visual_support_need` 定义

### 3.1 `none`

命题可以由文字/旁白独立核查，视觉最多是可选的组织、例示或装饰。以下是默认 `none` 锚点：

- 抽象、规范性、价值判断和宏观评价；
- 并列清单、熟悉例子、历史沿革或“包括/涉及/有助于”等宽泛陈述；
- 命题已经用文字完整列出的阶段顺序或作用链，且不要求学习者检查图形布局、空间轨迹或证据记录；
- 文本已经直接给出对象及关系，额外图示只会把同一关系重新排版。

照片、牌匾、建筑、纸币、书信或其他具体例示物，即使图片 caption 使用了“基于血缘/地缘的信任”“基于价值的信任”“基于信用的信任”等概念标题，也只说明某个例子存在，不等于图像承载了命题的关系结构；这类图片默认标为 `none`。

### 3.2 `source-sufficient`

已有源图直接承载命题的核心对象和关系，并且其信息不是文字逐项复述即可替代的。满足以下条件时可用：

- 源图是示意图、流程图、拓扑图、结构图或其他信息图，其空间/拓扑结构、连接关系、字段布局或视觉证据本身是命题解释的核心；
- 去掉源图后，学习者虽然可能听到同一组名词，却无法按命题要求检查该结构如何组织或连接；
- 仅有照片、实物图、建筑图或例示图片，不满足本标签；
- `source_evidence_ids` 应指向包含该核心图形证据的最小源材料集合。

正例锚点：命题“区块链采用链式数据结构，每个区块包含上一区块哈希、随机数和交易记录”，源图直接展示相邻区块、连接方向以及区块内部字段布局，因此标为 `source-sufficient`，不能因为命题文字也提到了这些名词就降为 `none`。

### 3.3 `extra-support-needed`

命题的核心是需要学习者检查的轨迹、空间变化、可审计证据链或多实体因果链；现有源图没有直接承载该核心结构，因此需要额外视觉支持。满足以下条件时可用：

- 视觉不是单纯把抽象结论做成流程框，而是要展示命题中的轨迹/证据/实体之间如何连接；
- 现有源图只能提供文字背景，不能直接核查核心链条；
- 若可由命题信息生成，应标记 `retrieval_need=generation-candidate`，不要把外部检索误当作充分证据。

正例锚点：命题“区块链可记录骑行轨迹，利用真实、不可篡改的数据佐证骑行行为，支持惩罚、信用分和规则遵守”，需要把轨迹、记录和后果作为可审计链条呈现；若 packet 没有承载该链条的源图，标为 `extra-support-needed`。

## 4. 防止过度保守和过度扩张的互斥规则

- “命题文字完整”不等于“视觉永远不需要”。只要核心学习对象是结构、轨迹或证据链，应使用第 3.2/3.3 节继续判定。
- “packet 中存在图片”也不等于 `source-sufficient`。图片必须直接承载核心关系，而不能只是同主题照片、装饰图、例示物或邻近背景。
- caption/文件名只能帮助定位图片，不能单独证明图片承载了关系结构；必须检查图片内容属于示意/结构信息，还是单纯照片/实物例示。
- 不能为了提高 κ 而把所有样本压成 `none`。若一个协议版本出现全类别坍缩，必须在报告中标记为 `possible_overconservative_collapse`，不得作为 gold 结论。
- `visual_function` 仅在 `source-sufficient` 或 `extra-support-needed` 时填写；`none` 必须为 `null`。

## 5. `retrieval_need` 与来源证据

`retrieval_need` 继续作为 A 内部的探索字段：`no`、`retrieve`、`generation-candidate`、`uncertain`。它不改变 `visual_support_need` 的判定，也不用于声称外部检索质量。

`source_evidence_ids` 取支撑当前命题边界和当前视觉判定的最小集合。不得为了“保险”列出整段邻近页；但如果多个材料共同构成不可拆分的核心证据链，应全部保留。

## 6. 质量控制

- 30 条命题全部覆盖；ID、命题文本和枚举值必须通过 schema 校验。
- 独立标注后计算逐字段一致率和 Cohen's κ；所有 agent 结果标记为 `NON_GOLD_INDEPENDENT`，一致性比较标记为 `NOT_GOLD`。
- 除 κ 外必须报告三类标签的边际分布，并检查是否出现全类别坍缩。
- 任一无法稳定判断的条目可使用 `abstain`，但本轮不应为了避免分歧而强行改成 `none`。

