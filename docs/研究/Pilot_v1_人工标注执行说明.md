# Pilot v1 人工标注执行说明

## 1. 目标

本轮只验证原则定义是否可操作、现有产物是否足以支持人工观察，以及两名标注者能否独立形成可比较的判断。它不是自动分类器实验，也不负责修复视频。

数据入口为 `datasets/research_event_alignment/pilot_v1/pilot_index.json`。A、B 标注者只编辑各自文件，不编辑 `source.json`、`lesson_context.json`、`segment_context.json`、`machine_observations.json`、媒体文件或另一名标注者的文件。

## 2. 开始前检查

每名标注者开始前应确认：

1. 能打开五个 case 的 `media/final.mp4`；
2. 能读取对应的 `source.json`、`lesson_context.json` 和 `segment_context.json`；
3. 已完整阅读 `docs/研究/事件级教学原则标注手册_v1.md`；
4. 自己的 annotation/task 文件均为 `NOT_STARTED`；
5. 所有人工字段仍为 `null`、空数组或空字符串；
6. 未查看另一名标注者的文件。

如 MP4、source 或 narration 无法读取，应停止该 case 并记录技术问题，不得依据候选字段猜测标签。

## 3. 防止实验相互污染的执行顺序

同一标注者必须按以下顺序完成，且不得回看并修改已冻结的前一阶段答案：

1. **Source ablation Round 1**：先完成分配到的 30 个 WITH_SOURCE/NO_SOURCE 任务；
2. **三层时间证据实验**：依次完成 A_plan_only、B_plan_runtime、C_rendered；
3. **完整事件级标注**：最后完成五个 case 的 proposition、visual、temporal 与 signaling 标注；
4. A、B 都完成后，才运行一致性统计和争议审阅。

Source ablation 必须最先执行，因为完整标注会让标注者接触 source，从而污染 NO_SOURCE 条件。三层时间证据的 Panel A、B、C 必须顺序执行，以保留新增证据是否改变判断的记录。

## 4. 文件分工

### 标注者 A

- 完整标注：`cases/<case>/annotations/annotator_A.json`
- Source ablation：`tasks/source_ablation/annotator_A_round1.json`
- 三层证据：`tasks/three_layer/annotator_A/*.json`

### 标注者 B

- 完整标注：`cases/<case>/annotations/annotator_B.json`
- Source ablation：`tasks/source_ablation/annotator_B_round1.json`
- 三层证据：`tasks/three_layer/annotator_B/*.json`

任何人都不得把 A 的答案复制到 B，或用 LLM/VLM 批量填写人工字段。

## 5. 状态管理

开始编辑一个文件时，将顶层 `annotation_status` 或 `status` 从 `NOT_STARTED` 改为 `IN_PROGRESS`。只有完成该文件全部任务、检查必填理由且无空缺后，才改为 `COMPLETED`。

`gold_labels_initialized=false` 只是空白模板声明。首次填写人工标签后可改为 `true`。这不表示标注正确，也不替代完整性检查。

每次工作结束应保存合法 UTF-8 JSON。不要改变 schema version、case ID、candidate ID、event ID 或机器观察字段。

## 6. 完整事件级标注操作

对每个 case：

1. 先看 source 与 lesson context，再听/看完整 MP4；
2. 按 segment 处理 candidate proposition；
3. 根据手册将候选标为 ACCEPT_CANDIDATE、EDITED、SPLIT 或 MERGED；
4. 为最终 proposition 赋唯一 `proposition_id`，填写文本和人工校正的 narration 时间；
5. 人工确认 KP 与 source evidence 绑定，不把 lexical candidate link 当成 gold；
6. 依次标 Visual Necessity、Visual Correctness、Temporal Contiguity、Signaling；
7. 写出 element/event/target ID 时，先在 `machine_observations.json` 中核对，再在 MP4 中确认实际呈现；
8. 无法观察实际可见区间时使用 UNOBSERVABLE/UNCERTAIN 并解释，不得把 planned/runtime time 抄为 observed time。

若需要 SPLIT，可复制当前 proposition 空白结构形成多行，并为每行写不同 ID、文本和时间；若需要 MERGED，以一个最终 proposition 行承载结果，并在 notes 记录被合并的 candidate IDs。机器候选本身保留不改。

## 7. 证据优先级

- source：判断教材支持、visual semantic correctness 与 attribution；
- narration/字幕候选：定位命题，但候选边界不构成 gold；
- storyboard/timeline：表示计划，不表示最终可见；
- runtime trace：表示浏览器侧事件执行记录，不表示对象一定被学习者看见；
- MP4：判断最终呈现与 observed visibility 的最高优先级；
- neighborhood frames：仅用于定位，不能取代连续播放视频。

技术失败与教学违规分开记录。`target_missing`、资源缺失、trace 缺口是技术证据；只有人工确认其造成教学需要未满足时，才进入教学原则标签。

## 8. 双人独立与争议处理

首轮期间：

- A、B 不讨论具体 case；
- 不共享已填文件、截图或标签；
- 可共同查阅本手册，但新增规则必须同时记录并从同一位置起生效；
- 不在看到一致性结果前回改首轮答案。

两人均完成后，先冻结原文件并运行 `src/textbook2video/research/annotation_agreement.py`。脚本只统计，不自动裁决。随后另建争议记录，由第三方或共同讨论形成 adjudicated 版本；不得覆盖原始 A/B 标签。

## 9. 停止条件

出现以下任一情况，暂停相关 case 并写入问题清单：

- source、narration 或 MP4 缺失/损坏；
- schema 与手册标签集合冲突；
- 同一标签在至少 5 个任务上无法按定义判断；
- proposition 时间坐标系无法确认；
- 标注者意外看到了另一条件或另一标注者答案。

暂停不等于把缺失项标成否定标签。先修复数据包或澄清规则，再从冻结点继续。
