# Textbook-to-Video 与 PresentAgent 对比及评估设计总结

> 本文基于项目当前实现和 `docs/PresentAgent.pdf` 整理，用于明确本项目与 PresentAgent 的关系、可主张的差异点、当前能力边界，以及后续对照实验设计。本文不把本项目定位为 PresentAgent 的完整复现，而是把 PresentAgent 作为“长文档到旁白演示视频”的代表性工作来对照。

> 正式实验执行方案已单独整理为 [`docs/presentagent-experiment-design.md`](presentagent-experiment-design.md)。该文档采用 `Lesson Plan × Timed Animation` 的 `2 × 2` 因子设计，并包含 TextbookEval-v1 数据集组建、双人并行分工、独立评分、VLM 辅助评价、统计分析和官方 PresentAgent 外部对照。当前执行范围不包含参与者实验。若本文后续的方向性建议与正式方案存在差异，以正式实验方案为准。

## 1. 当前结论

本项目不适合定位为 PresentAgent 的简单复现或平替。PresentAgent 已经提出了 Document-to-Presentation Video Generation 的任务定义，并实现了长文档到带旁白演示视频的完整 pipeline。如果本项目仍然只强调“文档转视频”，创新点会显得不够清楚。

更稳妥的定位是：

> 面向教材章节的可控教学视频生成系统，核心差异是教学计划驱动、结构化 storyboard、旁白驱动页内动画、教材图片引用、可编辑中间层和确定性质量检查。

也就是说，本项目应从“通用文档演示视频生成”转向“教材教学视频生成与可控编辑”。PresentAgent 证明了长文档可以生成旁白演示视频；本项目进一步研究在教材教学场景下，教学约束和可控中间表示是否能提升生成结果的教材忠实度、教学完整性、音画同步和可审阅性。

## 2. PresentAgent 的主要方案

PresentAgent 的整体流程可以概括为：

```text
长文档
  -> outline / semantic blocks
  -> slide planning and composition
  -> oral-style narration
  -> TTS audio
  -> static slide frames + audio
  -> presentation video
```

它的主要贡献包括：

- 提出 Document-to-Presentation Video Generation 任务。
- 使用模块化 pipeline 生成 slide、narration、audio 和 video。
- 提出 PresentEval 评估框架。
- 构建 Doc2Present benchmark，包含 30 个文档-人工演示视频对。
- 使用 objective quiz 和 VLM subjective scoring 评估内容、视觉和理解质量。

PresentEval 的核心评估方式包括：

- Objective Quiz Evaluation：为每个文档人工设计 5 道多选理解题，评估生成视频是否传达关键信息。
- Subjective Scoring：用 VLM 从 content fidelity、visual/audio quality、comprehension clarity 等维度打分。

需要注意，PresentEval 的模型评估不是让真人直接观看视频，而是把 slide images 和 narration transcript 等信息输入 VLM，模拟观看后的理解与评分。

## 3. PresentAgent 的限制

本文建议把 PresentAgent 的不足表述为“限制”而不是“错误”或“问题”，因为它的目标是通用演示视频，而本项目面向教材教学场景。

第一，PresentAgent 当前生成的是静态 slide frame 加 narration audio。其 limitation 中明确提到，由于架构和生成速度/视觉质量权衡，目前没有动态动画或页内元素级效果。

第二，PresentAgent 提出了 30 个样本的 Doc2Present benchmark，但详细主结果表是 5-document test set。论文解释原因与商业 LLM/VLM API 成本有关。

第三，PresentAgent 更偏通用 presentation video，不专门建模教学目标、课堂活动、知识点检测、教材原图证据链等教学需求。

这些限制给本项目留下了差异化空间，但论文中不宜写成“本项目解决了 PresentAgent”，而应写成：

> 本项目针对 PresentAgent 在动态呈现、教学建模和教材 grounding 方面的限制，在教材教学视频生成场景下提出互补增强。

## 4. 本项目当前已有能力

本项目当前 pipeline 已具备端到端生成能力：

```text
教材(PDF/DOCX)
  -> 教材解析
  -> Lesson Plan
  -> Script
  -> Storyboard JSON
  -> Storyboard Enhancer / Agent Review
  -> TTS 配音与时长回写
  -> Timed Storyboard
  -> HTML 动画渲染
  -> 浏览器录制
  -> 音画合成 MP4
  -> Quality Report
```

已经实现或基本实现的关键模块包括：

- `lesson_plan.py`：生成学习目标、知识点、活动和检测题。
- `storyboard.py`：生成结构化 storyboard，支持 lesson plan 增强、deterministic enhancer 和 agent review loop。
- `timing.py`：根据真实 TTS 时长和字幕 cue 生成元素级 `trigger_at_sec`。
- `quality.py`：生成确定性质量报告，检查音频、字幕、布局、知识点覆盖、教学活动、测验结构和教材图片使用。
- `preview.py`：支持 storyboard 预览和轻量编辑。
- `review.py`：支持人工 review packet 与 approve gate。
- `recorder.py`：录制时优先读取 `slideDurations`，按真实配音时长翻页。

这些说明项目不是概念方案，而是已经有较完整的工程基础。

## 5. 当前能力边界

### 5.1 评估还不够强

当前 `*_quality.json` 更像自动体检单，能发现生成事故，但不能直接证明教学效果。它可以检查：

- 音频段数是否齐全。
- 字幕覆盖是否完整。
- 知识点是否被 storyboard 引用。
- 教学活动页、检测题页是否存在。
- 布局 QA 是否失败。
- 动画触发时间是否晚于音频结束。
- 教材图片是否被引用。

但它还不能回答：

- 学生看完是否真正理解。
- 讲解是否完全符合教材原意。
- 动画是否真的帮助理解，而不是造成干扰。
- 教材图片是否被正确讲解。

因此，后续最需要补的是教学质量评估闭环，而不是继续堆生成效果。

### 5.2 教材 grounding 仍是部分实现

项目已经能提取教材图片、引用教材图片，并检查图片使用率；也支持 `focus_box` / `callout` 这类局部标注元素。但目前还没有形成严格的：

```text
教材原文 -> 知识点 -> 讲稿 -> 画面元素 -> 教材图片区域
```

证据链。

因此，教材 grounding 应在实验阶段通过人工标注补强，至少标注：

- 每个核心知识点对应教材哪一段原文。
- 哪些教材图片必须使用或可选使用。
- 图片是否被用于正确知识点。
- 讲稿或画面是否引入教材外错误内容。

### 5.3 动画优势需要实验验证

项目已经有 narration-driven timing，但还不能直接宣称“动画一定提升理解”。动画可能帮助流程、对比和图示类知识点，也可能增加干扰。

更严谨的说法是：

> 本项目检验旁白驱动的页内动画是否能改善音画同步、降低一次性信息暴露，并在部分知识类型上提升理解表现。

需要通过实验验证：

- 页内元素出现时间是否更接近旁白语义。
- 动画是否减少过早暴露信息。
- 对流程、定义、对比、图示类知识点，动态呈现是否优于一次性静态展示。

### 5.4 可编辑工作流仍偏工程化

项目已有 `preview --edit`、`--from-storyboard`、`--reuse-html`、局部重配音和 review gate 等工程入口。但它还不是完整产品化 authoring tool。

可以主张：

> 本项目提供可检查、可编辑、可局部重跑的中间产物和命令行工作流。

不宜过度主张已经具备完整的表单化编辑、前后对比、修改记录或教师协同审批系统。

## 6. 本项目相对 PresentAgent 的差异点

### 6.1 教学计划驱动，而不是普通摘要

PresentAgent 主要把文档转成演示结构。本项目引入 Lesson Plan，先建模学习目标、知识点、活动和检测题，再驱动 script 和 storyboard。

这是本项目最重要的差异之一：系统不是单纯总结教材，而是围绕教学目标组织内容。

### 6.2 旁白驱动的页内动画

PresentAgent 当前是静态 slide 加音频。本项目通过 TTS 后处理，把真实音频时长和字幕 cue 写回 storyboard，再给元素安排 `trigger_at_sec`。

这可以形成明确贡献：

> Narration-driven timed storyboard for teaching animation.

它让画面元素尽量在旁白讲到相关内容时出现，更接近教师逐步讲解。

### 6.3 确定性模板渲染和浏览器 QA

本项目不是完全依赖 LLM 直接写 HTML。常见教学页面优先走结构化模板渲染，再通过浏览器布局 QA 和 CSS/LLM 修复降低版面事故。

这个优势比较工程化，但很实用：

- 页面结构更稳定。
- 结果更可复现。
- 更容易局部修复。
- 更适合批量生成教材视频。

### 6.4 可检查、可编辑、可局部重跑

本项目保留多个中间产物：

- `*_lesson_plan.json`
- `*_script.txt`
- `*_storyboard.json`
- `*_timed_storyboard.json`
- `*_preview.html`
- `*_quality.json`

这些中间产物使系统不像黑盒生成器，而更像教学视频 authoring workflow。教师或开发者可以审查、编辑和局部重跑。

### 6.5 教学活动和知识检测

PresentAgent 更关注演示清晰度。本项目可以把“活动页”和“知识点检测页”作为教学视频的重要组成部分，并在 quality report 中检查这些教学事件是否覆盖。

这能把系统从 presentation video 推向 teaching video。

## 7. 可对照的限制与本项目增强

| PresentAgent 限制 | 本项目增强方向 | 当前状态 |
| --- | --- | --- |
| 当前生成静态 slide，没有页内动态动画 | HTML/CSS 动画、`slideTimelines`、TTS 后元素触发时间 | 已有 MVP |
| 面向通用演示，不专门面向教材教学 | Lesson Plan、知识点、活动、检测题 | 已有 MVP |
| 生成结果较像黑盒输出 | 中间产物 + preview + quality report + 局部重跑 | 已有基础 |
| 不强调教材原图证据链 | 图片提取、图片引用、图片使用率检查、focus/callout 元素 | 部分实现 |
| VLM 评估成本高 | 先做确定性自动检查，再抽样 VLM/人工评估 | 可实现 |
| 音画同步主要体现在 slide 级别 | 真实 TTS 时长驱动翻页，元素级 trigger | 已有 MVP |

## 8. 建议评估框架：TextbookEval

建议不要完全照搬 PresentEval，而是设计面向教材教学视频的 TextbookEval。

TextbookEval 可以分为三层：

```text
自动确定性评估
  -> 教学内容评估
  -> 人工/学生/VLM 理解评估
```

### 8.1 自动确定性评估

这部分可以直接基于现有 `quality.py` 扩展，成本低，适合每次生成后自动运行。

指标包括：

- Storyboard structure score：页面数、字段完整性、元素 ID、动画 target 是否有效。
- Audio completeness：音频段数是否等于页面数。
- Subtitle coverage：字幕总时长 / 音频总时长。
- Layout pass rate：浏览器 QA 通过率。
- Timing safety：最后动画触发时间是否早于音频结束。
- Image usage ratio：教材图片使用率。
- Knowledge point coverage：storyboard 覆盖 lesson plan 中知识点的比例。
- Instructional event coverage：活动页、检测题页、小结页覆盖率。
- Quiz structure completeness：检测题是否有题干、答案和解释。

### 8.2 教学内容评估

这部分用于证明系统不是单纯生成好看的视频，而是尽量保留教材知识。

建议人工为每个教材章节标注：

- 5-8 个核心知识点。
- 每个知识点对应教材原文位置。
- 必须使用或可选使用的教材图片。
- 3-5 个容易误解点。

评估指标：

- Core knowledge coverage：核心知识点覆盖率。
- Source fidelity：讲稿和画面是否忠实教材。
- Hallucination count：教材外错误或无依据内容数量。
- Image grounding accuracy：图片是否与当前知识点对应。
- Misconception handling：是否解释或避免常见误解。

### 8.3 理解效果评估

这部分对齐 PresentAgent 的 objective quiz，但更贴近教学。

每节课设计 5 道题：

- 2 道事实理解题。
- 1 道概念辨析题。
- 1 道应用题。
- 1 道结构/过程理解题。

评估对象可以包括：

- 人工学生或同学。
- 教师评分。
- VLM/Omni 模型基于 slide frames 和 narration transcript 进行模拟评估。

指标：

- Quiz accuracy。
- Average response confidence。
- Explanation correctness。
- Per-question error type。

## 9. 推荐对比实验

建议至少设置三个系统版本：

```text
A. Static Presentation Baseline
   受 PresentAgent static slide + narration 设置启发。
   保留 slide + narration，但禁用页内元素 timing/动态触发。
   注意：这不是 PresentAgent 官方复现。

B. No Lesson Plan Baseline
   不生成 lesson plan，直接教材 -> script -> storyboard -> timed animation。
   用于观察 lesson plan 对知识点覆盖和教学事件完整性的影响。

C. Full System
   lesson plan + storyboard enhancer/review + timed animation + quality report。
```

如果资源允许，可以增加：

```text
D. No Review / Repair
   去掉 agent review 和 deterministic enhancer。

E. No Textbook Images
   不使用教材原图，只生成文本/图示页面。
```

核心假设建议写成“检验是否”，不要提前写成结论：

- H1：Full System 是否比 No Lesson Plan Baseline 有更高的核心知识点覆盖率。
- H2：Full System 是否比 Static Presentation Baseline 有更好的音画同步和更少 timing warning。
- H3：Full System 是否在理解题准确率和主观教学清晰度上优于 Static Presentation Baseline。
- H4：Review / Repair 是否能减少标题复读、空页面、坏图片引用和动画 target 错误。
- H5：使用教材图片是否能提高图示类知识点的 image grounding accuracy 和理解表现。

## 10. 推荐实验数据规模

课程论文或毕业设计阶段不一定需要很大规模，建议采用“小而严”的评估。

最低可行规模：

- 3 个教材章节。
- 每个章节生成 3 个系统版本。
- 每个视频 5 道理解题。
- 邀请 5-10 名同学或教师进行观看评价。

更完整规模：

- 5-8 个教材章节。
- 覆盖概念讲解、流程讲解、图示讲解、对比辨析、活动检测等类型。
- 每个章节 3-5 个系统版本。
- 每个视频由 2 名人工评审 + 1 个 VLM 评审。

## 11. 论文中可以强调的贡献点

建议贡献点写成以下四个：

1. 提出面向教材章节的教学视频生成流程，引入 Lesson Plan 层建模学习目标、知识点、活动和检测题。

2. 设计结构化 Storyboard 和 Timed Storyboard 中间表示，实现从教材内容到页内动画的可检查、可编辑、可复用生成。

3. 构建模板优先的 HTML 动画渲染与浏览器 QA 机制，提高页面布局稳定性和音画同步可靠性。

4. 提出 TextbookEval 评估设计，并实现其中的确定性自动检查子集，从知识点覆盖、教学事件完整性、教材图片引用、音画同步和布局稳定性等方面评估生成教学视频。

注意：如果没有完成学生实验或 VLM 理解评估，不宜把 TextbookEval 写成完整已验证贡献，而应写成“评估框架设计 + 自动检查实现 + 小规模人工/理解题验证”。

## 12. 后续优先级

最高优先级不是继续加更多生成效果，而是补评估闭环。

建议按以下顺序推进：

1. 完成 TextbookEval 文档和 JSON schema。
2. 扩展 `quality.py`，加入更明确的 source grounding 和 timing alignment 指标。
3. 为 3 个教材章节人工标注知识点、原文证据、教材图片和理解题。
4. 跑 Static Presentation Baseline、No Lesson Plan Baseline、Full System 三组对比。
5. 整理表格：知识点覆盖率、quiz accuracy、layout pass rate、timing warning、人工评分。
6. 把结果写回论文实验章节。

## 13. 最终定位

本项目可以这样概括：

> PresentAgent 证明了长文档可以自动生成带旁白的演示视频；本项目不直接复现 PresentAgent，而是在教材教学场景下引入教学计划、结构化 storyboard、旁白驱动动画、教材图片引用、可编辑中间层和确定性质量检查，研究这些教学约束是否能提升生成视频的可控性、教材忠实度和学习理解效果。
