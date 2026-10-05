# Research Generation v2 数据目录

本目录承载论文研究新增的结构化产物和交接 mock，不替代 `datasets/pilot3/` 或 `datasets/research_event_alignment/pilot_v1/`。

```text
research_generation_v2/
├─ README.md
├─ mock_v0.1/                         # G0 冻结的接口样例，只在版本升级时修改
│  ├─ package_manifest.json
│  └─ cases/<case_id>/
│     ├─ source_units.json
│     ├─ lesson_plan.json
│     ├─ script_v2.json
│     ├─ storyboard.json
│     ├─ storyboard_timed.json
│     ├─ compiled_timeline.json
│     ├─ animation_trace.json
│     └─ render_evidence.json
├─ dry_run/                           # 3–5 份真实文档 dry run；不得覆盖 mock
│  └─ <run_id>/cases/<case_id>/...
└─ experiments/                       # 正式实验结果
   └─ <experiment_id>/<run_id>/...
```

规则：

- `mock_v0.1` 是接口测试数据，不是人工 gold，也不得计入论文统计。
- 新实验一律写新 `<run_id>`；禁止原地覆盖 frozen mock、Pilot v1 或正式结果。
- 所有路径在 manifest 中使用相对路径和 `/` 分隔符。
- 运行时事件继续使用既有 `contracts/animation_trace.schema.json`；最终 MP4 可见区间写入 `render_evidence.json`，二者不能互相替代。
- 字段、ID 和所有权以 `docs/研究/G0_研究数据契约冻结说明.md` 为准。

