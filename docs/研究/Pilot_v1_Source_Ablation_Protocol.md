# Pilot v1 Source Ablation Protocol

## 1. 研究问题

本实验只回答一个 pilot 问题：**教材 source evidence 是否会改变人工对 visual applicability / visual relation 的判断？**

它不训练或评价自动模型，也不预设 WITH_SOURCE 一定更准确。若 source 不改变判断，可能意味着该样本不需要 source、任务定义不敏感，或 sample size 不足，不能直接推出 source-conditioned diagnosis 无价值。

## 2. 样本与随机化单元

- 从 5 个 case 中抽取 30 个 proposition candidates；
- 每个任务固定 case、segment、candidate text、候选时间与视频；
- 版本只有 `WITH_SOURCE` 和 `NO_SOURCE`；
- A、B 得到相反条件：同一任务在 A 为 WITH_SOURCE 时，在 B 为 NO_SOURCE，反之亦然；
- 每名标注者各完成 30 项，其中 15 项 WITH_SOURCE、15 项 NO_SOURCE。

该分配用于降低 case/task 差异的影响，不等于已具备正式统计功效。

## 3. 条件定义

### WITH_SOURCE

标注者可访问 `lesson_context.json`，并可看到机器生成的 candidate KP/source links。后者明确标为 `MACHINE_CANDIDATE_NOT_GOLD`，只能帮助导航，不能当成正确绑定。

### NO_SOURCE

任务中的 `source_context_path` 与 `candidate_knowledge_point_links` 均为 `null`。标注者只根据 candidate narration、视频和客观视觉信息判断，不得另行打开该 case 的 source 或 lesson context。

NO_SOURCE 任务仍可访问 `machine_observations.json` 以识别 element/event，但不得通过其他文件反向读取 source/KP 信息。

## 4. 执行约束

1. Source ablation 必须在完整 case 标注之前完成；
2. 首轮只看自己分配的条件，不查看另一标注者或同一任务的另一版本；
3. 标注者按任务文件顺序完成，不按预期结果挑选任务；
4. 每项填写 `visual_applicability`、`visual_relation`、`visual_element_ids`、`reason`、`annotator_confidence`；
5. 证据不足时填写 `uncertainty_reason`，不得用 source 猜测 NO_SOURCE 项；
6. 完成后将文件顶层 `status` 设为 `COMPLETED` 并冻结。

文件位置：

- `datasets/research_event_alignment/pilot_v1/tasks/source_ablation/annotator_A_round1.json`
- `datasets/research_event_alignment/pilot_v1/tasks/source_ablation/annotator_B_round1.json`

## 5. 观察指标

在 A、B 首轮均冻结后，按同一 task 比较：

- visual applicability 是否改变；
- visual relation 是否改变；
- element selection 是否改变；
- confidence 是否改变；
- source 是否使理由从主题相关转为有教材证据的具体归因；
- 不确定性是否下降或上升。

报告应同时给出原始计数、方向性变化和代表性分歧，不只报告单一比例。样本量小，不把结果包装为确定性因果结论。

## 6. 污染控制

- 不允许先做完整标注再做 ablation；
- 不允许两名标注者讨论某任务的 source；
- 不允许把 NO_SOURCE case 的 source 放在同一屏幕或缓存标签页；
- 若标注者已熟悉某 case source，应在 `uncertainty_reason` 中标记 memory contamination；
- 如后续设计 crossover round，应设置 washout、重新随机化顺序，并与本轮结果分开保存。

## 7. 完成标准

只有当 A、B 两份文件均为 COMPLETED、所有 30 项人工字段完整、NO_SOURCE 项无 source 字段泄漏且原始文件已冻结，才可计算 source-conditioned judgement change。否则结果状态为 NOT READY。
