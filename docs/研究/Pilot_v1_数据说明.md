# Pilot v1 数据说明

## 1. 数据范围

Pilot v1 冻结 5 个真实生成案例：`lesson_002`、`lesson_004`、`lesson_007`、`lesson_011`、`lesson_012`。它们均来自现有 pipeline 历史产物，没有为实验重新生成视频、修改默认 prompt、改 timing 或注入错误。

研究数据入口：`datasets/research_event_alignment/pilot_v1/pilot_index.json`。

不可变基线快照位于本地忽略目录：`.local/data/research_runs/pilot_v1/baseline/<case>/`。快照通过 SHA-256 记录来源和产物，写入器拒绝覆盖已有 snapshot。annotation package 是面向人工观察的导出层，不替代基线快照。

## 2. 总量

| 项目 | 数量 |
|---|---:|
| cases | 5 |
| segments | 45 |
| proposition candidates | 272 |
| elements | 284 |
| animations | 284 |
| raw timeline items | 277 |
| runtime events | 284 |
| source paragraphs | 74 |
| knowledge point candidates | 34 |
| sampled three-layer events | 25 |
| event-neighborhood JPG frames | 125 |

Proposition candidates 来自 deterministic subtitle chunks，只是人工划分的起点；34 个 knowledge points 也是现有数据引用/候选，不是人工确认的 proposition-level binding。

## 3. 目录与文件

### 顶层

- `pilot_index.json`：case 列表、总量与整体状态；
- `cases/<case>/manifest.json`：单 case 计数、coverage、字段责任与文件索引；
- `tasks/source_ablation/`：双人交叉条件任务；
- `tasks/three_layer/`：计划、运行、成片三层证据任务。

### 单 case

- `source.json`：教材段落和可用 source image 引用；
- `lesson_context.json`：lesson/KP 上下文与 source 候选关系；
- `segment_context.json`：narration、storyboard elements/animations/timeline 等 segment 上下文；
- `machine_observations.json`：从已有产物提取的客观字段、runtime trace 与候选链接；
- `media/final.mp4`：冻结的最终视频；
- `media/animation.html`：冻结的 HTML；
- `media/frames/`：25 个抽样 event 的邻域帧；
- `three_layer_frame_index.json`：event、候选时间与帧路径索引；
- `annotations/annotator_A.json`、`annotator_B.json`：完全独立的人工标注模板。

## 4. 字段责任边界

| 类型 | 示例 | 性质 |
|---|---|---|
| 客观预填 | case/segment/event/element ID、narration、timeline、runtime trace、audio duration、source paragraph、文件路径 | 从现有产物复制或确定性提取；不等于教学 gold |
| 机器候选 | subtitle chunk boundary、lexical KP/source link、candidate score、event neighborhood | 导航和候选；明确标为 `MACHINE_CANDIDATE_NOT_GOLD` |
| 人工 gold | proposition 边界、KP/source binding、visual necessity/correctness、acceptable window、observed visibility、temporal/signaling labels | 只能由独立人工标注 |

系统没有自动填写 pedagogical gold。空白模板中人工标签保持 `null`、`[]` 或空字符串；manifest 的 `gold_validation.status` 为 `EMPTY`。

`machine_observations.json` 还为每个 segment 提供 `richness_observation`：`element_count`、`animation_count`、`timeline_event_count`、`events_per_10_sec`、`signaling_event_count`。这些只是确定性计数；普通 `show` 不计作 signaling，也不会由计数自动推出 decorative、irrelevant、redundant 或 overload。

## 5. 可用证据与缺失证据

五个 case 均有：source、narration、elements、animations/timeline、runtime trace、HTML、音频相关 duration 和 final MP4。

明确缺失或受限：

- 五案都没有可证明为 timing 前版本的独立 storyboard；归档中的 `storyboard.json` 与 `storyboard_timed.json` 字节一致，因此标记 `before_timing_storyboard=MISSING`；
- 五案都没有 `sentence_cues.json`，candidate proposition time 来自确定性字幕块，不是 forced alignment；
- 生成时 prompt 的精确 hash 与原始生成 timestamp 缺失；manifest 只记录当前 prompt 参考 hash和 archive mtime，不能冒充生成时证据；
- `lesson_012` 没有 render images；
- 这些运行的 lesson-plan 阶段处于 disabled/复用既有数据状态，因此 KP 是 candidate/reference，不是新运行产生的稳定 provenance chain；
- runtime event time 不是实际 rendered visibility interval，后者必须从 MP4 人工观察；
- 实际 signaling action 仅覆盖 `highlight`/`pulse`，普通 `show` 不自动视为 signaling；没有确认的 focus/dim 样本；
- `lesson_002`、`lesson_011` 虽有 segment 声明 requested `llm`，归档运行记录仍为 deterministic renderer、无 LLM fallback，不能宣称存在已确认 LLM-rendered 页面。

## 6. 各 case 工作量

| case | segments | proposition candidates | elements | animations/runtime events | source paragraphs | KP candidates |
|---|---:|---:|---:|---:|---:|---:|
| lesson_002 | 10 | 64 | 65 | 65 | 15 | 7 |
| lesson_004 | 9 | 50 | 57 | 57 | 10 | 7 |
| lesson_007 | 8 | 38 | 50 | 50 | 21 | 7 |
| lesson_011 | 9 | 70 | 52 | 52 | 18 | 7 |
| lesson_012 | 9 | 50 | 60 | 60 | 10 | 6 |
| **合计** | **45** | **272** | **284** | **284** | **74** | **34** |

## 7. 研究辅助代码

- `src/textbook2video/research/snapshot.py`：只读来源并建立拒绝覆盖的研究快照；
- `src/textbook2video/research/pilot_export.py`：从快照导出客观字段、候选、空白模板和帧；
- `src/textbook2video/research/annotation_agreement.py`：在双人完成后计算一致性；空白或不完整输入返回 NOT_READY，不自动裁决；
- `tests/test_research_pilot.py`：验证 snapshot 不可覆盖、候选与 gold 分离、空白标注不会产生伪一致性结果。

这些文件位于独立 research namespace，不被生产 orchestrator 调用，也不改变 baseline 输出。

## 8. 数据使用限制

- 不得根据 candidate score 自动接受 KP/source relation；
- 不得把 timeline/trace 时间写入 observed visibility；
- 不得把 target missing 自动写成教学违规；
- 不得把 renderer 声明当成真实 fallback 已发生；
- 不得用 A 文件初始化 B 文件；
- 未经人工完成与冻结，不得报告原则违规率、模型性能或一致性数值。
