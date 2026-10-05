# B 线交付审计与交接说明

## 结论

B 线的本地接口、5 案例 dry run、Direct LLM binding baseline 和结果对照已完成；**成片级语义时序评价尚不可完成**，原因是 Pilot v1 没有对象级连续 rendered visibility interval，也没有命题—目标的 human/gold 关系。该限制已在结果中显式保留，未用 planned 或 runtime 时间替代。

## 启动任务对应

| 启动任务 | 证据 | 状态 |
|---|---|---|
| G0 跨文件引用与 mock 适配 | `experiment.py::_pilot_inputs`，`tests/test_research_generation_contract.py` | 完成 |
| lexical/Jaccard binding | `binding_baselines.py::lexical_jaccard_bind`，`semantic_binding.py::build_binding_report` | 完成 |
| proposition→element→event 格式 | `contracts/proposition_visual_binding.schema.json`、`dynamic_planner.py::build_event_schedule_report` | 完成 |
| planned/compiled/runtime 分层 | `event_evaluator.py::evaluate_events`、5 个 `runtime_comparison.json` | 完成 |
| rendered evidence 的 onset/overlap/missing/wrong-target | `event_evaluator.py::evaluate_events` 支持；当前产物全部标为 `render_unobservable` | 已实现，缺少可计算输入 |
| 3–5 案例 dry run 与 ID 断链记录 | `datasets/research_generation_v2/dry_run/20261005-8ef5b2c-b-local-v0.1/` | 完成 |
| Direct LLM baseline | `cloud_binding.py::build_cloud_binding_report`，5 案例 `cloud_runs/` | 完成 |
| Direct VLM judge | 单帧 JSON 契约试跑已完成；批量成片 judge 未作为正式指标运行 | 仅试跑 |

## 结果包

本地结果包完整包含：`run_manifest.json`、`binding_predictions.json`、`event_schedule_predictions.json`、`runtime_comparison.json`、`rendered_evaluation.json`、`metrics.json`、`failures.json`、`README.md`。

5 个案例总计 169 个 canonical event。planned→compiled 的 case-macro MAE 为 `0.0 s`；compiled→runtime 的 case-macro MAE 为 `0.057347 s`。这两项仅反映计划/脚本执行层。

## 不可消隐的缺口

1. 169 个 event 均没有最终对象可见区间，故 rendered coverage 为 `0.0`；不能报告 onset error 或 window IoU。
2. 5 个 event 在现有 trace 中出现 target unresolved，5 个 event 缺少 runtime execution。它们已写入 `failures.json`，不应通过伪造 element ID 达成“全解析”。
3. Pilot proposition/KP links 是 `MACHINE_CANDIDATE_NOT_GOLD`，不能作为语义绑定 accuracy 的真值。

## 可供 A 或后续实验直接消费的输入

- `cloud_runs/20261005-qwen3-32b-awq-v0.1/*/binding_predictions.json`：Direct LLM binding；记录 raw response、模型和 prompt version。
- `dry_run/20261005-8ef5b2c-b-local-v0.1/*/result_bundle/`：本地 lexical baseline 与四层技术证据。
- 新增 A 输出只需遵守冻结 ID/字段契约；B 的 scheduler/evaluator 无需依赖 A 的实现细节。

## 继续前的最小前置条件

要完成成片级语义评价，最少需要：

1. 为少量事件提供连续 MP4 可见性 observation（`rendered_visible_start_sec/end_sec`）；
2. 为同一小样本冻结 proposition 的 acceptable window 与正确 target/visual relation；
3. 再运行 evaluator，才可判断 `correct/early/late` 并比较 LLM、lexical 与后续方法。

在这之前，B 线可以安全交接，但不能把任何覆盖率、VLM 单帧观察或 runtime trace 写成教学语义准确率。
