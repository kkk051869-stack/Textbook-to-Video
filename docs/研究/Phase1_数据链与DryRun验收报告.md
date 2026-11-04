# Phase 1 数据链与 Dry Run 验收报告

日期：2026-11-03
分支：`codex/visual-acquisition-handoff-20261030`
检查基线：`1a667a607ffee0a8d94c915b059b8b45757a9fbf`（与远端相同）
G0 契约：`research-generation-v2-v0.1`

## 结论

**Phase 1 未通过，状态为 PARTIAL/BLOCKED。** 当前只有一份可用的独立真实教材文档 `lesson_002`。现有 P0 侧车包含真实来源、命题图和视觉决策；但研究版导出只把 legacy 内容按规则投影为结构化字段，未把 P0 语义关系接入同一 G0 事件链。单文档 Dry Run 的五种结构化产物可以通过 G0 Schema，时间表却与渲染器实际编译结果明显不一致，编译、runtime 和 rendered evidence 也没有进入这份 G0 Dry Run。

本轮发现并修复一个直接导致真实 storyboard 投影违反冻结 Schema 的重复 ID 引用问题。G0 v0.1、冻结教材、Gold、baseline 和实验条件均未修改。

## 工作区与证据范围

- 检查的目标 worktree 为 `D:\Code\vibe coding\Textbook-to-Video-worktrees\visual-acquisition-handoff-20261030`；分支和 HEAD 与上述记录一致，开始时干净。
- 另一个主工作区位于不同分支且含有无关文件，本轮未修改。没有切换、回退、提交或推送分支。
- 已阅读目标 worktree 的 `AGENTS.md`、AB 执行规程、研究计划、G0 冻结说明、当前交接卡及 A 线 v4.2 标注协议。
- 本轮没有发出 LLM、VLM、图像生成、云 TTS、审核健康检查或录制请求。development 预检只读取凭据是否存在，不发送请求。

## A. Phase 1 验收矩阵

状态定义：PASS 为真实证据满足该项；PARTIAL 为只完成一部分；BLOCKED 为缺输入或依赖；FAIL 为已有证据显示实现结果不符合要求；NOT_VERIFIED 为未能检查。

| 检查项 | 已有实现 | 真实验证证据 | 状态 | 剩余问题 |
|---|---|---|---|---|
| G0 v0.1 Schema 与 Mock | Draft 2020-12 Schema、独立动画 trace Schema、冻结 Mock 包及跨文件测试 | 冻结 Mock 8 类产物和关联测试通过；本轮真实输入生成的 source/plan/script/storyboard/timed 5 个产物也都通过 Schema | PASS（接口与结构） | 结构有效不代表命题或教学语义正确 |
| feature flag 与 legacy 兼容 | `T2V_RESEARCH_GENERATION_V2` 默认关闭；关闭时 dual-write helper 提前返回 | 临时目录验证：关闭时 storyboard 字节不变且无 v2 sidecar；开启时生成 4 个 sidecar，均过 Schema | PASS | 开启后的内容仍是 bootstrap 投影 |
| 教材来源与知识命题 | P0 source evidence、proposition graph；legacy v2 helper | `lesson_002` 原文 SHA 与 P0 source evidence 一致；P0 有 24 个 source unit、49 个 knowledge proposition、55/55 来源引用可解析 | PARTIAL | P0 命题状态仍为 `LLM_PROPOSED_SOURCE_GROUNDED_PENDING_HUMAN_REVIEW`；G0 helper 把整篇教材变为 1 个 source unit、`document.sha256=null`、没有导入已存在的教材图片 |
| 旁白命题与 span | P0 graph 保存精确 span；G0 helper 用句子切分构造 span | P0 的 35/35 narration proposition span 与冻结 script 精确相符；44/44 P0 narration→knowledge 引用可解析 | PARTIAL | P0 sidecar 未迁移进 G0；G0 helper 得到 32 条句子命题并按序号映射到 knowledge proposition，属于 bootstrap，不是语义绑定 |
| 视觉需求决策 | P0 visual decisions；G0 plan 中有 `visual_support` 字段 | P0 的 35 条决策覆盖 35 条 narration proposition：none 18、reuse 5、retrieve 3、generate 9 | PARTIAL | 决策未经人工复核；G0 legacy helper 输出均为 uncertain，未消费 P0 决策 |
| visual element / event | G0 storyboard projection 将 legacy 元素与动画映射为稳定格式 ID | 真实冻结 storyboard 的 65 个动画目标均存在；投影后 65/65 event target 可解析，Schema 通过 | PARTIAL | 每个元素和事件被赋予整段全部命题；`source_refs` 为空。元素/事件 ID 当前由序号生成，未证明插入/重排后稳定；这不等于 proposition-to-element 的语义绑定 |
| planned 时间与 renderer 编译时间 | G0 `build_timed_storyboard_v2` 读 `animations[].trigger_at_sec`；renderer 用 `animation_gen.build_slide_timelines` 编译 | 65 个 v2 planned event 对比 renderer canonical timeline：仅 10/65 在目标、动作、时刻上完全相同；55/65 不同。canonical action 为 show 63、highlight 2；v2 全部为 show。v2 event ID 与编译 event ID 交集为 0/65 | FAIL | v2 builder 忽略 renderer 优先读取的 `timeline[]`，两个 highlight 丢失且计划时刻偏移；runtime event 无法匹配 G0 planned IDs |
| compiled / runtime / rendered evidence | G0 Schema、旧 runtime trace Schema、保守的 `write_render_evidence` | 目标分支代码中未找到 `compiled_timeline_v2` 生产函数。普通开发运行中虽有 12 段 MP4 和 73 个 runtime event，但该 trace 有 367 个 G0 animation trace Schema 错误，且不与本次 G0 事件 ID 对应 | BLOCKED | 不能将普通运行的 MP4/trace 当作本 G0 Dry Run 的下游证据；没有同一 case 的 compiled/runtime/rendered 证据链 |
| 3–5 份独立真实文档 Dry Run | 冻结数据集 manifest | `ab-real-lessons-dev-v1` 仅列一个独立 case：`lesson_002`；10/10 manifest 文件 hash 均匹配。页面、运行版本和 mock 不计为新文档 | BLOCKED | 还缺至少 2 份满足来源与导出要求的独立教材文档；track A 侧车本身也未列入冻结 dataset manifest |

## B. 单文档 Dry Run 结果

### 输入与产物

- 真实来源：`datasets/research_generation_v2/frozen/ab-real-lessons-dev-v1/cases/lesson_002/source/lesson_002.md`、`source.pdf`、`source.json` 和教材图 `fig7-6_区块链数据结构.png`。source hash 为 `83b16211331fde3deebccb2260a221d0e9ac27ae58719332302768a8dd64ef1c`；冻结 dataset manifest 列出的 10 个文件 hash 全部匹配。
- 现有 P0 侧车：`source_evidence` v0.1、`proposition_graph` v1.0、`visual_decisions` v2.0。其 source hash 与冻结原文相符，但三个 P0 侧车没有包含在 dataset manifest 的文件列表中；多个记录中的 `raw_path`、`storyboard_path` 和 `lesson_plan_path` 指向旧 worktree 绝对路径，不具可移植性。
- 本轮 G0 bootstrap Dry Run 输出在 `datasets/research_generation_v2/dry_run/20261103-1a667a6-phase1-r4/cases/lesson_002/`。`dry_run_manifest.json` 记录输入/输出 hash；`validation.json` 记录跨文件检查；`p0_sidecar_validation.json` 记录现有 P0 证据的引用覆盖与人工状态；`legacy_runtime_timeline_comparison.json` 记录时间比较。
- G0 投影结果：1 个 source unit、0 张 source image、5 个 knowledge point / 5 个 knowledge proposition、10 个 narration segment / 32 个 narration proposition、65 个 visual element、65 个 visual event。5 种标准产物均通过 G0 Schema；source refs、span、target 和 storyboard→timed event ID 的结构检查未发现悬空引用。
- `source_units_v2.json` 的文档 hash 是 null，source image 数量为 0，尽管冻结来源包含 hash 可验证的教材图。Schema 接受这些值，因此 Schema 通过不能代替来源完整性验收。

### P0 实际侧车的覆盖与状态

- Source evidence 有 24 个文本 source unit、1 张本地教材图。P0 graph 的 49 个 knowledge proposition 有 55 条 source reference，55/55 指向现有 source unit；35 个 narration proposition 有 43 条 source reference，43/43 可解析。
- 35 个 narration proposition 的 44 条 knowledge proposition link 均可解析；35/35 span 与冻结旁白严格匹配。所有 knowledge/narration 命题均标为待人工复核的 LLM proposal。
- 35 个 visual decision ID 与 35 个 narration proposition 完全覆盖，但它们是模型建议，不是人工确认。P0 冻结包没有 proposition-to-element/event 计划，因此不能拿这些决策证明事件绑定正确。
- 冻结 storyboard 有 65 个元素与 65 个动画记录，所有动画目标存在。元素目标通过不证明视觉对象与具体命题语义匹配。

### 时间、编译与视频

`build_timed_storyboard_v2` 使用动画数组触发时刻；实际 renderer 在 `timeline[]` 非空时优先编译 timeline。对这份冻结页面逐事件比较，canonical 编译的 65 个事件与 v2 planned 的 65 个事件只有 10 个在目标、动作和开始时刻上完全一致。65 个 v2 event ID 与 renderer 生成的 65 个 runtime event ID 没有交集。此后即使 `write_render_evidence` 读取到 runtime trace，也无法按这些 ID 关联 planned event。

工作区中存在普通开发版 MP4 `.local/ordinary-course/20261102-full-course-dev-v2/run-03/video/lesson_002-full-course-dev.mp4` 和 73 条 runtime trace；该运行使用 12 个派生页，包含已修改的课程 storyboard，不属于本次 10 页冻结输入到 G0 sidecar 的同一数据链。本轮没有重新渲染、解码、听看该视频，也没有将其用于 G0 rendered evidence。

### 失败现场

- 初始投影发现知识命题 ID 被重复写入元素引用，导致 65 个元素违反 Schema 的 `uniqueItems`。失败产物和记录保存在 `20261103-1a667a6-phase1/cases/lesson_002/`。
- 初始直接脚本受 `.venv` editable install 指向旧 worktree 的影响；后续 run 目录保留了导入路径错误及一次诊断映射错误的现场，不纳入最终通过证据。最终 r4 已显式设置 `PYTHONPATH=src` 并在 manifest 记录实际模块路径。

## C. 修复与验证记录

- 修改 `src/textbook2video/research/proposition_schema.py`：投影段内 knowledge proposition IDs 时按首次出现顺序去重，满足冻结 Schema 的 unique ID 约束。
- 修改 `tests/test_research_generation_v2.py`：新增一个多句旁白重复指向同一知识命题的真实回归，验证投影唯一且完整 storyboard 通过 G0 Schema。
- 新增本报告；未修改 G0 v0.1、冻结教材、Gold、baseline、P0 协议或默认生产策略。
- 定向测试：6 个相关测试文件，`49 passed`。Development 预检：`scripts/check_research_g0_starter.ps1 -Mode development -AllowDirty` 通过，预检内部 `33 passed`。静态检查：`ruff check src/textbook2video/research/proposition_schema.py tests/test_research_generation_v2.py` 通过。
- 预检提示本 shell 的 PATH 中未找到 ffmpeg/ffprobe；本轮不需要 rendering，因此没有尝试视频验证。未运行全量测试。

## D. Phase 2 Pilot Readiness

| 能力 | 当前状态 |
|---|---|
| Visual Support Need / Retrieval Need 操作定义 | A 线 v4.2 协议定义了 visual support、retrieval、visual function、边界和来源证据；它本身不涵盖 B 线绑定与时间判定 |
| 标注包字段 | `pilot_export.py` 能生成独立的 A/B 空白文件，但当前模板没有明确的 `retrieval_need`、候选 appropriateness、`visual_function` 和独立 binding label；也没有完整的 rendered outcome 标签。现有 `visual_applicability` / `visual_relation` 不能自动视为这些字段的等价物 |
| Time / Signaling | 有时间窗口、observed visibility、signal applicability/label 和 target 字段；信号自身的可接受窗口与整体 rendered outcome 字段仍需对齐研究计划 |
| 两人独立存储 | 导出代码能分别写 `annotator_A.json` 与 `annotator_B.json`，但目标 worktree 中没有正式、可用的双盲标注包或已完成的独立 A/B 标注 |
| Agreement / adjudication | Agreement 模块可计算部分分类 κ、时间窗口 IoU、目标 Jaccard，并报告分歧；它不计算 retrieval_need、visual_function、appropriateness 或来源证据一致性，也不要求所有必填字段完整或两人行集合完全匹配后才返回 READY。模块明确不负责 adjudication；没有可替代人工 adjudication 的正式工作流 |
| 现有 30 条 Gold | 全局分布为 none 28、source-sufficient 1、extra-support-needed 1；retrieval 为 no 29、generation-candidate 1。`lesson_002` 有 7 条，但与当前 49 条 P0 graph knowledge proposition 的 exact-text match 为 0/7。7 个 ID 字符串虽相同，文本却不匹配，因此不能按 ID 合并或作为当前 graph 的 crosswalk |

**Pilot Ready：否。** 现有 Gold 不能作为双人一致性证据，也不能用来证明类别覆盖；当前 G0 timeline 与 runtime 未接通；导出模板和 agreement 还未覆盖研究计划声明的全部标注维度。进入正式 Pilot 前至少需要完成下节第 1–4 项，并由两名独立标注者完成 20–30 条命题盲标。之后按计划检查 proposition boundary agreement ≥0.80、核心类别 κ/α ≥0.67；未达到时按预注册规则收缩问题，不伪造或预设通过。

## E. 下一阶段最小任务

| 优先级 | 目标与当前缺口 | 预计模块 | 完成标准 | 需要真实模型调用 | 研究计划对应 |
|---|---|---|---|---|---|
| 1 | 让 v2 events/timing 对齐 renderer 的 canonical timeline；持久化稳定 element/event ID，并补 compiled→runtime ID 交叉验证 | `proposition_schema.py`、`animation_gen.py`、`pipeline/orchestrator.py`、相关定向测试 | 同一输入的目标、action、planned time 和 runtime target 全量一致；不再出现 55/65 mismatch 或 0/65 ID overlap；flag 关闭时 legacy 行为一致 | 否 | Phase 1 导出链 / 四层时间证据 |
| 2 | G0 source export 纳入真实文件 hash、paragraph/page locator 和图片清单；P0 sidecar 使用可移植相对路径并进入可核验 manifest | `proposition_schema.py`、pipeline source/visual metadata 接线、Dry Run manifest | source 文档与图片均可 hash 复核；引用有真实 locator；不再以全篇单 unit 代替细粒度证据 | 否；如需新语义判定则另行审批 | Phase 1 source→knowledge proposition |
| 3 | 将 Dry Run 扩展到 3–5 份独立教材文档，且每份保留输入 hash 与真实 sidecar 状态 | `datasets/research_generation_v2/dry_run/`、snapshot/export 入口 | 每份文档逐层覆盖 source、KP、narration、element/event、timed、compiled、runtime；不足的阶段明确 abstain/block，不混用 mock | 仅当其余文档没有可复用命题图时才可能需要，执行前另行确认预算 | Phase 1 多文档 Dry Run Gate |
| 4 | 对齐正式标注字段、A/B 空白包、完整性门禁和人工 adjudication 记录 | `pilot_export.py`、`annotation_agreement.py`、Pilot annotation schema/说明 | 能记录研究计划全部标签；拒绝缺字段、重复/缺失 proposition、行集合不匹配；分别保存盲标、agreement 和人工 adjudication | 否 | Phase 2 Pilot preparation |
| 5 | 重新确认 Gold 与当前 proposition 的 crosswalk，选择有正类、边界与 abstain 样本的 20–30 条并完成双盲 | 数据选择清单、人工 packet、agreement/adjudication 记录 | 不按重复 ID 猜测对齐；两名标注者独立完成；报告类别边际分布、逐字段 agreement、阈值与收缩决定 | 否 | Phase 2 formal Pilot Gate |

## 验收问题的直接回答

1. **Phase 1 是否通过？** 否，当前为 PARTIAL/BLOCKED。
2. **实际验证多少份独立真实文档？** 1 份：`lesson_002`。普通开发运行和 mock 都未另计。
3. **哪些字段仍只是 bootstrap 或推断？** 当前 G0 v2 投影中的 lesson-plan→source、sentence split→knowledge proposition、按序号映射、整段 proposition→所有 visual element/event，全部是 bootstrap；P0 graph/visual decisions 虽为真实模型侧车，仍待人工复核，不是 gold。
4. **现有 v2 命题、来源和事件证据足以支持下一阶段实验吗？** 不足。P0 的 source/KP/narration 引用与 span 有真实结构证据，但尚未接到语义 element/event、canonical timeline、compiled/runtime/rendered G0 evidence。
5. **Phase 2 正式双人 Pilot 能否开始？最小阻塞是什么？** 不能。至少需修复时间与 ID 对齐、补齐 3–5 份真实 Dry Run 数据、对齐 annotation/agreement 字段与完整性规则，并对现有 Gold 做文本级 crosswalk 或重新标注后再冻结 Pilot packet。
