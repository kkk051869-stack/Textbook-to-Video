# A → B 评测接口与交接说明

更新日期：2026-09-10
评测分支：`codex/eval-harness-v2`
冻结审核标识：`A-eval-owner`

## 当前 A 侧状态

- 已正式冻结 `pilot3_lesson_001`、`pilot3_lesson_002`、`pilot3_lesson_004`。
- 数据目录：`D:\text python\Textbook-to-Video-master\TextbookEval-assets\pilot3-candidate-20260909`。
- Baseline：`D:\text python\Textbook-to-Video-master\TextbookEval-assets\baseline-C01`。
- 冻结记录：`D:\text python\Textbook-to-Video-master\TextbookEval-assets\pilot3-freeze-record.json`。
- 正式本地报告：`D:\text python\Textbook-to-Video-master\TextbookEval-assets\eval-runs\pilot3-C01-formal-local-v1`。
- 正式模式已完成 3 Case：无 Case 级错误、无缺失 evidence 的 Issue。
- 当前报告为 `partial`，预期缺项是新的 Text Judge 结果和 B 的 `animation_trace.json`。
- GitHub 中的可移植副本位于 `datasets/pilot3/cases/` 和 `datasets/pilot3/artifacts/`。
- 本地生成的 `eval-runs/` 与冻结审计临时文件不应提交，可从上述目录重新生成。

交接时运行 `git rev-parse HEAD` 记录最终 commit，不使用启动包快照代替工作树。

## B 需要提供的公共评测产物

B 不修改 A 的报告 Schema。每个 Case/系统输出一个 `animation_trace.json`，遵循：

- `contracts/animation_trace.schema.json`
- `contracts/animation_event.schema.json`

必须记录 `case_id`、`lesson_id`、逐事件 `event_id`、`slide`、`target`、
`target_resolved`、`executed`、`effect_realized`、`status`、`planned`、`actual`、
`error_code` 和 `message`。target 未命中、未知 effect、降级和实际 timing 不能只写日志。

## A 接收 B 产物

把 B 的 trace 放入对应 Case artifacts 目录，再登记相对路径和 SHA-256：

```powershell
python -m textbook2video.eval.attach_artifacts `
  --case <case_manifest.json> `
  --artifacts <case_artifacts> `
  --artifact animation_trace=animation_trace.json `
  --system-id <candidate-system-id>
```

随后运行正式评测，不使用 `--allow-candidate`：

```powershell
t2v eval --dataset <frozen-pilot3> --artifacts <candidate-artifacts> --output <eval-output> --run-id <run-id>
t2v eval-compare --baseline <baseline-eval> --candidate <candidate-eval> --output <comparison>
```

## 数据隔离边界

- B 只需要公开 source、storyboard、HTML、layout 和 trace 接口。
- `private/annotation.json` 和 `private/heldout_questions.json` 不得进入生成提示。
- Video-QA Audience 只看关键帧和生成文本；Reference Scorer 才能读取标准答案。
- A 不直接修改动画 Runtime；B 如需改公共 Schema，先在合并前提出。
- 当前不计算跨指标统一总分。

## 合并与上云顺序

1. A、B 各自在本地分支通过相关测试。
2. 在新的集成分支合并 A/B，不重置或覆盖旧项目。
3. 本地跑全量测试和 3 Case deterministic Gate。
4. A 登记 B 的 trace，生成 JSON、Markdown、CSV 和 review index。
5. 本地生成 before/after comparison，确认无布局、媒体和时长退化。
6. 以上通过后，才把同一集成 commit 放到云端新 worktree。
7. 云端先跑 1 Case Smoke，再跑正式 3 Case Text Judge、VLM readability 和两阶段 Video-QA。

云端旧仓库 `/ai/data/repos/Textbook-to-Video` 不覆盖；新代码使用
`/ai/data/repos/Textbook-to-Video-v2`，输出统一放在 `/ai/data/textbook-to-video`。

## 交接验收清单

- [ ] B 提供 3 Case 修复前/后 trace。
- [ ] trace 全部通过公共 Schema。
- [ ] target miss、degraded 和 runtime error 可定位到 slide/event。
- [ ] A/B 合并后全量测试通过。
- [ ] 3 Case 正式本地 Runner 无 Case 级错误。
- [ ] 每个失败或低分 Issue 至少有一个 evidence path。
- [ ] before/after 报告不包含统一总分。
- [ ] 本地验收完成后再创建云端 Smoke Test。
