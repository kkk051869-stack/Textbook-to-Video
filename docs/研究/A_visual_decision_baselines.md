# A 方向：Visual Decision baselines

## 当前 AB 实现

合并后的 AB 分支保留现有 P0 `visual_decision.py`，并在
`src/textbook2video/research/visual_decision_baselines.py` 中提供不调用模型的四种可重复 baseline：

- `never_retrieve`：允许复用教材图片，但不触发外部检索；
- `always_retrieve`：对每个 proposition 触发 `retrieve`；
- `keyword_heuristic`：优先使用 proposition source refs 可达的教材图片，否则根据固定的 visual-type keyword 触发 `retrieve`，没有命中则为 `none`。
- `pool_availability`：优先复用教材图片；没有源图时，仅在冻结外部候选存在时触发 `retrieve`。

输出直接使用当前 P0 decision schema，并显式保留独立的 `visual_support_need` 字段。这些是 prediction，不是人工 gold。没有调用 LLM、embedding、网络检索或图像生成。

下文保留 G0 A 单线的历史运行记录。旧脚本、旧 `visual_decision.py` 私有 API 和批量 dry-run 目录没有整体复制进 AB 分支；路径记录不代表这些旧命令应在当前分支直接运行。

## G0 mock 运行

```powershell
$env:PYTHONPATH = "$PWD/src"
python scripts/run_visual_decision_baselines.py `
  --case-root datasets/research_generation_v2/mock_v0.1/cases/mock_lesson_001 `
  --output datasets/research_generation_v2/dry_run/<run_id>/cases/mock_lesson_001 `
  --run-id <run_id> `
  --baseline all
```

由于 Windows 路径长度限制，`nr`、`ar`、`kh` 三个短目录本身就是对应 baseline 的 result bundle：

```text
nr = never_retrieve
ar = always_retrieve
kh = keyword_heuristic
```

每个 bundle 包含 `run_manifest.json`、`visual_decision_predictions.json`、`candidate_pool_manifest.json`、`metrics.json`、`failures.json` 和 `README.md`。

## Pilot v1 legacy dry run

旧 Pilot 的 `lesson_context.json` 不是 G0 v2 原生输入，先由
`src/textbook2video/research/legacy_visual_input.py` 转换到新的隔离目录。适配器只读原始 Pilot 文件，并在 `adapter_manifest.json` 中记录来源 hash 和“不是 gold”的警告。

```powershell
$env:PYTHONPATH = "$PWD/src"
python scripts/run_visual_decision_legacy_dry_run.py `
  --contexts-root datasets/research_event_alignment/pilot_v1/cases `
  --storyboards-root datasets/pilot3/artifacts `
  --output-root datasets/research_generation_v2/dry_run/<run_id> `
  --schema contracts/research_generation_v2.schema.json `
  --run-id <run_id>
```

legacy dry run 的结果状态为 `NO_REFERENCE_NOT_GOLD`，不能据此计算准确率。正式实验前还需要固定 proposition 边界、候选池和人工标注协议。

## 当前人工代理标注轮次

已对 `20261006-3a7-pilot-a1` 的 5 个 legacy case、共 34 条 proposition 做完一轮
`assistant_manual_proxy` 判断。结果单独写入：

```text
datasets/research_generation_v2/dry_run/20261006-3a7-a2-manual34/sanity/
```

本轮统计为：`source-sufficient=6`、`extra-support-needed=20`、`none=8`；对应
`reuse=6`、`retrieve=20`、`none=8`。这些判断仍然是非正式定义检查结果，标记为
`COMPLETED_NONFORMAL` / `NOT_GOLD`，不能作为模型准确率或人工一致性结论。

下一阶段应根据其中 20 条 `candidate_pool_gap` 建立受控候选池，并在正式实验前冻结
人工标注协议和 proposition 边界。

## 候选池规格轮次

已生成受控候选池规格：

```text
datasets/research_generation_v2/dry_run/20261006-3a7-a3-candidates/
```

该轮登记了 15 张本地教材源图、34 个显式 `NO_MATCH` 选项和 20 个外部候选请求。
由于 Pilot 输入中没有现成外部候选资产，本轮没有执行网络检索，状态为
`CONTROLLED_POOL_SPEC_PENDING_EXTERNAL_ASSETS`。外部候选后续必须以新 run 加入，
并同时记录资产 hash、来源和许可信息；不能把待检索请求当作已取得的图片。

随后已冻结一轮受控公开素材 fixture：

```text
datasets/research_generation_v2/dry_run/20261006-3a7-a4-external/
```

该轮下载并登记 6 个 Wikimedia Commons 候选，覆盖 12 条 proposition；另有 8 条
请求仍无匹配外部候选，继续保留 `NO_MATCH` 和 pending 状态。该轮只冻结候选资产，
不把候选出现当作语义正确性，也不报告正式 retrieval accuracy。

## Retrieval trigger 与候选排序

基于外部候选 fixture 又完成了一轮无模型 dry-run：

```text
datasets/research_generation_v2/dry_run/20261006-3a7-a5b-trigger-rank/
```

其中实现了四个 trigger baseline：`never_retrieve`、`always_retrieve`、
`keyword_heuristic` 和 `pool_availability`；另有一个保留 `NO_MATCH` 的词法
候选排序器。`pool_availability` 对人工代理 acquisition 的非正式一致数为
26/34；排序器覆盖 12 条已有冻结外部候选的 retrieve 命题，另外 8 条保持
待候选状态。上述数字不是正式准确率。

## Proposition → visual binding

已在 `contracts/proposition_visual_binding.schema.json` 中固定命题到候选视觉对象的
关系契约，并实现两个确定性 baseline：

- `source_linked`：绑定命题已有的全部教材源图，支持一对多；没有源图则 abstain；
- `lexical_top1`：绑定上一轮词法排序选出的非 `NO_MATCH` 候选；没有可用候选则 abstain。

最新结果位于：

```text
datasets/research_generation_v2/dry_run/20261006-3a7-a6b-binding/
```

34 条命题中，`source_linked` 绑定 6 条、abstain 28 条，并产生 4 条一对多关系；
`lexical_top1` 绑定 18 条、abstain 16 条，产生 9 条 many-to-one 绑定（3 个共享
候选组）。仍缺冻结外部候选的 8 条请求保留在 `failures.json` 的 pending 中。
这些是可复现的非正式 baseline 输出，不是像素级验证、人工 gold、语义正确率或
人工一致性结果。

## A-only 正式 Pilot 包

按当前分工，后续只推进 A 的 Visual Support / Retrieval Triggering，不实现 B 的
semantic binding、timing、signaling 或 event evaluator。A 内部正式 pilot 包位于：

```text
datasets/research_generation_v2/annotation/20261006-3a8-formal-pilot-A-v1/
```

该包包含 30 条 proposition、两份相同内容的独立标注模板
`annotator_A1` / `annotator_A2`，以及固定版本的 A 标注协议。两份标注角色都属于
A 方向，不代表成员 B；包内不含旧代理标签、baseline prediction 或 gold。

已完成一份由助手执行的 A-only 代理标注：

```text
datasets/research_generation_v2/annotation/20261006-3a9-assistant-proxy-A-v3/
```

该轮覆盖 30/30 条，分布为 `extra-support-needed=16`、`none=8`、
`source-sufficient=6`。它复用了前期视觉检查，只能作为 A 的接口/定义检查，
仍然不是第二独立标注者、正式 gold 或 agreement 结果。与 A 的三个 baseline
逐条对照时，Never/Always/Keyword 的非正式一致数分别为 `14/30`、`16/30`、
`16/30`；这些数字不等于正式 accuracy。

## A-only 多 agent Pilot 对照

按 A-only 分工，已启动两个相互隔离的标注 agent：

```text
datasets/research_generation_v2/annotation/20261006-3aa-agent-A1/
datasets/research_generation_v2/annotation/20261006-3ab-agent-A2/
```

两者各自完成 30/30 条，未读取旧 proxy、baseline 或对方结果。对照结果位于：

```text
datasets/research_generation_v2/annotation/20261006-3ac-agent-proxy-comparison-A-v2/
```

结果仅是 agent-proxy debugging，不是人类 gold：

- proposition boundary：30/30，一致率 1.000；
- visual support need：26/30，Cohen κ=0.773；
- retrieval need：20/30，Cohen κ=0.510；
- visual function：25/30，Cohen κ=0.769；
- source evidence IDs：14/30 完全一致。

当前 gate 结论：visual support need 的定义可以继续迭代；retrieval need 的
`retrieve` 与 `generation-candidate` 边界仍不稳定，暂不冻结为 A 的正式 gold，
也暂不据此报告正式方法准确率。下一步只修订 A 的 retrieval 操作定义并做新的
独立复标；不扩展到 B 的 semantic binding、timing 或 signaling。

## A retrieval v2 复标 Gate

根据上述分歧，已发布不覆盖 v1 的 v2 协议：

```text
docs/研究/A_visual_decision_annotation_protocol_v2.md
datasets/research_generation_v2/annotation/20261006-3ae-formal-pilot-A-v2/
```

两个 agent 在 v2 下重新完成 30 条，汇总位于：

```text
datasets/research_generation_v2/annotation/20261006-3ah-v2/
```

v2 结果为：proposition boundary 30/30；source evidence 30/30；visual support
need 26/30、κ=0.751；retrieval need 22/30、κ=0.529；visual function 24/30、
κ=0.711。retrieval agreement 仍低于预注册的 0.67 gate。

因此 A 方向下一步按计划收缩主张：保留 `Visual Support Need` 作为可继续验证的
核心标签；`retrieval_need`、`retrieve` 与 `generation-candidate` 只保留为探索性
字段，不冻结为正式 gold，不报告正式 retrieval accuracy，也不继续扩展 B 方向工作。

## A 主任务隔离包：Visual Support Need

为避免把不稳定的 acquisition 判断混入 A 的主任务，已将 `visual_support_need`
单独抽成一个结果契约和可复现 bundle：

```text
contracts/visual_support_need.schema.json
src/textbook2video/research/visual_support_need.py
scripts/run_visual_support_need_baselines.py
datasets/research_generation_v2/dry_run/20261006-3ai2-visual-support-A/
```

该 bundle 使用 v2 两个 agent 的 proxy consensus 作为非 gold 参照：30 条中 26 条
达成一致、4 条保留为 `uncertain`；参照标签计数为
`extra-support-needed=17`、`source-sufficient=5`、`none=4`、`uncertain=4`。
在 26 条已解析命题上，`never_retrieve`、`always_retrieve`、
`keyword_heuristic` 对主标签的逐条一致数分别为 `9/26`、`17/26`、`12/26`。

这仍是 agent-proxy 的接口/基线检查，不是人工 gold 或正式准确率。A 当前只把
`Visual Support Need` 作为主验证对象；retrieval/acquisition 继续作为探索性字段，
不据此扩展 B。

## A Visual Support Need assistant adjudication

对 v2 proxy 中 4 条未决的 Visual Support Need 做了 A-only 内容复核，结果单独保存为：

```text
datasets/research_generation_v2/annotation/20261006-3aj-assistant-adjudication-A/
contracts/visual_support_need_adjudication.schema.json
src/textbook2video/research/visual_support_adjudication.py
scripts/run_visual_support_need_assistant_adjudication.py
```

复核将两条区块链技术/特性并列命题和一条信任因果命题判为 `none`，将工业体系
命题判为 `extra-support-needed`，因为现有联合国产业分类图不能覆盖生产端场景及
其优势关系。最终 30 条的 assistant-adjudication 分布为：
`extra-support-needed=18`、`source-sufficient=5`、`none=7`，未决数为 0。

该结果是 assistant adjudication，用于定义和流水线调试，不是 human gold、正式准确率
或人工一致性；本轮没有 adjudicate retrieval/acquisition 字段。正式结论仍需实际独立
人工标注者完成双盲标注后再冻结。

## A v2 双盲 packet readiness

已对 `20261006-3ae-formal-pilot-A-v2` 做只读 readiness 检查：A1/A2 均为 30 条，
proposition ID 顺序和 packet 结构一致，标注字段保持空白；packet 明确排除了旧的
assistant proxy 和 baseline prediction，`gold_status` 保持 `NOT_INITIALIZED`。
因此该包已经可以交给两名真实独立标注者使用；在他们提交结果前，不把现有
assistant adjudication 当作正式 gold。

## A repaired agent-proxy comparison

按用户要求，已安排两个相互独立的 A-only agent 完成 v2 packet，并由第三个
agent 对修复后的结果做对照。原始 agent 输出曾把 `proposition_boundary` 和
`visual_function` 写成非协议枚举，已保留原始目录并由各自 agent 修复到新目录：

```text
datasets/research_generation_v2/annotation/20261006-3ao-agent-A1-formal-v2-repaired/
datasets/research_generation_v2/annotation/20261006-3ap-agent-A2-formal-v2-repaired/
datasets/research_generation_v2/annotation/20261006-3aq-repaired-comparison-A-v2/
```

本轮修复后的协议检查和 manifest hash 均通过，30/30 条覆盖，无 failures。agent-proxy
对照结果为：`proposition_boundary=30/30, κ=1.000`；`visual_support_need=23/30,
κ=0.533`；`retrieval_need=20/30, κ=0.515`；`visual_function=17/30, κ=0.367`；
`source_evidence_ids=30/30`。因此 Visual Support Need 仍低于 0.67 gate，
retrieval 继续只作探索性字段；本轮不是 human agreement、human gold 或正式准确率，
不启动 B 方向工作。

## A v3 必要性 gate 复标与局部复核

根据两份独立 definition review 的一致建议，新增但不覆盖 v1/v2 的 v3 协议和 packet：

```text
docs/研究/A_visual_decision_annotation_protocol_v3.md
datasets/research_generation_v2/annotation/20261006-3au-formal-pilot-A-v3/
datasets/research_generation_v2/annotation/20261006-3av-agent-A1-v3/
datasets/research_generation_v2/annotation/20261006-3aw-agent-A2-v3/
datasets/research_generation_v2/annotation/20261006-3ax-v3-comparison-A/
```

v3 将“可选展示价值/可画图”与“必须视觉支持”分开，并要求 source-sufficient 直接
覆盖命题核心关系。v3 对照通过枚举、ID、输入输出 hash 和 failures 检查，30/30
无 failures：`proposition_boundary=30/30, κ=1.000`；`visual_support_need=28/30,
κ=0.643`；`retrieval_need=28/30, κ=0.483`（仅探索性）；`visual_function=28/30,
κ=0.634`；`source_evidence_ids=16/30` exact agreement。主标签已明显收敛，
但仍略低于 0.67 gate，不能冻结为正式 gold。

v3 剩余两条主标签分歧由两个独立 reviewer 局部复核：

```text
datasets/research_generation_v2/annotation/20261006-3ay-boundary-review-A1/
datasets/research_generation_v2/annotation/20261006-3az-boundary-review-A2/
```

两者均建议 `lesson-002-kprop-001` 和 `lesson-012-kprop-004` 为 `none`，不 abstain；
这只是非 gold 定义复核，不追溯改写 v3 agreement。当前 A-only 结论仍是继续收缩
正式主张为 Visual Support Need 的定义/接口研究，不报告正式准确率，不扩展 B。

基于两份局部复核的一致建议，另生成了一个不覆盖原始 v3 agreement 的 provisional
consensus bundle：

```text
datasets/research_generation_v2/annotation/20261006-3bb-v3-support-consensus-A/
```

其 30 条主标签分布为 `none=28`、`source-sufficient=1`、
`extra-support-needed=1`，状态为 `ASSISTANT_ADJUDICATION_NONFORMAL`、
`gold_status=NOT_GOLD`；只用于 A 的接口和 baseline 调试，不作为正式人工 gold。

## A v4 必要性反事实 gate：过度保守检查

为直接处理 v3 的 κ=0.643 分歧，新增 v4 协议，加入必要性反事实测试、`none` 锚点和
最小充分来源证据规则：

```text
docs/研究/A_visual_decision_annotation_protocol_v4.md
datasets/research_generation_v2/annotation/20261006-3bc-formal-pilot-A-v4/
datasets/research_generation_v2/annotation/20261006-3bd-agent-A1-v4/
datasets/research_generation_v2/annotation/20261006-3be-agent-A2-v4/
datasets/research_generation_v2/annotation/20261006-3bf-v4-comparison-A/
```

v4 两个 agent 均将 30 条标为 `none`，因此表面上四个字段 κ=1.000；但
`visual_support_need` 出现全类别坍缩，且把 v3 中两个正例（区块链结构图、骑行轨迹
审计链）也压成 `none`。该轮被记录为 `possible_overconservative_collapse`，不能作为
修复结果或 gold。

## A v4.1/v4.2 正例与照片负例护栏

v4.1 先增加了两个正例护栏：源图承载拓扑/字段布局时为 `source-sufficient`；缺少源图
但命题需要轨迹或可审计证据链时为 `extra-support-needed`。第一次 v4.1 agent 输出暴露
出协议没有重复写死枚举值的问题，原始目录保留为无效调试产物；随后补齐固定枚举并重跑。

进一步检查 v4.1 的 3 个分歧条目发现，`lesson-007-kprop-002/003/004` 的源图实际是
宗祠牌匾、建筑照片和侨批照片，而不是关系示意图。v4.2 明确规定“照片/实物例示及
caption 不能单独证明关系结构”，并保留两个正例锚点：

```text
docs/研究/A_visual_decision_annotation_protocol_v4_1.md
docs/研究/A_visual_decision_annotation_protocol_v4_2.md
datasets/research_generation_v2/annotation/20261006-3bl-formal-pilot-A-v4_1/
datasets/research_generation_v2/annotation/20261006-3bq-agent-A1-v4_2/
datasets/research_generation_v2/annotation/20261006-3br-agent-A2-v4_2/
datasets/research_generation_v2/annotation/20261006-3bs-v4_2-comparison-A/
```

v4.2 两个独立 A-only agent 均通过覆盖、枚举、来源 ID 和跨字段约束检查，结果为：

- proposition boundary：30/30，一致率 1.000，κ=1.000；
- `visual_support_need`：30/30，一致率 1.000，κ=1.000；分布为
  `none=28`、`source-sufficient=1`、`extra-support-needed=1`；
- `retrieval_need`：30/30，一致率 1.000，κ=1.000，仍只作探索性字段；
- `visual_function`：30/30，一致率 1.000，κ=1.000；
- `source_evidence_ids`：30/30 完全一致。

该结果说明 v3 的低 κ 主要来自“关系结构图”与“主题照片/例示图”的操作定义边界，
而不是简单的标签随机噪声。它仍是两个 agent proxy 的非 gold 对照，不能写成正式的人类
一致性或准确率；下一步若要冻结 A 的正式 gold，仍需真实人工双盲标注。A-only 范围到此
保持不变，不扩展 B。

## A v4.2 deterministic baseline diagnostics

在 v4.2 两个 agent 的一致 proxy reference 上重跑了 A 的三个 deterministic baseline：

```text
src/textbook2video/research/visual_support_need.py
scripts/run_visual_support_need_baselines.py
datasets/research_generation_v2/dry_run/20261006-3bu/
```

同时补充了不依赖 retrieval 的 confusion matrix、per-class precision/recall/F1 和
macro-F1 诊断，并增加了单元测试。结果为：

| baseline | exact / accuracy | macro-F1 | 主要现象 |
|---|---:|---:|---|
| `never_retrieve` | 24/30 = 0.800 | 0.390 | 对 28 条 `none` 较稳，但漏掉唯一的 `extra-support-needed` |
| `always_retrieve` | 1/30 = 0.033 | 0.022 | 几乎把全部命题推成外部视觉需求 |
| `keyword_heuristic` | 16/30 = 0.533 | 0.323 | 能命中源图正例，但对 `none` 有较多过触发 |

由于本 pilot 的 `source-sufficient` 和 `extra-support-needed` 各只有 1 条，上述
per-class 和 macro-F1 仅用于接口/基线诊断，不是正式准确率，也不能据此宣称某个
baseline 在真实数据上优胜。当前 A 的下一步是获得真实人工双盲 gold 后复用同一评测
脚本；retrieval/acquisition 仍保持探索性，不扩展 B。

## A v4.2 formal packet readiness gate

对 v4.2 空白双盲包执行了独立 readiness audit：

```text
scripts/check_visual_decision_formal_pilot_readiness.py
datasets/research_generation_v2/annotation/20261006-3bv/
```

8 项检查全部通过：协议版本、30 条覆盖、A1/A2 packet 内容一致、标注字段全空、30 个
源图候选路径可读、输入 failures 为空，并确认 proxy 与 baseline 均未泄漏。状态为
`READY`，`gold_status=NOT_INITIALIZED`。因此 A 的下一步可以直接交给两名真实独立
标注者；在此之前不把 agent proxy 共识升级为 human gold，也不开始 B。

## A v4.2 independent proxy replication

按继续执行要求，又安排两名新 agent 在不读取旧结果的条件下，对同一 v4.2 空白 packet
做了第二轮独立复测：

```text
datasets/research_generation_v2/annotation/20261006-3bw-agent-A1-v4_2-rep2/
datasets/research_generation_v2/annotation/20261006-3bx-agent-A2-v4_2-rep2/
datasets/research_generation_v2/annotation/20261006-3by-rep2-comparison-A/
datasets/research_generation_v2/annotation/20261006-3bz-A1-test-retest/
datasets/research_generation_v2/annotation/20261006-3ca-A2-test-retest/
```

复测 A1/A2 仍为 `none=28`、`source-sufficient=1`、`extra-support-needed=1`，主标签
30/30 一致，κ=1.000；与上一轮逐 agent test–retest 的主标签也均为 30/30、κ=1.000。
`source_evidence_ids` 的稳定性较低：A1 复测为 22/30，A2 复测为 30/30，说明来源
证据的“最小集合”仍需要真实标注者说明取舍，但没有改变 A 的主视觉支持标签。

这轮仍是 `NON_GOLD_INDEPENDENT_REPLICATION`，用于协议稳定性诊断，不是 human gold。

## A v4.2 baseline test–retest

使用第二轮复测 agent 输出重新跑了 baseline：

```text
datasets/research_generation_v2/dry_run/20261006-3ce/
```

与 `20261006-3bu` 相比，三种策略的 reference 分布、accuracy、macro-F1 和 confusion
matrix 完全一致：`never_retrieve=0.800/0.390110`、`always_retrieve=0.033333/0.021505`、
`keyword_heuristic=0.533333/0.322511`。这说明当前 A 工作版的 baseline 输出对本轮
agent 复测稳定；它仍然不等于 human-gold 泛化结果。

## A 工作版 proxy consensus

由于两轮独立 agent 复测的主标签完全一致，已由 A-only assistant 生成一个可供后续
流水线使用的工作版共识包：

```text
datasets/research_generation_v2/annotation/20261006-3cc-assistant-proxy-consensus-A/
```

该包覆盖 30/30 条，未发生 assistant 二次裁决，分布仍为 `none=28`、
`source-sufficient=1`、`extra-support-needed=1`，状态为
`ASSISTANT_ADJUDICATION_NONFORMAL` / `NOT_GOLD`。你不需要再手工填写这 30 条；后续 A 的
baseline 和接口实验可以直接使用这个工作版，但论文或正式结果不能把它写成真实人工 gold。

## A v4.2 retrieval-trigger diagnostic

继续把工作版接入 retrieval trigger 层，生成：

```text
scripts/run_visual_retrieval_trigger_v4_2.py
datasets/research_generation_v2/dry_run/20261006-3cg/
```

该诊断严格区分 `retrieve` 与 `generation-candidate`，同时额外报告二值“是否触发视觉”
指标。30 条 retrieval proxy 中有 29 条 `no`、1 条 `generation-candidate`：

| policy | exact retrieval label | binary visual-trigger |
|---|---:|---:|
| `never_retrieve` | 29/30 | 29/30 |
| `always_retrieve` | 0/30 | 1/30 |
| `keyword_heuristic` | 21/30 | 21/30 |
| `pool_availability` | 29/30 | 29/30 |

这些结果只说明当前小型 proxy packet 上的触发行为；`retrieval_need` 仍是探索性字段，
没有进行网络检索，也没有把 `generation-candidate` 偷换成外部 `retrieve`。

## A v4.2 generation-candidate gate

对上述唯一的 `generation-candidate`（`lesson-011-kprop-005`）继续执行候选获取分流审计：

```text
scripts/run_visual_generation_candidate_audit.py
datasets/research_generation_v2/dry_run/20261006-3ci-generation-audit-A/
```

审计结果覆盖 30 条 proxy 共识：28 条 `NO_VISUAL_REQUIRED`、1 条
`SOURCE_REUSE_ONLY`、1 条 `GENERATION_PENDING`，没有外部候选、没有网络检索、没有图像
生成调用。`lesson-011-kprop-005` 生成请求为
`lesson-011-kprop-005-generation-slot`，状态为 `PENDING_GENERATION_BRIEF`，保留
`lesson-011-src-p0014`、骑行轨迹→不可篡改记录→信用/规则的解释链约束，并明确不能暗示
命题之外的监控。

旧 A4 候选池虽然有 `ext-wikimedia-blockchain-svg`，但其旧标签是 `retrieve`，且只覆盖
区块链结构，不能证明本 proposition 的完整骑行治理链。因此它被明确排除在 v4.2
generation gate 外；旧 `NO_MATCH` 仍只作为显式候选选项保留。该审计是
`COMPLETED_NONFORMAL` / `NOT_GOLD`，不能替代真实人工 gold，也不报告生成质量或检索准确率。

## A assistant expert proxy（工作版伪 gold）

按 A-only 继续执行要求，将两名独立 agent 的 v4.2 输出整理成可供下游实验直接消费的
工作版：

```text
scripts/run_visual_expert_proxy_gold.py
datasets/research_generation_v2/annotation/20261006-3cj-assistant-expert-proxy-A/
```

30 条 proposition 的四个主字段全部达成代理一致：`proposition_boundary` 30/30、
`visual_support_need` 30/30、`retrieval_need` 30/30、`visual_function` 30/30。来源证据
有 8 条存在 A1/A2 取舍差异，工作版仅在 packet 已列证据范围内取并集，不把它伪装成单一
人工判断。该包的 `working_gold_status=ASSISTANT_EXPERT_PROXY`、
`formal_gold_status=NOT_GOLD`；原始 v4.2 双盲 packet 不被回写。

因此后续 A 的接口、baseline、generation gate 可以继续使用这个工作版；论文正式结果仍
不得报告为真实人工准确率、真实人工 κ 或 human gold。

## A 工作版 proxy baseline 复跑

已将 `ASSISTANT_EXPERT_PROXY` 作为单一工作版 reference 接入 baseline：

```text
scripts/run_visual_support_need_expert_proxy_baselines.py
datasets/research_generation_v2/dry_run/20261006-3ck-expert-proxy-baselines-A/
```

结果与上一轮双 agent consensus 完全一致：`never_retrieve` 为 24/30、accuracy
`0.800000`、macro-F1 `0.390110`；`always_retrieve` 为 1/30、accuracy `0.033333`；
`keyword_heuristic` 为 16/30、accuracy `0.533333`。这一步确认当前 A 工作版接入下游
baseline 后结果可复现，且没有把工作版升级成 formal gold。

## A human-reviewed gold freeze

用户已逐条审查审查包并明确确认：`我已审查全部 30 条，确认无误，冻结为 human-reviewed gold`。
因此生成冻结版：

```text
scripts/freeze_visual_human_review_gold.py
datasets/research_generation_v2/annotation/20261006-3cn-human-reviewed-gold-A/
```

冻结结果为 30/30 条接受、0 条修改，状态为 `FROZEN` / `HUMAN_REVIEWED_GOLD`。
该 gold 只覆盖 A 的 Visual Decision 字段，不包含 B；原始空白双盲 packet 和
`ASSISTANT_EXPERT_PROXY` 源文件保持不变。`formal_accuracy` 和
`inter_annotator_agreement` 仍为空，因为该冻结记录的是用户对工作版的审查确认，
不是与外部真值或第二名人工标注者比较后的准确率。

## A human-reviewed gold baseline evaluation

冻结 gold 后，使用同一组确定性 baseline 重新评测：

```text
datasets/research_generation_v2/dry_run/20261006-3co-human-gold-baselines-A/
```

该 run 的 reference status 为 `HUMAN_REVIEWED_GOLD`，30 条分布为
`none=28`、`source-sufficient=1`、`extra-support-needed=1`。结果为：

| policy | exact agreement | accuracy | macro-F1 |
|---|---:|---:|---:|
| `never_retrieve` | 24/30 | 0.800000 | 0.390110 |
| `always_retrieve` | 1/30 | 0.033333 | 0.021505 |
| `keyword_heuristic` | 16/30 | 0.533333 | 0.322511 |

这一步把之前的 proxy baseline 结果正式替换为相对 human-reviewed gold 的工作结果；
baseline 预测本身没有改变。

## A human-reviewed gold trigger 与 generation gate

最后将两个探索性 acquisition gate 也切换到冻结 gold：

```text
scripts/run_visual_retrieval_trigger_reference.py
datasets/research_generation_v2/dry_run/20261006-3cp-human-gold-trigger-A/

scripts/run_visual_generation_candidate_reference.py
datasets/research_generation_v2/dry_run/20261006-3cq-human-gold-generation-A/
```

trigger 结果保持：`never_retrieve=29/30`、`always_retrieve=0/30`、
`keyword_heuristic=21/30` 的 exact retrieval label agreement；generation gate 保持
28 条 `NO_VISUAL_REQUIRED`、1 条 `SOURCE_REUSE_ONLY`、1 条 `GENERATION_PENDING`，
外部候选数、网络检索调用数和图像生成调用数均为 0。这里的 retrieval label 仍是 A 内部
探索字段，不把它扩展成外部检索质量结论。

## A P1 generation-candidate follow-up

针对冻结 gold 中唯一的 `generation-candidate`，按 P1 optional visual completion 做了一次
独立生成与视觉 QA：

```text
datasets/research_generation_v2/dry_run/20261007-3cr-human-gold-generation-A-p1/
```

目标命题为 `lesson-011-kprop-005`。生成图把骑行轨迹连接到带锁的链式记录，再连接到
信用与规则遵守两个结果；没有执行外部检索。QA 通过 5 项检查（其中文字准确性不适用，
因为素材刻意不含文字）。该素材标记为 `GENERATED_NOT_GOLD`，不会回写或改变冻结的 A
标签；这只是 P1 follow-up，不是 A 当前 P0 gate 的新增要求。
