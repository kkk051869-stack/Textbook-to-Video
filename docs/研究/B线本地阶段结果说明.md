# B 线本地阶段结果说明

## 范围与结论

本阶段在冻结的 G0 启动包与 Pilot v1 既有产物上完成了 B 线的**无模型可复现实验骨架**：命题候选到 storyboard element 的本地 lexical/Jaccard 绑定、对既有 canonical event/timed storyboard 的引用式排程、planned/compiled/runtime/rendered 四层证据分离，以及 event-level result bundle。

本阶段不声称完成语义绑定方法，也不声称已经测得最终 MP4 中对象的可见区间。所有运行的 `run_manifest.json` 均声明 `uses_external_model=false`、`model=null`。

## 可复现运行

- 运行目录：`datasets/research_generation_v2/dry_run/20261005-8ef5b2c-b-local-v0.1/`
- 提交版本：`8ef5b2c9bd02dd8addcaffbae579fefebb7443a1`
- 案例：`lesson_002`、`lesson_004`、`lesson_007`、`lesson_011`、`lesson_012`
- 输入：各案例既有 `segment_context.json`、`machine_observations.json` 与 `manifest.json`；其 SHA-256 记录在各自 `result_bundle/run_manifest.json`。
- 输出：每案例均具有 `binding_predictions.json`、`event_schedule_predictions.json`、`runtime_comparison.json`、`rendered_evaluation.json`、`signaling_audit.json`、`metrics.json`、`failures.json`。

本次产物由 `src/textbook2video/research/experiment.py::run_local_dry_run` 写入；Pilot v1 的适配由 `PilotV1Adapter` 完成。绑定方法为 `binding_baselines.py::lexical_jaccard_bind`，不是论文拟议的语义方法。

## 汇总结果

| 指标 | 结果 | 可以说明什么 | 不能说明什么 |
|---|---:|---|---|
| 案例数 | 5 | 结果包可在多个既有案例上运行 | 不是正式统计样本 |
| 命题候选数 | 272 | 适配器能导出可绑定的候选记录 | 候选边界或 KP 链接正确 |
| lexical 绑定数 | 238 | 本地 baseline 可产生可审计的绑定/弃权输出 | 视觉与讲解语义正确 |
| canonical events | 169 | 可把绑定引用到已有事件，而不新造第二条 timeline | 命题与事件语义匹配 |
| planned→compiled MAE | 0.000 s | 当前输入中计划时间被编译层保留 | 渲染或学习者所见时间正确 |
| compiled→runtime MAE | 0.057347 s（case-macro） | 已有 runtime trace 可度量脚本执行偏差 | 对象在 MP4 中实际何时可见 |
| runtime coverage | 0.968333（case-macro） | 多数 canonical event 在 trace 中有执行记录 | 最终成片的可见性 |
| target resolution rate | 0.968333（case-macro） | trace 中 target lookup 的技术解析率 | target 在视觉上、语义上正确 |
| rendered coverage | 0.0 | 当前缺少可用的最终可见区间证据 | 不能计算 onset/window overlap 或作时间语义结论 |

5 个案例共出现 179 条 failure/evidence-gap 记录：169 条 `render_unobservable`、5 条 `missing_runtime_event`、5 条 `unresolved_target`。这些是当前产物暴露出来的证据边界或技术问题，不自动等价于教学原则违规。

## 已实现的本地接口

- `contracts/proposition_visual_binding.schema.json`：绑定报告的可审计 schema。
- `contracts/event_evaluation.schema.json`：event-level 四层时间评价 schema。
- `semantic_binding.py::build_binding_report`：保留 bound/abstained 与候选排序。
- `dynamic_planner.py::build_event_schedule`：复用 canonical event；只有该时间缺失才使用 span-ratio fallback，并在结果中标示。
- `event_evaluator.py::evaluate_events`：禁止把 planned 或 runtime start 填成 rendered visibility；只有存在可接受窗口 gold 时才判断 early/late/correct。
- `signaling_policy.py::audit_signaling`：识别 explicit highlight/focus/dim 与可能过量信号；这是规则 proxy，不是教学效果证明。
- `metrics.py::aggregate_case_metrics`：按 case-macro 汇总，避免只报 event 微平均。

## 尚未完成且不能提前宣称的部分

1. **命题与知识点 gold**：Pilot v1 当前导出的 proposition boundary/KP link 是机器候选；尚不能用来评估绑定语义准确率。
2. **成片可见区间**：runtime trace 只证明脚本侧事件/target lookup，不能证明对象在连续 MP4 中可见、无遮挡或持续足够时间。`rendered_visible_start_sec/end_sec` 因此保持 `null`。
3. **语义时序正确性**：没有 human/gold acceptable window 时，`semantic_temporal_label` 必须保持 `not_evaluated`，不可用触发时间替代。
4. **论文方法和模型基线**：local lexical baseline 不能替代拟议 semantic binding，也不能替代 Direct LLM/VLM binding 或 Direct VLM judge。

## 后续边界

下一阶段首先需要冻结少量人工 gold（命题、合理时间窗、target/visual relation）并补充连续 MP4 的可观察性证据；其后才能形成正式评价。若要执行 Direct LLM/VLM binding、模型式 semantic binding、Direct VLM judge 或 PresentAgent 的模型运行，必须先获得使用 LLM/VLM 的明确许可。

现有三层人工证据流程见 `docs/研究/Pilot_v1_三层时间证据实验说明.md`：它明确规定计划层、runtime 层与成片层不可混写。
