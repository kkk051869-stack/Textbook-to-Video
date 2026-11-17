# Phase 1 事件证据链差异归因与修复

**结论状态：部分通过 / 最终媒体证据阻塞。** 本报告仅核对 `lesson_002`，没有进入 Phase 2。跨阶段事件映射和动作语义已修复；来源门禁前 65/65 个事件与 Renderer 的目标、动作、计划时间一致。严格来源门禁将 10 个事件及其依赖在编译前过滤，其余 55 个事件在浏览器 Runtime 中全部执行。两次录制均未通过媒体时钟校准，没有 MP4，因此不能通过要求 Final Video 证据的 Phase 1 对应验收项。

本次基线为分支 `codex/visual-acquisition-handoff-20261030`、HEAD `1a667a607ffee0a8d94c915b059b8b45757a9fbf`。冻结输入没有修改。新的运行证据位于 `datasets/research_generation_v2/dry_run/20261103-1a667a6-event-chain-r2/cases/lesson_002/`；原始 `phase1-r4` 保留未覆盖。

## 输入与证据版本

同一冻结输入的关键 SHA-256：

| 输入/产物 | SHA-256 |
|---|---|
| 冻结数据集清单 | `5b3c1fb444dac9ec1823a58adeb4e5988226369e73c2f19ed4a3f125e1f641c0` |
| `lesson_002.md` | `83b16211331fde3deebccb2260a221d0e9ac27ae58719332302768a8dd64ef1c` |
| 冻结 `baseline/storyboard.json` | `f9a66d016659549d10e51004048f3824d74db7d70bd188e0c405c57893b61824` |
| 来源图片 `fig7-6` | `9269bc182103e2237174ee08355ef544002f2ec493dcdef0d06be08ca2228c14` |
| 新 `storyboard_v2.json` | `8b12c3421ade8255a7b825d1259ecfa7c49dd2d0315e426ac3d816d851fc926d` |
| 新 `timed_storyboard_v2.json` | `61e3c95d50b1772ff7e60e55edf82cbcbeefbd915f8c982bab23fd08bf38a8e3` |
| G0 v0.1 `compiled_timeline_v2.json` | `a318b7e175a55c23a4d2bb93e7daeedca504bbf8b7ec05f07795dee5f578e1c8` |
| Renderer HTML | `99107a5a0468655f2b2a6fc0a8a7f75a591c333aa902b9d5c10e9409dd26e7b0` |
| 浏览器 Runtime Trace（首轮） | `aca304ac1237b78dd9280e857440f83d968fd114e954742f60612c415a974540` |

上游 `source_units_v2.json`、`lesson_plan_v2.json`、`script_v2.json` 从旧 r4 按字节复用，哈希分别为 `7010c060…649aa`、`e8aab238…60604`、`1b3a68de…105f9`。本轮重新投影 Storyboard 和时间线；旧、新产物共享冻结 Markdown 与 Storyboard 哈希。完整输入、代码、产物哈希记录见 [`run_manifest.json`](../../datasets/research_generation_v2/dry_run/20261103-1a667a6-event-chain-r2/cases/lesson_002/run_manifest.json)。逐事件机器可读交叉表见 [`event_crosswalk.json`](../../datasets/research_generation_v2/dry_run/20261103-1a667a6-event-chain-r2/cases/lesson_002/render/event_crosswalk.json)。

## 65 个事件的差异归因

旧 r4 的“10/65 完全一致”实际表示：**忽略事件 ID，只比较目标、动作和时间**，有 10 项三者相同；不是 10 个 ID 相同，也不是 55 个事件无法追踪。旧 G0 ID `lesson-002-evt-NNN` 与 Renderer ID `页号-aNN` 采用不同命名空间，所以原始字符串交集为 0/65。按 `segment_id + 已解析 legacy target + 同目标出现次序` 建立确定映射后，65 个事件均可对应，目标不匹配 0、映射缺失 0、未知 0。

逐项重算旧 r4 与 Renderer 的目标/动作/计划时间：

| 分类（互斥） | 数量 | 说明 |
|---|---:|---|
| 仅 ID 名称不同，目标/动作/时间一致 | 10 | 纯命名空间差异，不是教学事件错误 |
| 仅时间不同 | 53 | 旧 G0 投影时间与 Renderer 计划时间不同 |
| 动作和时间均不同 | 2 | `highlight` 被旧 G0 投影成 `show`，同时时间不同 |
| 目标不同 / 未找到目标 | 0 | 目标映射完整 |
| 无法判断是否同一事件 | 0 | 按段、目标和同目标顺序完成确定映射 |

本轮修复后的逐阶段数量：

| 阶段 | 数量/结果 |
|---|---:|
| 计划事件 | 65 |
| 成功映射到规范 Renderer 计划 | 65/65，ID 唯一 |
| 来源门禁前规范目标/动作/时间一致 | 65/65 |
| 有意动作降级 | 0 |
| 修复后非预期动作变化 | 0 |
| 编译前来源门禁过滤 | 10 |
| 实际 Renderer 编译 | 55 |
| Runtime 执行 | 55/55，Runtime ID 唯一 |
| 编译后 Runtime 失败 / unsupported | 0 |
| 最终 MP4 中已观察 | 0/65，MP4 未生成 |

55 个非完全匹配事件中，**0 个是单纯 ID 映射差异，55 个是真实跨产物计划差异**：53 个时序差异，2 个动作加时序差异。旧时间与规范时间绝对误差：最小 `0s`、中位数 `3.91s`、最大 `9.96s`、平均 `4.0408s`。这里证明的是旧导出与 Renderer 计划数据不一致；由于冻结案例没有可复用音频，不能据此断言这些旧时间相对旁白的教学时序是否正确。

逐事件归因表中，动作列依次列出旧 r4 G0 投影、规范请求动作、门禁后的实际编译动作、Runtime 动作；时间列比较旧 G0 与规范计划。被门禁过滤的行在 compiled/runtime 列留空；这 10 个事件的门禁前规范编译动作保存在 [`canonical_compiled_before_source_filter.json`](../../datasets/research_generation_v2/dry_run/20261103-1a667a6-event-chain-r2/cases/lesson_002/g0/canonical_compiled_before_source_filter.json)。Renderer ID 仅在事件通过来源门禁并进入实际编译后填写。“后续状态”中的 `filtered_before_compile` 不代表 Runtime 失败。

| # | 段 | G0 ID → Renderer ID | 目标 | 动作：旧G0→requested→compiled→runtime | 时间：旧→计划（Δ秒） | 旧差异归因 | 本轮状态 |
|---:|---:|---|---|---|---:|---|---|
| 1 | 1 | `lesson-002-evt-101` → `1-a01` | `e1 / lesson-002-el-101` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 2 | 1 | `lesson-002-evt-102` → `1-a02` | `e2 / lesson-002-el-102` | show→show→show→show | 0.300→0.500（+0.200） | 时序差异 | executed；有 DOM 可见观察 |
| 3 | 1 | `lesson-002-evt-103` → `1-a03` | `e3 / lesson-002-el-103` | show→show→show→show | 8.170→1.000（-7.170） | 时序差异 | executed；有 DOM 可见观察 |
| 4 | 2 | `lesson-002-evt-201` → `2-a01` | `e1 / lesson-002-el-201` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 5 | 2 | `lesson-002-evt-202` → `2-a02` | `e2 / lesson-002-el-202` | show→show→show→show | 6.610→1.500（-5.110） | 时序差异 | executed；有 DOM 可见观察 |
| 6 | 2 | `lesson-002-evt-203` → `2-a03` | `e3 / lesson-002-el-203` | show→show→show→show | 6.910→3.000（-3.910） | 时序差异 | executed；有 DOM 可见观察 |
| 7 | 2 | `lesson-002-evt-204` → `2-a04` | `e4 / lesson-002-el-204` | show→show→show→show | 9.810→4.500（-5.310） | 时序差异 | executed；有 DOM 可见观察 |
| 8 | 2 | `lesson-002-evt-205` → `2-a05` | `e5 / lesson-002-el-205` | show→show→show→show | 10.110→6.000（-4.110） | 时序差异 | executed；有 DOM 可见观察 |
| 9 | 3 | `lesson-002-evt-301` → `3-a01` | `e1 / lesson-002-el-301` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 10 | 3 | `lesson-002-evt-302` → `—（门禁前未编译）` | `e2 / lesson-002-el-302` | show→show→—→— | 2.830→0.500（-2.330） | 时序差异 | 门禁前过滤 |
| 11 | 3 | `lesson-002-evt-303` → `3-a02` | `e3 / lesson-002-el-303` | show→show→show→show | 5.650→2.000（-3.650） | 时序差异 | executed；有 DOM 可见观察 |
| 12 | 3 | `lesson-002-evt-304` → `3-a03` | `e4 / lesson-002-el-304` | show→show→show→show | 8.480→3.500（-4.980） | 时序差异 | executed；有 DOM 可见观察 |
| 13 | 3 | `lesson-002-evt-305` → `3-a04` | `e5 / lesson-002-el-305` | show→show→show→show | 11.310→4.500（-6.810） | 时序差异 | executed；有 DOM 可见观察 |
| 14 | 3 | `lesson-002-evt-306` → `—（门禁前未编译）` | `e6 / lesson-002-el-306` | show→highlight→—→— | 14.130→6.000（-8.130） | 动作+时序差异 | 门禁前过滤 |
| 15 | 3 | `lesson-002-evt-307` → `—（门禁前未编译）` | `e7 / lesson-002-el-307` | show→highlight→—→— | 16.960→7.000（-9.960） | 动作+时序差异 | 门禁前过滤 |
| 16 | 4 | `lesson-002-evt-401` → `4-a01` | `e1 / lesson-002-el-401` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 17 | 4 | `lesson-002-evt-402` → `4-a02` | `e2 / lesson-002-el-402` | show→show→show→show | 2.000→1.000（-1.000） | 时序差异 | executed；有 DOM 可见观察 |
| 18 | 4 | `lesson-002-evt-403` → `4-a03` | `e3 / lesson-002-el-403` | show→show→show→show | 4.000→2.000（-2.000） | 时序差异 | executed；有 DOM 可见观察 |
| 19 | 4 | `lesson-002-evt-404` → `4-a04` | `e4 / lesson-002-el-404` | show→show→show→show | 6.010→3.000（-3.010） | 时序差异 | executed；有 DOM 可见观察 |
| 20 | 4 | `lesson-002-evt-405` → `4-a05` | `e5 / lesson-002-el-405` | show→show→show→show | 8.010→4.000（-4.010） | 时序差异 | executed；有 DOM 可见观察 |
| 21 | 4 | `lesson-002-evt-406` → `4-a06` | `e6 / lesson-002-el-406` | show→show→show→show | 10.010→5.000（-5.010） | 时序差异 | executed；有 DOM 可见观察 |
| 22 | 4 | `lesson-002-evt-407` → `4-a07` | `e7 / lesson-002-el-407` | show→show→show→show | 12.010→6.000（-6.010） | 时序差异 | executed；有 DOM 可见观察 |
| 23 | 4 | `lesson-002-evt-408` → `—（门禁前未编译）` | `e8 / lesson-002-el-408` | show→show→—→— | 14.020→7.000（-7.020） | 时序差异 | 门禁前过滤 |
| 24 | 5 | `lesson-002-evt-501` → `5-a01` | `e1 / lesson-002-el-501` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 25 | 5 | `lesson-002-evt-502` → `5-a02` | `e2 / lesson-002-el-502` | show→show→show→show | 2.970→1.000（-1.970） | 时序差异 | executed；有 DOM 可见观察 |
| 26 | 5 | `lesson-002-evt-503` → `5-a03` | `e3 / lesson-002-el-503` | show→show→show→show | 3.270→2.000（-1.270） | 时序差异 | executed；有 DOM 可见观察 |
| 27 | 5 | `lesson-002-evt-504` → `5-a04` | `e4 / lesson-002-el-504` | show→show→show→show | 3.570→3.000（-0.570） | 时序差异 | executed；有 DOM 可见观察 |
| 28 | 5 | `lesson-002-evt-505` → `5-a05` | `e5 / lesson-002-el-505` | show→show→show→show | 5.710→4.000（-1.710） | 时序差异 | executed；有 DOM 可见观察 |
| 29 | 5 | `lesson-002-evt-506` → `5-a06` | `e6 / lesson-002-el-506` | show→show→show→show | 6.910→5.000（-1.910） | 时序差异 | executed；有 DOM 可见观察 |
| 30 | 5 | `lesson-002-evt-507` → `5-a07` | `e7 / lesson-002-el-507` | show→show→show→show | 7.210→6.000（-1.210） | 时序差异 | executed；有 DOM 可见观察 |
| 31 | 5 | `lesson-002-evt-508` → `—（门禁前未编译）` | `e8 / lesson-002-el-508` | show→show→—→— | 7.510→7.000（-0.510） | 时序差异 | 门禁前过滤 |
| 32 | 6 | `lesson-002-evt-601` → `6-a01` | `e1 / lesson-002-el-601` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 33 | 6 | `lesson-002-evt-602` → `6-a02` | `e2 / lesson-002-el-602` | show→show→show→show | 2.210→1.000（-1.210） | 时序差异 | executed；有 DOM 可见观察 |
| 34 | 6 | `lesson-002-evt-603` → `6-a03` | `e3 / lesson-002-el-603` | show→show→show→show | 4.430→2.000（-2.430） | 时序差异 | executed；有 DOM 可见观察 |
| 35 | 6 | `lesson-002-evt-604` → `6-a04` | `e4 / lesson-002-el-604` | show→show→show→show | 6.640→3.000（-3.640） | 时序差异 | executed；有 DOM 可见观察 |
| 36 | 6 | `lesson-002-evt-605` → `6-a05` | `e5 / lesson-002-el-605` | show→show→show→show | 8.850→4.000（-4.850） | 时序差异 | executed；有 DOM 可见观察 |
| 37 | 6 | `lesson-002-evt-606` → `6-a06` | `e6 / lesson-002-el-606` | show→show→show→show | 11.060→5.000（-6.060） | 时序差异 | executed；有 DOM 可见观察 |
| 38 | 6 | `lesson-002-evt-607` → `6-a07` | `e7 / lesson-002-el-607` | show→show→show→show | 13.280→6.000（-7.280） | 时序差异 | executed；有 DOM 可见观察 |
| 39 | 6 | `lesson-002-evt-608` → `—（门禁前未编译）` | `e8 / lesson-002-el-608` | show→show→—→— | 15.490→7.000（-8.490） | 时序差异 | 门禁前过滤 |
| 40 | 7 | `lesson-002-evt-701` → `7-a01` | `e1 / lesson-002-el-701` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 41 | 7 | `lesson-002-evt-702` → `—（门禁前未编译）` | `e2 / lesson-002-el-702` | show→show→—→— | 0.300→1.000（+0.700） | 时序差异 | 门禁前过滤 |
| 42 | 7 | `lesson-002-evt-703` → `7-a02` | `e3 / lesson-002-el-703` | show→show→show→show | 10.120→2.500（-7.620） | 时序差异 | executed；有 DOM 可见观察 |
| 43 | 7 | `lesson-002-evt-704` → `7-a03` | `e4 / lesson-002-el-704` | show→show→show→show | 10.420→3.500（-6.920） | 时序差异 | executed；有 DOM 可见观察 |
| 44 | 7 | `lesson-002-evt-705` → `7-a04` | `e5 / lesson-002-el-705` | show→show→show→show | 11.680→4.500（-7.180） | 时序差异 | executed；有 DOM 可见观察 |
| 45 | 7 | `lesson-002-evt-706` → `7-a05` | `e6 / lesson-002-el-706` | show→show→show→show | 15.460→5.500（-9.960） | 时序差异 | executed；有 DOM 可见观察 |
| 46 | 8 | `lesson-002-evt-801` → `8-a01` | `e1 / lesson-002-el-801` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 47 | 8 | `lesson-002-evt-802` → `8-a02` | `e2 / lesson-002-el-802` | show→show→show→show | 0.300→0.800（+0.500） | 时序差异 | executed；有 DOM 可见观察 |
| 48 | 8 | `lesson-002-evt-803` → `8-a03` | `e3 / lesson-002-el-803` | show→show→show→show | 4.230→1.500（-2.730） | 时序差异 | executed；有 DOM 可见观察 |
| 49 | 8 | `lesson-002-evt-804` → `8-a04` | `e4 / lesson-002-el-804` | show→show→show→show | 4.530→2.500（-2.030） | 时序差异 | executed；有 DOM 可见观察 |
| 50 | 8 | `lesson-002-evt-805` → `8-a05` | `e5 / lesson-002-el-805` | show→show→show→show | 8.840→3.000（-5.840） | 时序差异 | executed；有 DOM 可见观察 |
| 51 | 8 | `lesson-002-evt-806` → `8-a06` | `e6 / lesson-002-el-806` | show→show→show→show | 9.140→4.000（-5.140） | 时序差异 | executed；有 DOM 可见观察 |
| 52 | 9 | `lesson-002-evt-901` → `9-a01` | `e1 / lesson-002-el-901` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 53 | 9 | `lesson-002-evt-902` → `9-a02` | `e2 / lesson-002-el-902` | show→show→show→show | 4.940→0.800（-4.140） | 时序差异 | executed；有 DOM 可见观察 |
| 54 | 9 | `lesson-002-evt-903` → `9-a03` | `e3 / lesson-002-el-903` | show→show→show→show | 5.240→1.500（-3.740） | 时序差异 | executed；有 DOM 可见观察 |
| 55 | 9 | `lesson-002-evt-904` → `9-a04` | `e4 / lesson-002-el-904` | show→show→show→show | 5.540→2.500（-3.040） | 时序差异 | executed；有 DOM 可见观察 |
| 56 | 9 | `lesson-002-evt-905` → `9-a05` | `e5 / lesson-002-el-905` | show→show→show→show | 11.380→3.000（-8.380） | 时序差异 | executed；有 DOM 可见观察 |
| 57 | 9 | `lesson-002-evt-906` → `9-a06` | `e6 / lesson-002-el-906` | show→show→show→show | 13.570→4.000（-9.570） | 时序差异 | executed；有 DOM 可见观察 |
| 58 | 10 | `lesson-002-evt-1001` → `10-a01` | `e1 / lesson-002-el-1001` | show→show→show→show | 0.000→0.000（+0.000） | 仅 ID 命名差异 | executed；有 DOM 可见观察 |
| 59 | 10 | `lesson-002-evt-1002` → `—（门禁前未编译）` | `e2 / lesson-002-el-1002` | show→show→—→— | 10.260→1.500（-8.760） | 时序差异 | 门禁前过滤 |
| 60 | 10 | `lesson-002-evt-1003` → `—（门禁前未编译）` | `e3 / lesson-002-el-1003` | show→show→—→— | 10.560→2.500（-8.060） | 时序差异 | 门禁前过滤 |
| 61 | 10 | `lesson-002-evt-1004` → `—（门禁前未编译）` | `e4 / lesson-002-el-1004` | show→show→—→— | 10.860→2.700（-8.160） | 时序差异 | 门禁前过滤 |
| 62 | 10 | `lesson-002-evt-1005` → `10-a02` | `e5 / lesson-002-el-1005` | show→show→show→show | 11.160→3.500（-7.660） | 时序差异 | executed；有 DOM 可见观察 |
| 63 | 10 | `lesson-002-evt-1006` → `10-a03-1` | `e6 / lesson-002-el-1006` | show→show→show→show | 11.460→5.000（-6.460） | 时序差异 | executed；有 DOM 可见观察 |
| 64 | 10 | `lesson-002-evt-1007` → `10-a03-2` | `e7 / lesson-002-el-1007` | show→show→show→show | 11.760→5.200（-6.560） | 时序差异 | executed；有 DOM 可见观察 |
| 65 | 10 | `lesson-002-evt-1008` → `10-a03-3` | `e8 / lesson-002-el-1008` | show→show→show→show | 12.060→5.400（-6.660） | 时序差异 | executed；有 DOM 可见观察 |

## `highlight → show` 的根因

`build_storyboard_v2()` 和 `build_timed_storyboard_v2()` 旧实现只遍历 `animations[]`：动作读取 `animation.action`，缺失时默认为 `show`；时间读取 `trigger_at_sec`。但 `build_slide_timelines()` 对非空 `timeline[]` 优先，采用 `at_sec`，并展开多目标及 stagger。第 3 段两个旧 G0 事件 `lesson-002-evt-306/307` 在 `animations[]` 中只有 `zoomIn`/`pulse` 效果、没有 action；Renderer 实际采用 `timeline[]` 中的 `highlight`。因此降级发生在**旧 G0 导出投影**，不是 Timing 覆盖，也不是 Renderer 或 Runtime 把 `highlight` 改成 `show`。

本轮导出器改为调用 Renderer 的规范编译器，并用稳定目标映射复用现有 G0 事件 ID；Timed Storyboard 和新增的 G0 v0.1 `compiled_timeline_v2` 同样投影规范 action/time。没有修改冻结 G0 schema。Runtime trace 增加兼容诊断字段 `requested_action`、`compiled_action`、`runtime_action`、`source_collection`；事件未执行时 `runtime_action` 为 `null`，不再伪装成已执行请求动作。旧 ID 与 Renderer 内部 ID 仍各自保留，通过交叉表关联。

## 同一次运行的证据链

```text
冻结 Storyboard SHA f9a66d…61824
  → G0 storyboard_v2 / timed_storyboard_v2（65 个计划事件）
  → G0 compiled_timeline_v2（来源门禁前 65 个；目标/动作/时间 65/65 匹配 Renderer）
  → 既有素材来源门禁（10 个事件及其依赖，在编译前明确过滤）
  → 实际 Renderer 编译（55 个事件）
  → 浏览器 Runtime Trace（55/55 executed，55/55 action 与编译动作相同）
  → Final MP4（未生成；媒体时钟校验失败）
```

被拒图片有哈希且来源 ID 可追溯，但现有审核记录的 `visual_relevance_verdict` 为 `MISSING`，不满足既有图片接入门槛。门禁拒绝了 6 个教材图片目标及 4 个依赖标注事件，共 10 个计划事件；拒绝原因在 [`render_exclusions.json`](../../datasets/research_generation_v2/dry_run/20261103-1a667a6-event-chain-r2/cases/lesson_002/render/render_exclusions.json) 留痕。未绕过审核，也未将其伪记为 ACCEPT。其余 55 个实际编译事件都通过 Runtime：运行时实际时刻相对编译计划偏差为 `13–30ms`，中位数 `23ms`；55 个事件均有浏览器 DOM 可见观察记录，没有 unsupported、缺目标或 Runtime 失败事件。该可见性是 HTML/DOM 证据，不是 MP4 证据。

### 录制结果

冻结 `lesson_002` 没有音频文件；本轮没有调用 TTS，以下录制均为静音诊断尝试。浏览器按 10 页、总计划 180 秒运行，两次的 Runtime 校验都通过，但现有严格媒体校准阈值为 `0.12s`，因此没有生成 MP4：

| 尝试 | 请求时长 | Runtime 结束 | 解码测量内容时长 | 结果 |
|---|---:|---:|---:|---|
| 首轮 | 180.0s | 校验通过 | 180.2s | 偏差 0.2s，校准拒绝 |
| 增加末页停留的复核 | 180.1s | 180102.1ms | 181.0333s | 偏差约 0.933s，校准拒绝 |

没有放宽校准阈值，没有把 raw WebM 当作 MP4，也没有生成 Final MP4 帧观察。因此 Final MP4 可关联并实际观察的事件为 **0/65**；实际观察事件窗口、最终字幕/音轨和片尾只能标记为未验证。两次 raw WebM、clock、Runtime Trace 与详细错误保留在运行目录，录制汇总见 [`recording_attempts.json`](../../datasets/research_generation_v2/dry_run/20261103-1a667a6-event-chain-r2/cases/lesson_002/render/recording_attempts.json)。

本轮外部模型、VLM、图像生成和 TTS 调用均为 0。首次运行目录 r1 曾因 Windows 控制台编码错误中断报告写入；r2 修正控制台编码后完成离线编译和 Runtime 验证。原始失败现场均保留。

## 修改和验证

代码改动限于事件投影、编译追踪及定向测试：

- `src/textbook2video/research/proposition_schema.py`：从 Renderer 规范事件构造 G0 Storyboard / Timed Storyboard / Compiled Timeline；保留现有 G0 v0.1 schema 和事件 ID，建立确定的目标映射。
- `src/textbook2video/animation_gen.py`：编译结果附带 requested/compiled action 与事件来源集合，原有编译动作不变。
- `src/textbook2video/templates/slide-controller.js`：Runtime trace 区分 requested、compiled、runtime action；仅成功执行时填写 runtime action。
- 定向测试覆盖时间线优先、逗号多目标/stagger、G0 schema 校验，以及浏览器内 `highlight` 事件确实保留 action 并应用 `event-highlight` class。

验证结果：

- 定向测试：`tests/test_research_generation_v2.py`、`tests/test_animation_layout_repair.py`、`tests/test_local_visual_composition.py`：**73 passed**。
- development 预检：`scripts/check_research_g0_starter.ps1 -Mode development -AllowDirty`：**33 passed，预检通过**；预检提示 PATH 未发现 ffmpeg/ffprobe。本次采集显式使用已安装 ffmpeg 路径，但媒体时钟仍不满足校准；本机 ffprobe 缺失。
- Ruff 默认检查：触及的既有文件中报告 4 项旧行格式问题（`animation_gen.py` 的 3 项、`test_animation_layout_repair.py` 的 1 项）；未对无关旧行做重排。对触及 Python 文件忽略既有 `E501/I001` 后：通过。
- `git diff --check`：通过。
- 未运行全量测试、真实模型/API、TTS、新图片生成或全课程流程；未提交、未推送。

## 验收问题与剩余阻塞

1. **55 个不完全匹配如何归因？** 其中 0 个是单纯 ID 差异；53 个是旧 G0 与 Renderer 的时序差异，2 个同时有 action/time 投影差异；经确定映射后未知数为 0。65 个命名不同的 ID 已有跨阶段关联规则。
2. **`highlight → show` 根因？** 旧 G0 投影只读 `animations[]` 且缺失 action 默认 `show`；Renderer 采用明确包含 `highlight` 的 `timeline[]`。不是 Runtime 静默降级。
3. **G0 到 Runtime 是否有可靠事件对应关系？** 有：来源门禁前的 65 个 G0 计划事件均能确定映射到 Renderer 规范事件；实际通过门禁编译的 55 个均有唯一 Runtime trace ID 且成功执行。其余 10 个在编译前因来源审核门禁而被拒，不能声称到达 Runtime。
4. **真实 Final Video 证据能否关联计划事件？** 不能。本轮没有通过校准的 MP4，因此无 MP4 帧、可见窗口或人工视频观察证据；DOM trace 不替代视频证据。
5. **`lesson_002` 能否单独通过 Phase 1 对应验收项？** 不能，状态仍是 **PARTIAL/BLOCKED**。事件映射、编译语义和 55 个 Runtime 执行证据达到可核验；10 个事件受来源审核门禁阻止，且 Final MP4 及音画观察缺失。

下一步只需继续处理已定位的两个边界：为 `fig7-6` 补齐可信的语义审核绑定（或维持拒绝并明确内容去向），以及诊断录制器媒体时钟/本机 ffprobe 环境后，使用同一 HTML 与输入重新完成校准录制和 MP4 帧检查。本报告不启动其他案例或 Phase 2。
