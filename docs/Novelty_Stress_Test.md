# Textbook-to-Video：Novelty Stress Test / 创新性查重审计

> 审计日期：2026-10-03  
> 范围：2024–2026 为主，必要时追溯更早的理论、评价与视频理解工作。  
> 本文目的：主动寻找能够否定拟议创新的证据，不为既定方案辩护。  
> 状态词：**已做过**、**部分做过**、**相邻但不同**、**没有公开证据**、**本轮检索未找到**严格区分。“本轮检索未找到”不等于“首次”。

## 0. 审计结论先行

### 0.1 严格结论

当前宽泛方案不能作为独立贡献。以下主张均已有直接近邻，继续使用会面临高 novelty risk：

1. “用 Mayer/CTML 原则指导 AI 教学视频生成”：PedaCo-Gen 已把 12 条 Mayer 原则操作化为脚本与视觉描述约束；CogniPresent、LLM2Manim、Teaching Step by Step 和 PIVOT 又分别覆盖了 CTML 合同、Segmenting/Signaling/Temporal Contiguity、教学规划与验证。[PedaCo-Gen](https://arxiv.org/html/2602.19623)、[CogniPresent](https://openreview.net/pdf?id=PinJSxPLUD)、[LLM2Manim](https://arxiv.org/html/2604.05266)、[PIVOT](https://arxiv.org/html/2609.24083)
2. “把教学原则写成机器可执行 contract/schema”：PedaCo-Gen 已有结构化原则约束，CourseBlueprint 已有 typed instructional contract，CogniPresent 明确使用 CTML-guided generation contracts。[CourseBlueprint](https://arxiv.org/html/2606.20608)
3. “在最终成片上自动检查 Mayer 原则”：When Saying No 已对最终视频自动计算 Coherence、Redundancy、Temporal Contiguity、Modality 和 Image Quality；EduVideoBench 又把六条 Mayer 原则纳入专家评分和确定性认知负荷指标。[When Saying No](https://arxiv.org/html/2608.19812)、[EduVideoBench](https://arxiv.org/html/2605.26918)
4. “checker → repair → rerender”：PIVOT 已公开多模态 verification harness、迭代代码修复与重渲染；TeachMaster、Code2Video、LASEV、Teaching Step by Step 也都实现不同粒度的生成后反馈和修复。因此，闭环本身不是创新。[PIVOT](https://arxiv.org/html/2609.24083)、[Code2Video](https://arxiv.org/html/2510.01174)
5. “教材/课程材料 grounding”：Dynamic Learning Solutions 直接从 NCERT 教材 PDF 生成多场景视频；CourseBlueprint 从课程语料检索并保存 source chunk/slide IDs；VCEval 也把教材与教学目标用于视频质量评价。[Dynamic Learning Solutions](https://arxiv.org/html/2609.14408)、[VCEval](https://arxiv.org/abs/2407.12005)
6. “教学视频 benchmark / 原则合规指标”：TheoremExplainBench、VisualEDU、MMMC、PedagogyBench、VCEval 与 EduVideoBench 已覆盖多个 benchmark 形态；仅再收集一批视频并给整体分数，不能构成强贡献。[TheoremExplainAgent](https://aclanthology.org/2025.acl-long.332/)、[VisualEDU](https://aclanthology.org/2025.findings-emnlp.889/)、[PedagogyBench](https://aclanthology.org/2026.findings-acl.614/)

### 0.2 经反例攻击后仍可能成立的窄问题

本轮检索未找到一项工作同时完成下列任务：

> 在**教材有据**的生成视频中，以**讲述命题—视觉对象—渲染时间区间**为基本单位，给出 Temporal Contiguity / Signaling 违规的**时间定位、教材证据、目标对象和校准置信度**，并由人工金标验证。

这不是“原则 checker”的换名。它把评价单位从整段/整片分数改为可证伪的、source-conditioned event-level diagnosis；它要求模型区分“画面出现了相关东西”和“教材所支持、当前命题所需的视觉证据在正确时刻可见且被正确指向”。但是，它仍面临 AutoCue、When Saying No、EduVideoBench、CourseBlueprint 和一般音视频 temporal grounding 的联合压力，novelty 只能评为 **MEDIUM-HIGH**，不能宣称“首次”。

### 0.3 是否只是把已有模块拼起来

如果工作只是把 CourseBlueprint 的 source ID、PedaCo-Gen 的原则 prompt、When Saying No 的视频指标和 PIVOT 的修复循环接起来，结论是：**engineering integration，不足以支撑论文主贡献**。

要超过集成，至少要有一项可独立检验的新研究产物：

- 新任务：source-conditioned event-level pedagogical violation localization；
- 新标注协议：命题、对象、时间边界、原则类型、证据、严重度/置信度；
- 新方法：显式利用教材证据链进行事件级诊断，而非整片 VLM 打分；
- 新实证：证明聚合指标/VLM judge 在事件级定位上失败，或证明局部修复存在可量化的副作用。

## 1. 审计方法与证据规则

### 1.1 检索与复核方法

- 原始来源优先：ACL Anthology、ACM/CHI、IEEE/CVF、Springer、arXiv、OpenReview 与官方 GitHub。
- 对每项能力检查正文的方法、实验、附录和公开仓库；只有摘要可见的论文一律保守标为 UNKNOWN/PARTIAL。
- 从 PedaCo-Gen 追踪同作者后续 When Saying No；从 PresentAgent 追踪 PresentAgent-2；从 LASEV、Code2Video、PIVOT、PedagogyBench、CourseBlueprint 的 related work/references 反向发现 TheoremExplainAgent、VisualEDU、KCVR、Teaching Step by Step、TeachMaster 等。
- 对 2026 年 8–9 月论文做同题名、作者和能力词 forward search。由于论文很新，引用计数本身不可靠；“未发现 citing paper”不作为 novelty 证据。

### 1.2 判定规则

- **YES**：正文明确实现，且有实验或系统验证。
- **PARTIAL**：只实现能力的一部分、粒度不同，或仅以 prompt/人工环节实现。
- **NO**：论文明确输入/任务不包含该能力，或明确把它列为限制/未来工作。
- **UNKNOWN**：公开材料未披露，不能由系统宣传语推断。

### 1.3 对项目现状的限定

根据已有调研和项目文档，Textbook-to-Video 已有教材解析、learning objectives / knowledge points、source refs、narration、element IDs、animation target/trigger/timeline、音频时长和最终 HTML/MP4 技术检查。这些是研究基础，不自动构成论文创新。当前项目尚无公开证据证明已有：命题级标注、原则适用条件、类型化违规、事件级人工金标、校准 detector、原则特异修复及 repair-safety 指标。

## 2. 强制近邻重新核查

| 工作 | 原文核查后的能力边界 | 对本项目的威胁 |
|---|---|---|
| [PedaCo-Gen](https://arxiv.org/html/2602.19623) | 12 条 Mayer 原则被操作化为脚本/视觉描述约束；LLM review 提建议，教育者决定修改；23 名教育者、3 个主题、13 项原则评分；无公开的最终成片事件级自动 detector、自动局部修复或学习者结果。 | **极高**：否定宽泛“原则→生成约束”。 |
| [When Saying No Makes Better Videos](https://arxiv.org/html/2608.19812) | 脚本人工 gate + 成片自动 gate；自动评价 coherence、redundancy、temporal contiguity、modality、image quality；14 个视频自动比较、23 名教育者主观评价；作者明确未测学习结果。公开正文未披露对象级定位和自动修复。 | **极高**：否定宽泛“成片原则检测”。 |
| [LASEV](https://arxiv.org/html/2602.11790) | EVS 中间表示含画面、叙述和动画映射；多 agent critics 与失败重生成；1003 个视频和专家评价；未把 Mayer 违规定义成可验证的事件级 taxonomy。 | 高：否定“结构化音画规划+critic+重生成”。 |
| [LLM2Manim](https://arxiv.org/html/2604.05266) | CTML-aware 规划，显式覆盖 segmentation、signaling、temporal contiguity；narration cues 与 visual events 用 timing markers 连接，可调整 timing/重生成局部；100 人学习实验报告学习增益。 | **极高**：否定宽泛“时序+信号原则指导生成与学习效果”。 |
| [PIVOT](https://arxiv.org/html/2609.24083) | 教学目标、先备知识、概念解释、视觉计划、例题、诊断题组成 storyboard；shot-level narration/visual/duration；多模态 verification 检查 layout、factual consistency、cognitive clarity，并迭代修复 Manim 代码；32 名教师评价，但不是学习者实验。 | **当前最大系统级威胁**：已覆盖 pedagogy→plan→render→verify→repair。 |
| [Teaching Step by Step](https://link.springer.com/chapter/10.1007/978-3-032-29788-4_73) | 公开摘要称 Planner 受 Segmenting/Signaling 约束，AST 静态检查与 Vision Auditor 双循环验证；240 次试验中报告 93.8% render success 和 93.7% auditor pass。正文受限，细粒度字段与修复指标记为 UNKNOWN。 | 高：直接威胁“原则约束+视觉审计”；需精读补充材料。 |
| [CourseBlueprint](https://arxiv.org/html/2606.20608) | ConceptTree、StyledTree、EnrichedScript、CourseBlueprint 构成 typed instructional contract；23 讲/1116 对 slide-transcript 课程语料；narration 保存 corpus chunk IDs，支持 slide ID override；无原则违规定位或修复。 | **极高**：否定宽泛“typed contract”和课程 grounding/provenance。 |
| [TeachMaster](https://arxiv.org/html/2601.04204) | 代码作为语义中间媒介；基于 code event anchors、script semantic units 和 speaking rate 注入时间戳；含 render-debug、同步和布局修复；未声称 Mayer 操作化。 | 高：否定“事件锚点同步+技术修复”本身。 |
| [PresentAgent](https://aclanthology.org/2025.emnlp-demos.58/) | 长文档→分段→幻灯片→讲稿/TTS→精确按音频时长合成；PresentEval 评 content fidelity、visual clarity 和 audience comprehension。 | 中：否定通用 document-to-narrated-video 与粗粒度音画同步。 |
| [PresentAgent-2](https://arxiv.org/html/2605.11363) | query-driven research，融合文本、图片、GIF、视频，输出 slides/scripts/audio/video；PresentEval-2 用 VLM quiz 和主观维度评价。 | 中高：多媒体素材选择与视频评价更加拥挤。 |
| [Dynamic Learning Solutions](https://arxiv.org/html/2609.14408) | NCERT 教材 PDF + query，经 RAG 生成多场景脚本、图像/动态视频和 TTS，并做基于时长的场景对齐；公开定量实验有限。 | 高：否定通用“textbook-to-video”。 |
| [Ellysia](https://link.springer.com/chapter/10.1007/978-3-032-29788-4_60) | 12 项 research-informed checklist；LLM/VLM 联合分析 transcript/visual/audio，输出分数、解释、报告和 highlight clips；摘要报告与人工成对排序一致。 | 高：否定宽泛“可解释的成片教学质量评价”。 |
| [PedagogyBench](https://aclanthology.org/2026.findings-acl.614/) | 463 个真实教学视频、1852 个教学片段、9260 MCQ + 1852 SAQ；机器预标+专家精炼；评价 4 个认知层级、20 个任务。它是视频理解，不是原则违规生成/修复。 | 中高：否定通用“教学视频理解 benchmark”，但未覆盖 CTML 事件违规。 |
| [Code2Video](https://arxiv.org/html/2510.01174) | Planner–Coder–Critic；occupancy table 将元素 anchor、scale、code line 可索引化；VideoLLM 检测重叠/遮挡/空白并回写代码；ScopeRefine 做 line/block/global 修复；MMMC 与 TeachQuiz。 | **极高**：否定“对象可索引+局部修复+重渲染+教学评价”宽泛主张。 |
| [TheoremExplainAgent](https://aclanthology.org/2025.acl-long.332/) | 240 个定理的 TheoremExplainBench、5 个评价维度；agent 生成最长 5–10 分钟 Manim 解释；主要问题为视觉布局，非 Mayer 违规。 | 中：建立了长视频、benchmark 和多维评价基线。 |
| [VisualEDU](https://aclanthology.org/2025.findings-emnlp.889/) | 面向数学解题视频的 Manim benchmark；meta-prompt、visual/code feedback、模块化工具；指标含 temporal consistency、logical correctness、visual clarity。 | 高：否定通用“教育动画生成+视觉反馈+时间一致性 benchmark”。 |
| [Paper2Video / PaperTalker](https://arxiv.org/abs/2510.05096) | 101 篇论文及作者视频/幻灯片/讲者元数据；生成 slides、cursor、subtitles、speech、talking head；Meta Similarity、PresentArena、PresentQuiz、IP Memory。 | 中高：否定 paper-grounded presentation video 与多通道评价。 |
| [Preacher](https://openaccess.thecvf.com/content/ICCV2025/html/Liu_Preacher_Paper-to-Video_Agentic_System_ICCV_2025_paper.html) | top-down 分解为 key scenes，P-CoT 细粒度规划，再 bottom-up 合成多风格视频；按准确性、专业性、美学与论文对齐评价。 | 中：否定“文档→结构场景→多模态视频”宽泛主张。 |
| [VCEval](https://arxiv.org/abs/2407.12005) | 370 个 K12 视频、教材/课程目标和考试资料；以模拟学习/考试的 QA 框架区分课程质量，结果可定位到教学目标。 | 高：否定“教材参照的教学视频评价”宽泛主张。 |

### 2.1 新发现、必须加入的直接近邻

| 工作 | 新增证据 | 对判断的改变 |
|---|---|---|
| [EduVideoBench](https://arxiv.org/html/2605.26918) | 215 prompts、1070 个生成 MP4、18 名博士专家；K-PK rubric 明确含 signaling、spatial/temporal contiguity、coherence、segmenting、modality；另有 text density、scene rate、speech rate、redundancy 等确定性指标。 | **重大改变**：通用“原则合规 benchmark/metric”不能再主张。 |
| [AutoCue](https://arxiv.org/html/2608.04910) | 从视频变化、OCR、讲述和官方手册构造 evidence bundle；输出 timestamp、ROI、interaction label、evidence、confidence，并生成与 cursor 时空对齐的 cue；30 段视频技术验证及 24 人实验。 | **重大改变**：通用“cue→target/time/evidence/confidence”已被直接实现，Signaling 方向必须限定到生成视频与教材命题。 |
| [CogniPresent](https://openreview.net/pdf?id=PinJSxPLUD) | CTML-guided paper-to-presentation generation contracts，约束 source figures、屏幕文本、叙述互补与 pacing；用自动 proxy/diagnostics 评价。当前为匿名投稿，非归档论文。 | **重大改变**：CTML contract + source-grounded slide/narration 已有明确 prior-art 威胁。 |
| [KCVR](https://aclanthology.org/2026.acl-long.414/) | 把教学视频重构形式化为 SPR；dual-layer epistemic graph、evidence-supported plan、拓扑约束解码；EduStruct 评价 Knowledge Progression Consistency 与 Learning Objective Coverage。 | 中等改变：知识点/先修关系/视觉证据链也不是空白，但任务是已有视频重构而非生成视频违规检测。 |
| [Sci-VBench](https://arxiv.org/abs/2608.09873) | 1253 个专家标注样本、60 个科学主题；评价 prompt grounding、科学/因果正确性、时空一致性和感知质量。 | 中等改变：通用科学视频 fidelity benchmark 已拥挤。 |

## 3. 原子能力撞车矩阵

矩阵选择最可能覆盖拟议贡献的 14 篇工作；其余强制近邻已在第 2 节核查。每格均为状态加一句证据。为可读性，32 项能力拆成四张表。

### 3.1 Grounding 与音画结构（能力 1–8）

| 工作 | 1 Source grounding | 2 Learning objective | 3 Knowledge point | 4 Provenance | 5 Narration proposition | 6 Visual object ID | 7 Visual action/event | 8 Rendered visibility interval |
|---|---|---|---|---|---|---|---|---|
| PedaCo-Gen | NO—输入是主题。 | PARTIAL—脚本有教学目标但未形式化评价。 | PARTIAL—按内容单元组织。 | NO—无来源证据链。 | PARTIAL—有分段讲稿但无命题标注。 | PARTIAL—视觉描述结构化但非稳定对象 ID。 | PARTIAL—描述动画但未建立事件金标。 | UNKNOWN—未披露对象可见区间。 |
| When Saying No | NO—输入不是教材语料。 | PARTIAL—脚本 gate 考察先备与结构。 | PARTIAL—人工审查内容顺序。 | NO—无来源链。 | UNKNOWN—未披露命题单元。 | UNKNOWN—未披露对象 ID。 | PARTIAL—自动指标读取成片动态。 | PARTIAL—Temporal 指标利用视频时间但无对象区间。 |
| LASEV | NO—按 topic 生成。 | PARTIAL—规划教学序列。 | PARTIAL—离散逻辑单元。 | NO—无教材证据。 | YES—EVS 的 N 是离散叙述单元。 | PARTIAL—场景元素可在代码中引用。 | YES—A 映射动画与过渡。 | PARTIAL—代码/等待时间隐式给出区间。 |
| LLM2Manim | NO—按 topic 生成。 | PARTIAL—scene goals 表达局部目标。 | PARTIAL—分段概念结构。 | NO—无教材证据。 | PARTIAL—narration cues 近似命题。 | YES—symbol ledger 维护视觉实体。 | YES—storyboard 定义视觉事件。 | PARTIAL—timing markers 而非实测可见区间。 |
| PIVOT | NO—按 learner topic 生成。 | YES—storyboard 显式含 learning objectives。 | YES—显式 key concepts/先备关系。 | NO—无教材来源链。 | PARTIAL—shot narration 未拆原子命题。 | PARTIAL—shot 有 visual elements 但 ID 机制未充分披露。 | YES—shot-level animations。 | PARTIAL—有 duration constraint，非对象级实测。 |
| Teaching Step | NO—公开摘要为概念到动画。 | PARTIAL—按教学步骤规划。 | PARTIAL—因果有序 transformation steps。 | UNKNOWN—公开材料未披露。 | UNKNOWN—正文受限。 | PARTIAL—AST/视觉审计可指向元素。 | YES—逐步动画是核心单位。 | UNKNOWN—未见对象可见区间。 |
| CourseBlueprint | YES—检索课程 corpus。 | YES—typed blueprint 包含课程目标。 | YES—ConceptTree 显式建模。 | YES—narration 保存 chunk/slide IDs。 | PARTIAL—EnrichedScript 有段落但非命题金标。 | PARTIAL—slide ID 可追踪，内部对象未完整追踪。 | PARTIAL—支持 slide/媒体事件。 | PARTIAL—forced alignment 到 slide，不是对象。 |
| TeachMaster | NO—输入为主题/页面计划。 | PARTIAL—页面承担教学意图。 | PARTIAL—分页面解释知识。 | NO—无 source evidence。 | PARTIAL—script semantic units。 | PARTIAL—代码对象可引用。 | YES—code event anchors。 | PARTIAL—代码时间锚点近似区间。 |
| Code2Video | PARTIAL—external DB 提供参考资产，非教材。 | YES—Planner 围绕 learning topic/objective。 | YES—outline/storyboard 分解知识。 | PARTIAL—资产可追踪但无教材 span。 | PARTIAL—lecture lines 近似命题。 | YES—occupancy table 索引元素/anchor/code line。 | YES—Manim 代码显式事件。 | PARTIAL—代码可推断但未做人类区间标注。 |
| EduVideoBench | NO—prompt 不是教材证据。 | PARTIAL—prompt 有教学意图。 | PARTIAL—题目含目标知识。 | NO—无源文档 provenance。 | NO—不标命题。 | NO—不标对象 ID。 | PARTIAL—对生成 MP4 取帧/指标。 | NO—无对象可见区间金标。 |
| AutoCue | YES—官方手册是操作知识来源。 | NO—不建 lesson objective。 | PARTIAL—操作 label 是程序性知识单元。 | PARTIAL—保存 OCR/手册/画面证据但非教材 span 链。 | YES—ASR 形成 timestamped utterances。 | YES—ROI/cursor/界面目标可定位。 | YES—interaction event 有预定义 label。 | PARTIAL—事件 timestamp 与 cue persistence 可配，但非完整对象区间。 |
| CogniPresent | YES—输入论文并复用 source figures。 | PARTIAL—围绕论文信息传达。 | PARTIAL—阶段化内容选择。 | PARTIAL—保留 source image/evidence，未见完整 span 链。 | PARTIAL—生成 complementary narration。 | PARTIAL—source figure/slide element 可区分。 | NO—主要是 presentation slides。 | PARTIAL—slide duration/pacing 而非对象区间。 |
| PedagogyBench | NO—输入为既有视频。 | PARTIAL—任务涉及教学意图。 | YES—按教学认知内容构造问答。 | NO—无教材来源链。 | PARTIAL—转录与语义注入。 | PARTIAL—视觉证据用于 QA，非稳定 ID。 | PARTIAL—片段级教学事件。 | PARTIAL—有片段边界，非对象可见区间。 |
| Ellysia | NO—评价公开视频。 | PARTIAL—checklist 涉及目标清晰度。 | PARTIAL—从视频内容判断。 | NO—无教材证据链。 | PARTIAL—分析 transcript。 | UNKNOWN—摘要未披露对象 ID。 | PARTIAL—用视听片段诊断。 | PARTIAL—输出 highlight clips，粒度不明。 |

### 3.2 对齐、原则与可观测化（能力 9–16）

| 工作 | 9 Narration span | 10 Proposition→visual | 11 Cue→target | 12 Principle rep. | 13 Applicability | 14 Observable vars | 15 Typed violation taxonomy | 16 Violation localization |
|---|---|---|---|---|---|---|---|---|
| PedaCo-Gen | PARTIAL—讲稿分段但无强制时间 span。 | PARTIAL—脚本与视觉描述成对。 | PARTIAL—Signaling 以约束表达，未显式映射 target。 | YES—12 条 Mayer 原则结构化操作化。 | PARTIAL—prompt 中有情境判断，未形式化。 | PARTIAL—约束可检查但部分依赖 LLM 判断。 | NO—没有错误类型与边界标注。 | NO—不在最终视频定位违规。 |
| When Saying No | PARTIAL—成片指标使用音频/时间。 | PARTIAL—Temporal 指标做聚合对齐。 | UNKNOWN—未披露 cue target 表示。 | YES—五类 CTML 指标显式。 | UNKNOWN—未披露原则适用条件。 | YES—给出可计算的成片维度。 | PARTIAL—维度是类别，不是事件级 taxonomy。 | NO—报告视频级分数，未报告事件位置。 |
| LASEV | PARTIAL—叙述段落进入 EVS。 | YES—EVS 把 N 与 A/画面绑定。 | PARTIAL—critic 可检查强调元素，非明确 cue map。 | NO—未把 Mayer 原则作为类型系统。 | NO—无原则适用条件。 | YES—rule/tool/semantic critics 可观测。 | PARTIAL—critic 类别存在但非教学原则违规。 | PARTIAL—可定位失败 artifact/segment。 |
| LLM2Manim | PARTIAL—cue/timing marker 提供局部时间。 | YES—narration cues 连接 visual events。 | PARTIAL—Signaling 进入 storyboard，未见统一 target schema。 | YES—明确 CTML/三条原则。 | PARTIAL—按场景应用但未形式化条件。 | PARTIAL—timing/ledger 可检查。 | NO—无人工定义违规 taxonomy。 | PARTIAL—drift 可定位到 part/cue。 |
| PIVOT | PARTIAL—TTS 在验证后同步。 | YES—每个 shot 同含 narration 与 visual description。 | PARTIAL—highlights 在视觉计划中，未见显式 target map。 | PARTIAL—引用 Mayer 但三类 verifier 更宽。 | UNKNOWN—无公开适用条件规则。 | YES—layout/factual/cognitive 三类检查。 | PARTIAL—三类 verifier 是粗 taxonomy。 | PARTIAL—shot-level failure 可定位。 |
| Teaching Step | UNKNOWN—公开材料未披露 span。 | PARTIAL—步骤与动画因果对应。 | PARTIAL—Signaling 约束存在，target schema 未公开。 | YES—Segmenting/Signaling 明确约束 Planner。 | UNKNOWN—正文受限。 | YES—AST lint + Vision Auditor。 | PARTIAL—视觉缺陷类别不等于原则 taxonomy。 | PARTIAL—auditor 可定位缺陷，粒度未披露。 |
| CourseBlueprint | YES—forced alignment 提供讲述时间。 | PARTIAL—以 slide/script 粒度对应。 | NO—无 signaling cue target schema。 | PARTIAL—typed instructional contract，不等于 Mayer 表示。 | PARTIAL—persona/style/课程条件被类型化。 | YES—typed fields 和 evaluator 可读取。 | PARTIAL—有 evaluator 失败项，非原则违规 taxonomy。 | PARTIAL—可定位到中间产物/slide。 |
| TeachMaster | YES—semantic units 按 speaking rate 对齐时间。 | YES—叙述由页面/视觉代码条件化。 | PARTIAL—代码事件可触发强调，未形式化 cue target。 | NO—未操作化 Mayer。 | NO—无原则条件。 | YES—event anchors、layout 与 render error 可观测。 | PARTIAL—技术/同步/layout 错误分类。 | YES—定位到页面、事件或代码。 |
| Code2Video | PARTIAL—lecture lines 参与时间流。 | PARTIAL—storyboard line 对应动画 section。 | PARTIAL—visual anchor 是布局 target，不是教学 cue target。 | NO—未采用 Mayer 原则类型。 | NO—无原则适用条件。 | YES—occupancy、anchor、code line 可观测。 | PARTIAL—重叠、遮挡、空白三类视觉问题。 | YES—问题可回溯元素与代码行。 |
| EduVideoBench | NO—无命题时间 span 标注。 | NO—不标 proposition mapping。 | NO—不标 cue target。 | YES—rubric 含六条 Mayer 原则。 | PARTIAL—rubric 说明评分情境，非形式化条件。 | YES—六类 rubric 与六类确定性指标。 | PARTIAL—评分维度而非事件违规类型。 | NO—视频/样本级评分不定位事件。 |
| AutoCue | YES—ASR utterance 有时间戳。 | YES—事件 evidence bundle 对齐附近 narration。 | YES—cue 与 cursor/ROI/interaction target 对齐。 | PARTIAL—CTML/contiguity 指导 cue grammar。 | YES—限定 UI-mediated、可观测反馈事件。 | YES—frame diff、OCR、ROI、narration、manual label。 | NO—interaction label 不是原则违规 taxonomy。 | YES—candidate timestamp 与 ROI 明确定位。 |
| CogniPresent | YES—按认知复杂度设置 pacing。 | YES—slide-aware complementary narration。 | PARTIAL—标签靠近图形，但未报告统一 cue map。 | YES—CTML contract 分 reduce/manage/foster。 | YES—依 visual/concept complexity 施加 pacing/内容约束。 | YES—evidence use、alignment、load-pacing proxies。 | PARTIAL—proxy 维度不是事件违规 taxonomy。 | PARTIAL—主要在 slide/stage 粒度诊断。 |
| PedagogyBench | YES—视频片段与 transcript 对齐。 | PARTIAL—双流语义注入结合音画证据。 | NO—不构造 signaling cue map。 | PARTIAL—认知金字塔而非 Mayer 原则。 | PARTIAL—任务按认知层级适用。 | YES—20 个任务均可评价。 | NO—不是原则违规 taxonomy。 | PARTIAL—答案对应教学片段，非违规边界。 |
| Ellysia | PARTIAL—音频/transcript 联合分析。 | PARTIAL—checklist 评价音画关系。 | UNKNOWN—摘要未披露 cue target。 | PARTIAL—12 项 research-informed checklist。 | UNKNOWN—条目适用规则未公开。 | YES—LLM/VLM 对 transcript/visual/audio 打分。 | PARTIAL—checklist 项可作粗类型。 | YES—输出 highlight clips。 |

### 3.3 证据、置信度与修复闭环（能力 17–24）

| 工作 | 17 Violation evidence | 18 Confidence | 19 Principle-specific repair | 20 Local repair | 21 Repair routing | 22 Post-render recheck | 23 Repair success rate | 24 New-error rate |
|---|---|---|---|---|---|---|---|---|
| PedaCo-Gen | PARTIAL—LLM review 给修改理由。 | NO—未报告校准置信度。 | PARTIAL—建议按原则修改，但由人执行。 | NO—非自动局部修复。 | NO—无自动路由。 | NO—原论文无成片自动复验。 | NO—只比较总体评分。 | NO—未测新错误。 |
| When Saying No | PARTIAL—指标分数是聚合证据。 | NO—未报告置信度。 | NO—返回脚本由教育者定向修改。 | NO—无自动局部修复。 | PARTIAL—gate 可拒绝并回到脚本。 | YES—自动 gate 作用于最终视频。 | NO—未评价自动 repair success。 | NO—未测副作用。 |
| LASEV | YES—critics 返回语义/工具/规则反馈。 | UNKNOWN—未见校准置信度。 | NO—修复针对 artifact failure，非原则类型。 | PARTIAL—失败 artifact 可重生成。 | YES—不同 critic/gate 决定返工。 | YES—失败后再生成再检查。 | PARTIAL—报告产出/质量，不是按违规的成功率。 | NO—未测新违规。 |
| LLM2Manim | PARTIAL—timing drift/组件问题可反馈。 | NO—未报告校准置信度。 | PARTIAL—可调整 timing 以满足 temporal constraint。 | YES—支持 component-level regeneration。 | PARTIAL—问题决定调时或重生成 part。 | PARTIAL—有 pre-render checks/人工 review，非独立同一 checker。 | NO—未按违规统计修复成功率。 | NO—未测新错误。 |
| PIVOT | YES—execution trace 与 rendering feedback。 | NO—未报告置信度。 | PARTIAL—按 layout/factual/cognitive 类别修复，但非 Mayer 特异。 | YES—shot/code 可迭代修复。 | YES—持续失败转交另一模型。 | YES—verification-guided iterative rendering。 | PARTIAL—用消融证明 verifier 有效，未报告逐违规成功率。 | NO—未报告修复诱发错误。 |
| Teaching Step | PARTIAL—AST/Vision Auditor 提供缺陷信号。 | UNKNOWN—公开材料未披露。 | PARTIAL—原则约束影响改写，具体动作未知。 | PARTIAL—双循环可局部反馈，粒度未知。 | YES—静态与视觉两条审计路径。 | YES—Vision Auditor 检查渲染结果。 | PARTIAL—报告 auditor pass，非违规修复成功率。 | UNKNOWN—未公开。 |
| CourseBlueprint | YES—evaluator 对 typed intermediates/render 给分。 | PARTIAL—slide override 有 confidence threshold。 | NO—未见 Mayer 特异修复。 | UNKNOWN—公开材料未明确局部 repair。 | PARTIAL—typed stage 可定位返工阶段。 | YES—评价 rendered video。 | NO—无修复成功率。 | NO—无新错误率。 |
| TeachMaster | YES—execution/render/sync/layout 反馈。 | UNKNOWN—未披露校准置信度。 | NO—修复不是原则特异。 | YES—技术、同步、布局可局部修复。 | YES—按错误进入不同 agent。 | YES—重渲染后技术检查。 | PARTIAL—报告质量/成功，但非原则违规成功率。 | NO—未报告新教学错误。 |
| Code2Video | YES—occupancy、video 与 code line 共同作证。 | NO—未报告置信度。 | NO—修复针对执行与布局。 | YES—ScopeRefine 从 line 到 block。 | YES—line→block→section 分级路由。 | YES—Critic 看 rendered video 并重渲染。 | PARTIAL—消融报告收益，非逐违规成功率。 | NO—未测新教学违规。 |
| EduVideoBench | PARTIAL—rubric/指标提供分数解释。 | PARTIAL—报告人机一致性而非样本置信度。 | NO—无修复。 | NO—无修复。 | NO—无路由。 | YES—直接评价最终 MP4。 | NO—无修复。 | NO—无修复。 |
| AutoCue | YES—每个事件保存画面/OCR/叙述/手册依据。 | YES—结构化 descriptor 含 0–1 confidence。 | NO—生成 cue，不是检测原则违规后修复。 | PARTIAL—只叠加局部 cue。 | YES—高置信自动输出，低置信交人工。 | PARTIAL—技术验证输出 cue，但非同一原则 checker 复验。 | PARTIAL—报告事件 precision/recall，非 repair success。 | PARTIAL—用户实验观察 breakdown，未定义新错误率。 |
| CogniPresent | PARTIAL—自动 proxy 解释 stage-level 问题。 | NO—未见校准置信度。 | NO—CTML 约束用于生成，不是违规后特异修复。 | NO—未报告局部修复。 | NO—未报告 repair routing。 | PARTIAL—评价生成结果但非同 checker 修复循环。 | NO—无修复成功率。 | NO—无新错误率。 |
| PedagogyBench | YES—QA/片段提供可核证视频证据。 | NO—无样本校准置信度。 | NO—不生成/修复。 | NO—不修复。 | NO—不路由。 | NO—不含重渲染。 | NO—不含修复。 | NO—不含修复。 |
| Ellysia | YES—解释与 highlight clips 是诊断证据。 | UNKNOWN—摘要未披露置信度。 | NO—只评价不修复。 | NO—不修复。 | NO—不路由。 | YES—直接检查最终视频。 | NO—不修复。 | NO—不修复。 |

### 3.4 修复安全、标注、benchmark 与结果（能力 25–32）

| 工作 | 25 Source-fidelity regression | 26 Technical-quality regression | 27 Human gold | 28 IAA | 29 Natural-error benchmark | 30 Synthetic benchmark | 31 Compliance metric | 32 Learning outcome |
|---|---|---|---|---|---|---|---|---|
| PedaCo-Gen | NO—无 source regression。 | PARTIAL—总体视频质量由教育者评价。 | NO—教育者评分不是事件级违规金标。 | UNKNOWN—未见事件标注一致性。 | NO—无错误 benchmark。 | NO—无注入错误 benchmark。 | YES—13 项 CTML 人工遵循度。 | NO—未招募学习者。 |
| When Saying No | NO—无 source regression。 | PARTIAL—image quality 是回归维度之一。 | NO—无事件金标。 | NO—无 IAA。 | NO—14 个对比视频不是错误 benchmark。 | NO—无受控注错。 | YES—五个成片自动原则指标。 | NO—作者明确未测学习结果。 |
| LASEV | NO—无教材 fidelity。 | YES—render/quality gate 持续检查。 | NO—专家评分不是事件金标。 | UNKNOWN—未见违规 IAA。 | NO—无错误 benchmark。 | NO—无注错 benchmark。 | NO—无 Mayer 合规指标。 | NO—无学习者结果。 |
| LLM2Manim | NO—无 source regression。 | PARTIAL—检查渲染/组件质量。 | NO—无违规金标。 | NO—无 IAA。 | NO—无错误 benchmark。 | NO—无注错 benchmark。 | PARTIAL—CTML 设计通过整体评价体现。 | YES—100 人实验报告 post-test/gain/workload。 |
| PIVOT | NO—无教材 fidelity regression。 | YES—layout 与 render quality 持续评价。 | NO—教师感知评价非违规金标。 | UNKNOWN—未见 IAA。 | NO—40 topics 不是错误数据集。 | NO—无受控注错。 | PARTIAL—专家/LLM 评价 pedagogical alignment。 | NO—模拟误答与教师判断，不是学习者增益。 |
| Teaching Step | UNKNOWN—输入来源/回归未公开。 | YES—render success 与 visual defect 指标。 | NO—未见违规金标。 | UNKNOWN—未公开。 | NO—240 trials 不是错误标注集。 | UNKNOWN—未公开是否注错。 | PARTIAL—auditor pass 近似约束遵循。 | NO—公开摘要未报告学习者实验。 |
| CourseBlueprint | PARTIAL—evaluator 检查 corpus-grounded 内容，但无 repair regression。 | YES—同族 evaluator 检查 rendered output。 | NO—无人工违规金标。 | NO—无 IAA。 | NO—5 topics/课程语料不是错误 benchmark。 | NO—无注错。 | PARTIAL—typed-contract evaluator。 | NO—无学习者实验。 |
| TeachMaster | NO—无 source fidelity。 | YES—render/sync/layout agent 检查技术质量。 | NO—无违规金标。 | NO—无 IAA。 | NO—无错误 benchmark。 | NO—无注错 benchmark。 | NO—无原则合规指标。 | NO—无学习者结果。 |
| Code2Video | NO—external assets 不是教材 fidelity regression。 | YES—AES/layout/执行效率及 Critic 消融。 | NO—human study 不是违规事件金标。 | UNKNOWN—未见违规 IAA。 | NO—MMMC 是参考视频集，不是错误集。 | NO—无受控原则注错。 | NO—无 Mayer 合规指标。 | PARTIAL—TeachQuiz 是 VLM 学习代理；人类研究主要评价质量。 |
| EduVideoBench | NO—prompt fidelity 非教材回归。 | YES—同时评价一般感知/认知负荷质量。 | YES—专家对生成视频按 rubric 标分。 | PARTIAL—报告两评者相关而非事件标签 κ。 | YES—1070 个自然生成视频。 | NO—无受控单一违规注入集。 | YES—六条 Mayer 原则 rubric/metrics。 | NO—无真实学习者实验。 |
| AutoCue | PARTIAL—手册一致性用于标签约束，未测修改后回归。 | PARTIAL—仅叠加 cue 并人工可编辑。 | YES—两名 Maya 专家标 critical interactions。 | UNKNOWN—未报告 IAA 指标。 | YES—30 个 in-the-wild 视频片段。 | NO—无原则违规注错集。 | NO—不输出 Mayer 合规总指标。 | YES—24 人实验测任务时间、breakdown 和体验。 |
| CogniPresent | YES—评价 paper evidence utilization。 | PARTIAL—保持 prior paper-to-video metrics。 | NO—无事件级人工金标。 | NO—无 IAA。 | NO—benchmark 不是错误标注集。 | NO—无注错。 | YES—CTML proxies/diagnostics。 | NO—明确未直接测学习结果。 |
| PedagogyBench | NO—无教材 fidelity regression。 | NO—不修复生成视频。 | YES—专家精炼 1852 个教学片段和问答。 | UNKNOWN—正文未见本任务所需违规 IAA。 | YES—真实教学视频 benchmark。 | NO—无原则注错。 | NO—CFS 是认知任务均衡，不是原则合规。 | NO—无学习者实验。 |
| Ellysia | NO—无教材 source regression。 | PARTIAL—checklist 包含一般视听质量。 | PARTIAL—人工成对排序用于外部验证，不是事件金标。 | PARTIAL—摘要称强一致，细节需正文。 | YES—使用真实 YouTube STEM 视频。 | NO—无注错 benchmark。 | YES—12 项 checklist 得分。 | NO—无学习者增益。 |

### 3.5 矩阵结论

1. **没有单篇论文覆盖 32 项大部分能力**。最接近系统闭环的是 PIVOT；最接近对象/代码可追踪与局部修复的是 Code2Video；最接近原则 contract 是 PedaCo-Gen/CogniPresent；最接近成片原则指标是 When Saying No/EduVideoBench；最接近事件级 cue evidence/confidence 是 AutoCue；最接近课程 provenance 是 CourseBlueprint。
2. **两三篇组合已覆盖多数“模块名”**。PedaCo-Gen + When Saying No + PIVOT 已覆盖原则约束、成片检查、迭代修复；CourseBlueprint + TeachMaster/Code2Video 已覆盖来源 ID、事件锚点、对象/代码可追踪和局部修复。若论文贡献只是把这些串联，审稿人可以合理判定为集成。
3. 组合后仍连续缺失的不是字段，而是**经人工金标验证的 source-conditioned event-level principle diagnosis**，以及**原则特异修复的 safety evaluation**（成功、新错误、source fidelity、技术质量四者同时报告）。

## 4. Claim-Level Novelty Audit

| Claim | 已有工作做到什么 | 与可保留版本的差异 | 能否作为贡献 | Risk | 必须如何缩小 |
|---|---|---|---|---|---|
| 1. 原则→机器可执行约束 | PedaCo-Gen、CourseBlueprint、CogniPresent、LLM2Manim 已有 structured constraints/contracts。 | 单纯 JSON/schema/prompt 无差异。 | **不能单独成立**。 | HIGH | 只把形式化作为任务基础设施，不列主贡献；除非证明约束可判定、跨模型执行并有人类效度。 |
| 2. 教学原则违规 taxonomy | La Torre & Désiron 已人工编码 CTML “transgression”；When Saying No/EduVideoBench 有原则维度；PIVOT 有三类 verifier。 | 尚缺生成视频的事件边界、对象、证据、严重度和可复现标注规范。 | **可作为 benchmark 子贡献**，不能只列类型名。 | MEDIUM | 限定 1–2 条原则，发布 operational definitions、负例边界、IAA 与 adjudication。 |
| 3. proposition-level narration–visual alignment | LASEV、LLM2Manim、TeachMaster 已把叙述单元与视觉事件/代码锚点关联；AutoCue 对齐 timestamped utterance 与 ROI 事件。 | 缺少教材证据条件下、命题→对象→可见区间的人类金标和错误定位。 | **可保留，需改成检测任务**。 | MEDIUM | 不主张“建立映射”；主张 source-conditioned event-level diagnosis，并与一般 AV grounding baseline 比较。 |
| 4. 最终渲染视频检测原则违规 | When Saying No、EduVideoBench、Ellysia 已直接检查成片；PIVOT 检查渲染结果。 | 聚合分数到事件级、可举证定位仍有差距。 | **宽泛版本不能；窄版本可**。 | HIGH | 输出时间区间、对象、source evidence、类型和 confidence；以人工事件金标评价。 |
| 5. violation type→principle-specific local repair | PIVOT/Teaching Step/LLM2Manim 有验证后修复；Code2Video/TeachMaster 有局部技术修复。 | 未见按 CTML 违规类型选择最小编辑，并独立测教学副作用的完整证据。 | **可能成立**。 | MEDIUM | 只做已验证 detector 的 1–2 类修复；定义 action space 和 minimality，不把普通重生成称 local repair。 |
| 6. repair 后重渲染并由同 checker 复验 | PIVOT、Code2Video、TeachMaster、LASEV 已有重渲染/复验。 | “同一 checker”不是足够差异，还可能产生 evaluator overfitting。 | **不能单独成立**。 | HIGH | 改成 checker-independent human gold + held-out verifier；同 checker 只作流程。 |
| 7. 同时测 success/new-error/source-fidelity regression | 现有工作多测成功或总体质量；本轮未找到四项同时报告的原则修复研究。 | 差异是 repair safety 的评价问题，而非更多指标堆叠。 | **可作为实证贡献**。 | MEDIUM | 预注册 failure criteria；对照 full regeneration/local repair；用独立 evaluator 与人工复核。 |
| 8. source→KP→narration→visual→render event provenance | CourseBlueprint 覆盖 corpus chunk→narration/slide；KCVR 覆盖 evidence→concept plan；TeachMaster/Code2Video 覆盖 visual/code event。 | 未见从教材 span 一直连到最终可见事件并用于原则诊断的完整链。 | **仅作 schema 不成立；作为诊断变量可能成立**。 | MEDIUM | 证明 provenance 提高检测、定位或错误归因，做去除 source/KP/object link 的消融。 |
| 9. 人工金标 pedagogical violation benchmark | EduVideoBench 已有专家原则评分；PedagogyBench/AutoCue/MTBU-Bench 已有专家事件标注；La Torre 有人工 transgression coding。 | 通用 benchmark 已不可做；事件级 CTML 违规、自然错误+受控单错、教材证据链仍未见。 | **窄版本可**。 | HIGH | 避免“首个教学视频 benchmark”；限定生成视频、两条原则、事件定位、证据和 IAA。 |
| 10. 原则合规与 learner outcome 关系 | LLM2Manim 测学习增益；AutoCue 测任务表现；Mayer 原始研究支持原则效应；但生成视频自动合规分数与真实学习结果的关联未被这些工作直接验证。 | 可检验 checker construct validity，而非再次证明 Mayer。 | **可作为独立实证论文，成本高**。 | MEDIUM | 使用预/后测与 transfer；控制内容、时长、先验；避免把相关性写成因果。 |

## 5. 连续缺失链审计

### Chain A：principle → object → observable → typed violation → validated detector

- **单篇完整完成？** 本轮未找到。AutoCue 最接近 object/observable/localization/evidence/confidence，但目标是 GUI 操作 cue，不是 CTML 违规；When Saying No/EduVideoBench 最接近 principle/metric，但缺事件级 object 与人工定位金标。
- **多篇组合？** PedaCo-Gen（原则）+ AutoCue（事件证据）+ When Saying No（成片指标）可以拼出表面链条。
- **为何可能不只是集成？** 只有在提出新的“source-conditioned event-level violation localization”任务、标注协议和经验证 detector 时才不是集成。若只是把字段放进同一 JSON，就是集成。
- **新方法要求：** 原则适用条件必须可观测；模型要在教材证据和视频证据冲突时做可判定归因；输出区间、对象、证据和 calibrated confidence。
- **可形成 benchmark/task？** 可以，且比“视频整体打 1–5 分”更可证伪。
- **独立实验：** event detection F1/IoU、object grounding、evidence precision、calibration、跨主题/跨模板泛化，并与 aggregate metric 和直接 VLM prompting 比较。

判定：**仍可研究，但只限事件级、source-conditioned、human-validated 版本。**

### Chain B：typed violation → principle-specific repair → local modification → rendered verification → effectiveness

- **单篇完整完成？** PIVOT 最接近，但 verifier 是 layout/factual/cognitive 三类，修复为低温代码 debug；未报告 CTML violation-specific action、逐违规 repair success、new-error、source-fidelity regression。
- **多篇组合？** LLM2Manim（CTML timing 调整）+ Code2Video（scope-local repair）+ PIVOT（render verify）已覆盖技术链的大部分。
- **何时仍是研究问题？** 需要把 repair 视为受约束决策：最小化修改，同时满足目标原则并保持 source fidelity/其他原则。若只是按错误文字让 LLM 改代码，就是已有范式。
- **新方法要求：** 原则特异 action space 或 constrained selection；独立 verifier；repair safety 指标。
- **benchmark/task？** 可建立 paired before/after repair benchmark，但应建立在稳定的 Chain A detector 上。
- **独立实验：** local repair vs full regeneration vs generic LLM repair；成功率、新错误率、source/technical regression 和人工偏好。

判定：**潜在贡献，但被 PIVOT/Code2Video 强烈挤压，且依赖先有可靠 detector。**

### Chain C：textbook evidence → knowledge point → narration proposition → visual object → rendered event → diagnosis

- **单篇完整完成？** 本轮未找到。CourseBlueprint 到 narration/slide，KCVR 到 evidence-supported concept plan，TeachMaster/Code2Video 到 code event；没有单篇把整链用于教学原则诊断。
- **多篇组合？** 是，所有节点分别已有。
- **为什么不必然是新问题？** 纯 provenance ledger 是数据工程；把节点连接起来也不自动产生新方法。
- **何时构成研究？** 当完整链被证明能解决现有 checker 做不到的错误归因，例如区分“视觉不相关”“视觉正确但出现晚”“讲述本身不受教材支持”。
- **benchmark/task？** 可把诊断输出定义为 evidence path prediction，并做 edge-level/chain-level accuracy。
- **独立实验：** 去掉 source、KP、object、render interval 的消融；评估 detector 和解释正确率是否显著下降。

判定：**可作为 Candidate 1 的机制，不建议单独以‘完整 provenance’投稿。**

### Chain D：human gold → checker → repair → post-validation → learning outcome

- **单篇完整完成？** 本轮未找到。EduVideoBench 有专家评分但无 repair；PIVOT 有 checker/repair 但无事件金标和学习者 outcome；LLM2Manim 有学习结果但无金标 checker/repair safety。
- **多篇组合？** 是，且组合后工程量很大。
- **新方法还是集成？** 若目标是验证“自动合规改善是否真正预测学习”，这是新的评价效度问题；若只把四个模块串起来，是集成。
- **benchmark/task？** 可以建立 construct-validity study，但学习实验需严格控制内容、时长、先验与教师效应。
- **独立实验：** checker-human agreement、repair A/B、retention/transfer、mediational/correlational analysis；不能仅用 VLM quiz 替代学习者。

判定：**科学价值高，但超出一般小论文的低成本范围；更适合作为后续验证。**

## 6. 七个方向的 Stress Test

### 方案 1：Temporal Contiguity + Signaling 语义时序检测与修复

- **是否直接做过：** 部分直接做过。LLM2Manim 在生成计划中连接 narration cues 与 visual events；When Saying No 自动算 Temporal Contiguity；AutoCue 把 cue 定位到时间与 cursor/ROI；Teaching Step 约束 Signaling；PIVOT 做渲染后验证修复。
- **最大重合：** “何时出现视觉、何时强调、发现偏差后调整 timing”已非空白。
- **真正差异：** 教材有据、命题级、对象级、最终渲染区间、人工金标与校准置信度的联合诊断。
- **是否只是实现细节：** 若只提高同步阈值或多一个 VLM prompt，是实现细节；若定义 source-conditioned event diagnosis 与 benchmark，则不是。
- **需要什么：** 新任务+标注协议+detector；修复应放第二阶段。
- **是否够小论文：** **够，但必须只选一到两条原则，并以检测/benchmark 为主。**
- **审稿人质疑：** “这就是 temporal grounding / AutoCue / When Saying No。”
- **回答门槛：** 实验证明一般 temporal grounding、aggregate metric 与直接 VLM judge 无法正确给出教材证据、违规类型和事件边界。
- **放弃条件：** 找到一篇公开工作已对生成教学视频发布相同粒度的人类金标和 source-conditioned detector。

### 方案 2：Pedagogical Principle Contract / machine-executable constraints

- **是否直接做过：** 是。PedaCo-Gen、CourseBlueprint、CogniPresent。
- **最大重合：** 原则字段、约束 prompt、typed intermediate representation、stage evaluator。
- **真正差异：** 当前没有足够差异；换字段名不算。
- **需要什么：** 除非发展可判定语义、形式验证或跨生成器执行语义，否则只是 schema engineering。
- **是否够小论文：** **当前版本不够。**
- **审稿人质疑：** “PedaCo-Gen/CourseBlueprint 已经做了。”
- **能否回答：** 仅凭更细 JSON 不能。
- **结论：** **放弃作为主贡献。**

### 方案 3：Textbook-grounded principle violation detection

- **是否直接做过：** 本轮未找到完全相同工作；VCEval 用教材评价课程，CourseBlueprint/Dynamic 做教材 grounding，When Saying No/EduVideoBench 做原则评价。
- **最大重合：** 组件均已出现。
- **真正差异：** source evidence 不是输入装饰，而是 detector 的必要条件和输出证据；要判断“该命题所需且教材支持的视觉证据”是否在正确时间可见。
- **是否只是实现细节：** 若 detector 不利用 provenance 或无消融，容易被判为集成。
- **需要什么：** 新问题定义、source-conditioned baseline、事件级金标和 source-ablation。
- **是否够小论文：** **够，是当前最强候选。**
- **审稿人质疑：** “只是在 When Saying No 前加 RAG。”
- **回答门槛：** 证明无 source 条件时发生系统性误报/漏报，且 provenance 能改善错误归因与跨教材泛化。
- **放弃条件：** source 条件消融无显著价值，或错误主要靠视频自身即可判断。

### 方案 4：Principle-specific local repair + post-render verification

- **是否直接做过：** PIVOT 已做验证后迭代代码修复，LLM2Manim 做 timing 调整/局部重生成，Code2Video/TeachMaster 做局部修复。
- **最大重合：** detect-feedback-edit-rerender 已有。
- **真正差异：** 只剩 CTML violation-specific action 与 repair safety（新错误、source fidelity、技术回归）。
- **是否只是实现细节：** 非常容易退化成 prompt routing。
- **需要什么：** 受约束修复目标、明确最小编辑、独立 checker 和安全评价。
- **是否够小论文：** **可能够，但风险和工程量均高于方案 3。**
- **审稿人质疑：** “PIVOT/Code2Video 的 repair 换了标签。”
- **回答门槛：** generic repair baseline 明显更差，principle-specific method 在成功率和副作用上均显著改进。
- **放弃条件：** generic LLM repair 达到同等结果，或 detector 不可靠。

### 方案 5：Pedagogical violation benchmark

- **是否直接做过：** 通用版本已被 EduVideoBench、PedagogyBench、VisualEDU、TheoremExplainBench、VCEval 占据；La Torre 还有人工 CTML transgression coding。
- **最大重合：** 教学视频、多维 rubric、专家评价、人机一致性。
- **真正差异：** 仅可能是“生成视频、事件级、教材有据、typed violation、自然错误+单一受控注错”。
- **是否只是实现细节：** 若仍是整片 Likert 分，答案是是。
- **需要什么：** 事件级标注协议、IAA、自然/合成两套数据、强 detector baselines。
- **是否够小论文：** **窄版本够；通用版本应放弃。**
- **审稿人质疑：** “为什么 EduVideoBench 不够？”
- **回答门槛：** 展示整片分数不能定位、修复或区分错误源；新 benchmark 支持新的 localization/evidence task。
- **放弃条件：** 不能获得稳定 IAA，或事件边界/类型无法被专家一致标注。

### 方案 6：Coherence / extraneous-content detection

- **是否直接做过：** When Saying No 已算 coherence；PedaCo-Gen 和 PIVOT 已审查相关性/逻辑；Mayer coherence 与 seductive details 有大量既有实验。
- **最大重合：** 目标相关性、无关内容、逻辑连贯的判断。
- **真正差异：** 教材证据可以辅助 relevance，但“有趣且无关”仍高度语境化。
- **是否只是实现细节：** 大概率是把 relevance judge 接入视频。
- **需要什么：** 稳健的目标条件化定义和独立学习结果验证，成本高。
- **是否够小论文：** **不建议作为首选。**
- **审稿人质疑：** “LLM relevance scoring 是否只是主观 judge？”
- **回答门槛：** 高 IAA、跨领域泛化、与 retention/transfer 的关系。
- **放弃条件：** 专家 IAA 低或 detector 只学习表面素材类别。

### 方案 7：Repair safety / evaluation validity

- **是否直接做过：** 本轮未找到同时测 repair success、new-error、source fidelity、technical regression 并用人工金标复验的原则修复工作。
- **最近邻：** PIVOT、Code2Video、TeachMaster、LLM2Manim；它们分别测渲染/质量收益，但未形成 repair-safety 任务。
- **最大重合：** repair pipeline 已有。
- **真正差异：** 研究对象是“修复是否把错误转移到别处、是否对 checker 过拟合”，不是再做一个修复 agent。
- **是否只是实现细节：** 若只有四个平均分，是指标堆叠；若有对抗/独立验证、因果归因和失败分析，则是评价方法与实证发现。
- **需要什么：** 独立 evaluator、人类 before/after 标注、held-out principles/templates、局部与全量重生成对照。
- **是否够小论文：** **可行但依赖可靠 detector 和足够样本。**
- **审稿人质疑：** “只是软件回归测试。”
- **回答门槛：** 证明教学违规存在系统性 error migration，且常用单一 checker 高估修复收益。
- **放弃条件：** 未观察到可重复的副作用，或人工标注无法稳定区分。

## 7. 三个最终候选

## Candidate 1：教材证据条件下的事件级教学音画违规诊断

### One-sentence novelty

现有工作主要给整片/整段原则分数或在生成计划中做音画对齐；本研究把任务定义为：从最终视频中定位“教材支持的讲述命题所需视觉对象未在正确时间可见或未被正确指示”的事件，并输出 source evidence、对象、时间区间、违规类型和校准置信度。

### Closest Work

[When Saying No](https://arxiv.org/html/2608.19812)、[EduVideoBench](https://arxiv.org/html/2605.26918)、[AutoCue](https://arxiv.org/html/2608.04910)、[CourseBlueprint](https://arxiv.org/html/2606.20608)、[LLM2Manim](https://arxiv.org/html/2604.05266)。

### What they already do

- When Saying No：最终视频层面的 temporal contiguity/coherence 等自动指标。
- EduVideoBench：专家 Mayer rubric 和生成视频 benchmark。
- AutoCue：timestamp/ROI/evidence/confidence/cue rendering。
- CourseBlueprint：课程来源 IDs 与 typed intermediates。
- LLM2Manim：narration cue 与 visual event 的计划级链接。

### What is still missing

本轮未找到它们对“教材 span→讲述命题→视觉对象→实测可见区间”建立人工金标，并以此验证最终视频的事件级 CTML 违规定位。

### Why this is not just integration

贡献必须是新的诊断任务与标注单位；source 不是 RAG 附件，而是判定所需视觉证据、排除表面相关视觉和解释错误来源的条件变量。通过 source-ablation、aggregate-metric baseline 和通用 temporal-grounding baseline 可证伪其必要性。

### Research Question

- RQ1：source-conditioned event model 是否比整片原则指标和直接 VideoLLM prompting 更准确地定位 Temporal Contiguity/Signaling 违规？
- RQ2：显式 provenance 边（source→proposition→object→interval）是否提高跨主题/跨模板泛化、证据正确率和置信度校准？

### Required Method

需要：原则的操作定义与适用条件；命题/对象/时间区间联合表示；source-conditioned evidence reasoning；可拒绝/置信度校准。仅加字段或 prompt 不够。

### Required Dataset / Annotation

自然生成错误为主、辅以单一因素受控注错；双人或多人标注 proposition span、object、visibility interval、violation type、source evidence 与可判定/不可判定，报告 IAA 和 adjudication。

### Evaluation

事件 detection F1、temporal IoU、object grounding accuracy、violation classification F1、evidence precision/recall、ECE/Brier；baseline 至少含整片指标、无 source 的 VideoLLM、通用 AV grounding、规则时间阈值；做 source/KP/object/interval 消融。

### Main Risk

审稿人可能认为它是 AutoCue + CourseBlueprint + When Saying No 的集成，或一般 temporal grounding 在教育域的应用。

### Kill Condition

若精读补充材料发现已有工作已发布相同粒度的生成教学视频 CTML 事件金标与 source-conditioned detector；或 source-ablation 对定位/泛化无实质贡献，应立即放弃或改为纯 benchmark/负结果论文。

### Feasibility

HIGH

### Novelty Confidence

MEDIUM-HIGH

## Candidate 2：原则特异的最小局部修复与 repair-safety 评价

### One-sentence novelty

现有系统能按渲染/布局/同步反馈重生成或修代码，但本研究针对已定位的 CTML 违规选择最小原则特异编辑，并同时验证修复成功、新错误、教材忠实度和技术质量回归。

### Closest Work

[PIVOT](https://arxiv.org/html/2609.24083)、[Code2Video](https://arxiv.org/html/2510.01174)、[TeachMaster](https://arxiv.org/html/2601.04204)、[LLM2Manim](https://arxiv.org/html/2604.05266)、[LASEV](https://arxiv.org/html/2602.11790)。

### What they already do

它们已实现 shot/component/code-line 级反馈、局部修复、重渲染和若干质量检查；PIVOT 已有 verification-guided repair，因此“闭环”本身不能主张。

### What is still missing

本轮未找到按原则违规类型定义修复 action space、约束最小编辑，并以独立人工金标同时报告四类 repair-safety 结果的工作。

### Why this is not just integration

必须把修复形式化为多约束决策，而不是让 LLM 读取错误文本后改代码；研究问题是目标违规与副作用之间的可测 trade-off，以及 generic repair 为何失败。

### Research Question

- RQ1：principle-specific constrained repair 是否比 full regeneration 和 generic LLM repair 有更高净修复收益？
- RQ2：使用同一 checker 的闭环是否高估成功率，独立人工/held-out checker 会揭示多少 error migration？

### Required Method

违规到修复动作的显式映射、最小编辑约束、局部 rerender、独立 post-check 与 fail-safe abstention；不能仅用 prompt routing。

### Required Dataset / Annotation

Candidate 1 的 gold violations，加 before/after 配对标注；记录目标错误是否消失、新错误、source fidelity、技术故障与修改范围。

### Evaluation

repair success、net success、new-error rate、source-fidelity regression、technical-quality regression、edit locality/cost；baseline 为不修、全量重生成、generic repair、PIVOT-style render-feedback repair；做人类盲评和 action-space/independent-checker 消融。

### Main Risk

PIVOT 与 Code2Video 已非常接近；若 principle-specific 方法只是提示词差异，novelty 会崩溃。

### Kill Condition

若 generic repair 与拟议方法无显著差异，或事件 detector 的错误主导全部结果，立即停止把 repair 当主贡献。

### Feasibility

MEDIUM

### Novelty Confidence

MEDIUM

## Candidate 3：自动原则合规指标的构念效度与学习结果验证

### One-sentence novelty

现有生成研究多把 VLM/规则原则分数当作教学质量代理；本研究检验这些分数在控制内容与时长后，能否预测人工事件金标、认知负荷、保持与迁移，并识别“checker 提升但学习不改善”的失效模式。

### Closest Work

[EduVideoBench](https://arxiv.org/html/2605.26918)、[When Saying No](https://arxiv.org/html/2608.19812)、[LLM2Manim](https://arxiv.org/html/2604.05266)、[AutoCue](https://arxiv.org/html/2608.04910)、[VCEval](https://arxiv.org/abs/2407.12005)。

### What they already do

EduVideoBench 报告人机评分一致性；When Saying No 报告自动原则指标改进；LLM2Manim 有真实学习实验；AutoCue 有任务绩效实验；VCEval 用“学习后考试”代理质量。

### What is still missing

本轮未找到在同一批 AI 生成视频上把自动原则分数、事件级人工金标、真实学习者 retention/transfer 系统关联起来并检验 construct validity 的工作。

### Why this is not just integration

贡献是评价效度与可反驳的实证结论，而非添加生成模块；可能得到负结果——自动合规分数并不预测学习——这同样有研究价值。

### Research Question

- RQ1：自动 CTML compliance 与专家事件金标、学习者 retention/transfer 的相关/增量预测效度是多少？
- RQ2：哪些原则、视频类型或学习者先验导致自动指标失效？

### Required Method

预先定义 construct、控制混杂因素、建立多层统计模型和跨 evaluator 稳健性分析；不需要新生成器，但需要严谨实验设计。

### Required Dataset / Annotation

同内容的原则遵循/违规配对视频、专家事件标注、学习者先验测验、即时保持/迁移、延迟测验（若资源允许）和认知负荷量表。

### Evaluation

人机一致性、校准、相关与增量效度、混合效应模型、原则×先验交互、multiple-comparison control；与 VLM quiz、专家整体评分、简单可观测指标比较。

### Main Risk

样本量、伦理审批和学习者招募成本高；若设计不充分，只能得到低功效相关性。

### Kill Condition

若无法获得足够学习者、预注册效能分析显示所需样本超出资源，或只能用 VLM 充当学生，应放弃作为当前小论文主线。

### Feasibility

LOW

### Novelty Confidence

MEDIUM

## 8. 最终推荐

### 当前最值得继续的方向

**Candidate 1：教材证据条件下的事件级教学音画违规诊断。**

### 推荐依据

| 维度 | 判断 |
|---|---|
| Novelty | 在通用 contract、checker、benchmark 均被占据后，source-conditioned event-level diagnosis 仍保留连续缺失链；置信度 MEDIUM-HIGH。 |
| 可验证性 | 有明确人工金标、event F1/IoU、evidence accuracy 和 calibration；结果可失败。 |
| 项目匹配 | 现有 source refs、knowledge points、narration、element IDs、timeline 和最终渲染产物可作为数据基础。 |
| 实现成本 | 比先做完整 repair loop 低；研究原型可只做 1–2 条原则。 |
| 实验成本 | 主要成本是专家标注，不必立即做大规模学习者实验。 |
| 最近邻压力 | AutoCue/When Saying No/EduVideoBench/CourseBlueprint 很强，因此必须用 source-conditioned、event-level、人类金标三重限定。 |

对五个决策问题的回答：

1. **当前方向是否值得继续？** 宽泛方向不值得；收缩后的 Candidate 1 值得继续验证。
2. **是否应该换方向？** 应从“原则驱动生成+checker+repair 系统”换成“事件级、教材有据的诊断任务”；repair 暂降为后续候选。
3. **最大 novelty threat 是哪篇？** 系统级是 PIVOT；对推荐候选的组合威胁是 AutoCue + When Saying No + EduVideoBench + CourseBlueprint，其中 AutoCue 的事件证据/置信度最危险。
4. **实现前必须精读什么？** PIVOT 附录/代码、AutoCue Supplement 3–4、EduVideoBench rubric/annotation、When Saying No 的指标实现、CourseBlueprint schema/evaluator、CogniPresent 完整实验；Teaching Step by Step 的 OSF 补充材料也必须核清。
5. **现在能否冻结 scope？** 可以冻结“问题边界”的临时版本：只研究最终渲染视频、只选 Temporal Contiguity 与 Signaling、只做 source-conditioned event diagnosis；**不能冻结方法与 novelty claim**，须先完成上述补充材料审计和小规模 IAA pilot。

## 9. 总 Kill Condition

出现任一条件，应停止当前推荐方向：

1. 发现已公开论文/数据集同时具备：生成教学视频、教材/source grounding、命题—对象—时间区间金标、CTML 违规定位与 validated detector。
2. 双人 pilot 标注对核心 violation type 或 temporal boundary 的一致性低，且经规则澄清后仍不能达到可接受水平。
3. source-conditioned 方法相对无 source baseline 在跨主题泛化、证据正确率或事件定位上无稳定增益。
4. 通用 VideoLLM/temporal grounding baseline 已达到接近人工上限，新增问题定义不产生新的能力差异。
5. 为使任务可标注而不得不依赖系统内部 metadata，导致 detector 不能评价其他生成器的最终 MP4；此时论文会退化为项目内部 QA。

## 10. Search Saturation Report

### 10.1 已用关键词族

- 理论→生成：`pedagogical principle guided video generation`、`CTML educational video generation`、`Mayer principle video generation`、`pedagogy-aware video generation`。
- 原则→约束：`machine executable pedagogical constraints`、`typed pedagogical representation`、`instructional contract`、`pedagogical schema`。
- 违规检测：`pedagogical violation detection`、`CTML compliance`、`multimedia learning principle evaluation`、`instructional design violation`。
- 音画/时序：`narration visual alignment`、`semantic temporal grounding educational video`、`speech visual synchronization educational animation`。
- Signaling：`visual cue alignment narration`、`highlight timing instructional video`、`cue target alignment`。
- Coherence：`extraneous content detection educational video`、`seductive detail detection`、`goal relevance educational content generation`。
- 修复：`principle aware repair`、`video generation verification repair`、`localized video repair`、`pedagogical repair safety`。
- 教材/provenance：`textbook grounded video generation`、`curriculum grounded video generation`、`source evidence instructional video`、`pedagogical provenance`。
- 成片与 benchmark：`rendered video pedagogical evaluation`、`human annotated pedagogical errors`、`educational video error taxonomy`。
- 最后一轮候选反查：`event-level pedagogical video diagnosis`、`principle-specific repair educational video`、`source fidelity repair regression`、`human annotated multimedia learning violations`。

### 10.2 检索来源

ACL Anthology、ACM/CHI 与 GI DOI 页面、IEEE/CVF Open Access、Springer Nature、arXiv、OpenReview、Google Scholar/Semantic Scholar 发现页、作者/项目官方 GitHub。二手页面只用于发现线索，不作为核心事实证据。

### 10.3 Backward / forward chasing

- backward：PedaCo-Gen、When Saying No、LASEV、LLM2Manim、PIVOT、Code2Video、CourseBlueprint、PedagogyBench、AutoCue、EduVideoBench 的 references/related work。
- same-author/follow-up：PedaCo-Gen→When Saying No；PresentAgent→PresentAgent-2；PedagogyBench 作者链→KCVR。
- forward：对上述题名、作者和关键 capability 做 2026 限定搜索；因多数论文发表于 2026 年 5–9 月，正式 citing literature 尚不成熟，此项证据强度低。

### 10.4 新近邻与饱和判断

相对两份既有调研，本轮新增或显著提升权重的直接/近直接工作至少 5 篇：EduVideoBench、AutoCue、CogniPresent、KCVR、Sci-VBench；另发现 MTBU-Bench 等事件级教育视频理解 benchmark，但它未改变核心结论。[MTBU-Bench](https://educationaldatamining.org/edm2026/proceedings/2026.EDM.full-papers.128/index.html)

最近新增论文仍改变 novelty 判断：EduVideoBench 否定通用原则 benchmark，AutoCue 挤压 Signaling 事件对齐，CourseBlueprint/CogniPresent 挤压 contract 与 provenance，2026-09 的 PIVOT 直接挤压 checker-repair 闭环。因此，**整体领域尚不能宣称检索饱和**。当前只达到对三个窄候选的“局部稳定”：最后一轮 capability 查询没有发现完整覆盖 Candidate 1 或 repair-safety 四指标的单篇工作，但这不足以排除快速出现的 2026 follow-up。

正式方法设计前应再完成一次定点审计：下载并逐页核对 PIVOT、AutoCue supplements、EduVideoBench annotation files、Teaching Step OSF、CogniPresent 最新版本及相关代码；并对 Candidate 1 的精确任务描述做一次题名/摘要全文反查。若该轮仍无改变判断的工作，才适合冻结 novelty claim。

## 11. 关键证据索引

- Kim, Baek, Kwak. [PedaCo-Gen](https://arxiv.org/html/2602.19623), CHI EA 2026。
- Kim, Baek, Kwak. [When Saying No Makes Better Videos](https://arxiv.org/html/2608.19812), 2026。
- [LASEV](https://arxiv.org/html/2602.11790), KDD 2026 Applied Data Science。
- [LLM2Manim](https://arxiv.org/html/2604.05266), 2026。
- Ma et al. [PIVOT](https://arxiv.org/html/2609.24083), arXiv 2026。
- Cohn et al. [Teaching Step by Step](https://link.springer.com/chapter/10.1007/978-3-032-29788-4_73), AIED 2026。
- [CourseBlueprint](https://arxiv.org/html/2606.20608), 2026。
- [TeachMaster](https://arxiv.org/html/2601.04204), 2026。
- Shi et al. [PresentAgent](https://aclanthology.org/2025.emnlp-demos.58/), EMNLP 2025 Demo；[PresentAgent-2](https://arxiv.org/html/2605.11363), 2026。
- Chen et al. [Code2Video](https://arxiv.org/html/2510.01174), ICML 2026（官方仓库标注）。
- Ku et al. [TheoremExplainAgent](https://aclanthology.org/2025.acl-long.332/), ACL 2025。
- Chen et al. [VisualEDU](https://aclanthology.org/2025.findings-emnlp.889/), Findings of EMNLP 2025。
- Zhu et al. [Paper2Video / PaperTalker](https://arxiv.org/abs/2510.05096), 2025。
- Liu et al. [Preacher](https://openaccess.thecvf.com/content/ICCV2025/html/Liu_Preacher_Paper-to-Video_Agentic_System_ICCV_2025_paper.html), ICCV 2025。
- Zhu et al. [VCEval](https://arxiv.org/abs/2407.12005), 2024/2025 revision。
- Lee et al. [EduVideoBench](https://arxiv.org/html/2605.26918), 2026。
- Luo et al. [AutoCue](https://arxiv.org/html/2608.04910), Graphics Interface 2026。
- Liu et al. [KCVR](https://aclanthology.org/2026.acl-long.414/), ACL 2026。
- Jin et al. [PedagogyBench](https://aclanthology.org/2026.findings-acl.614/), Findings of ACL 2026。
- La Torre & Désiron. [How do instructional videos foster learning?](https://link.springer.com/article/10.1007/s10758-024-09753-2), International Journal of Educational Technology in Higher Education, 2024。

