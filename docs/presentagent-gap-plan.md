# 面向 PresentAgent 的差异化改进计划

> 创建日期：2026-06-23  
> 背景：当前 Textbook-to-Video 已经具备“教材解析 -> 讲稿 -> storyboard -> TTS -> 动画 HTML -> 录制 -> 音画合成”的端到端能力，但如果直接对比 PresentAgent，核心叙事仍然接近：都是长文档到带配音的演示视频。本文目标不是罗列小功能，而是规划一条能形成真实差异的技术路线。
>
> 阅读建议：本文是偏工程实现的专业方案。项目负责人跟进进度请优先看 `docs/presentagent-progress.md`，以后每一版改动都会先记录在那里。

## 0. 结论先行

当前项目相对 PresentAgent 的优势主要在工程落地层：

- 有确定性模板渲染，避免多数页面依赖 LLM 手写 HTML。
- 有浏览器布局 QA、CSS 热修复、原图注入、字幕、TTS 时长驱动等实用链路。
- 支持教材场景，尤其是 DOCX/PDF 教材原图、章节/课节粒度。

但这些优势还没有形成“不可替代的研究/产品卖点”。PresentAgent 已经覆盖了：

- 文档到 presentation video 的任务定义。
- 模块化生成 pipeline。
- slide + narration + audio 的同步合成。
- PresentEval 式多维评估。

因此，本项目要拉开差距，不能只继续补“也能生成视频”的功能，而应转向三个差异化方向：

1. **教材教学导向**：不是泛文档演示，而是围绕课程目标、知识点、教材原图、学习活动的教学视频生成。
2. **可控可编辑导向**：不是黑盒一次出片，而是结构化 storyboard、可预览、可修改、可重跑局部的半自动生产系统。
3. **时间化教学动画导向**：不是静态 slide + 音频，而是旁白驱动的元素入场、强调、局部放大、图文同步。

一句话目标：

> 从“Document-to-Presentation Video”升级为“Textbook-to-Interactive Teaching Video Authoring”，强调教材 grounding、教学节奏、可编辑中间层和自动质量评估。

## 1. 与 PresentAgent 的差距判断

### 1.1 已经接近或重叠的部分

| 能力 | PresentAgent | 本项目现状 | 判断 |
| --- | --- | --- | --- |
| 长文档解析 | 支持 papers/web/blogs/slides/PDF 等 | 支持 PDF/DOCX，但解析依赖特定教材结构 | 思路重叠，本项目通用性弱 |
| slide 规划 | structured slide generation | storyboard JSON | 基本重叠 |
| 旁白生成 | oral-style narration | scriptwriter + narrator | 基本重叠 |
| TTS + 合成 | MegaTTS3 + FFmpeg | edge-tts + FFmpeg | 本项目轻量，质量可能弱 |
| 音画同步 | slide duration/audio alignment | 音频先行 + slideDurations | 本项目工程上已具备 |
| 评估 | PresentEval | 目前主要是校验/布局 QA | 本项目明显弱 |
| 动态动画 | 论文 limitation 中承认静态 slide | 有 HTML/CSS 动画系统 | 本项目潜在优势，但还没形成系统卖点 |

### 1.2 本项目目前“不够特别”的原因

1. **任务定义仍然跟 PresentAgent 太像**  
   README 里写的是教材转视频，但技术叙事仍是“文档 -> 讲稿 -> storyboard -> 视频”。如果不强调教学特性，它看起来就是 PresentAgent 的教材版。

2. **评估维度不够高层**  
   现在能证明“页面不溢出、音频能合成”，但很难证明“学生真的听懂了、知识点覆盖了、教材图用对了”。PresentAgent 的 PresentEval 正好补了这点。

3. **动态动画没有被系统化**  
   目前动画更多是 CSS 入场类和 timeline/trigger_at_sec 的局部机制，还没有成为“旁白语义驱动的教学演示”。

4. **可编辑性没有产品化**  
   项目有 JSON/HTML 中间产物，但没有审阅 UI 或局部重跑机制。用户体验上仍像一键黑盒。

5. **教材 grounding 还只是“原图利用率”**  
   已经有可用图片列表、`src` 注入和利用率检查，但还缺图文对齐、图题关联、局部裁剪、引用理由等。

## 2. 差异化目标

### 2.1 核心定位

本项目应避免跟 PresentAgent 正面抢“通用文档演示视频”。更合适的定位是：

> 面向教材和课程的可控教学视频生成系统：保留教材事实和原图，按教学目标规划讲解节奏，用确定性模板和浏览器 QA 保证版面稳定，并允许教师在 storyboard 层审阅和局部重做。

### 2.2 目标能力矩阵

| 方向 | 要形成的能力 | 为什么能区别于 PresentAgent |
| --- | --- | --- |
| 教学目标建模 | 每节课有 learning objectives、knowledge points、misconceptions、activities | PresentAgent 主要是演示视频，不建模教学目标 |
| 教材 grounding | 图片、表格、章节标题、图注与页面内容显式绑定 | 避免泛化摘要，强调教材证据链 |
| 时间化讲解 | 旁白句子和画面元素逐步同步 | PresentAgent 当前主要是静态 slides |
| 可编辑工作流 | storyboard preview/editor + 局部重跑 | 从生成器变成 authoring tool |
| 自动评估 | 内容覆盖、理解题、原图使用、音画同步、字幕、布局、音频质量 | 建立可比较的质量报告 |

## 3. 总体架构调整

建议将 pipeline 从现在的一条线扩展为“两层中间表示 + 三类反馈”。

### 3.1 新增 Lesson Plan 层

当前：

```text
教材 -> script -> storyboard -> audio/html/video
```

建议：

```text
教材 -> lesson_plan -> script -> storyboard -> timed_storyboard -> html/video
```

`lesson_plan` 是教学语义层，不直接管视觉：

```json
{
  "lesson_title": "算法与程序",
  "objectives": [
    "理解算法是解决问题的有限步骤",
    "区分算法、程序和编程语言"
  ],
  "knowledge_points": [
    {
      "id": "kp1",
      "name": "算法",
      "source_spans": ["p12:3-6"],
      "suggested_visual": "definition",
      "required_images": ["fig3-1"]
    }
  ],
  "misconceptions": [
    "把算法等同于代码"
  ],
  "activities": [
    "让学生用自然语言描述刷牙步骤，再抽象成算法"
  ]
}
```

价值：

- scriptwriter 不再只做摘要，而是围绕教学目标写讲稿。
- storyboard 不再凭讲稿自由发挥，而是覆盖每个 knowledge point。
- evaluation 可以检查知识点覆盖率。

### 3.2 新增 Timed Storyboard 层

当前 storyboard 里让 LLM 写 `trigger_at_sec`，但 storyboard 生成时通常还没有真实 TTS 时长。建议将 timing 从 storyboard 后移：

```text
storyboard + TTS durations + subtitle cues -> timed_storyboard
```

`timed_storyboard` 示例：

```json
{
  "segment_id": 3,
  "audio_duration_sec": 12.4,
  "cues": [
    {
      "start": 0.0,
      "end": 3.1,
      "text": "算法是一组解决问题的明确步骤。",
      "show": ["e1", "e2"]
    },
    {
      "start": 3.1,
      "end": 7.8,
      "text": "它不等同于程序，程序只是算法的一种实现。",
      "show": ["e3"],
      "highlight": ["e2", "e3"]
    }
  ]
}
```

生成方法：

1. `subtitles.py` 已能按 narration 切分 cue，可复用。
2. 根据 cue 文本和 element 文本做相似度匹配。
3. 无法匹配时按元素顺序均匀分配。
4. 输出 `animations[].trigger_at_sec` 或直接输出新字段 `cues`，由 `animation_gen.py` 转换为 `slideTimelines`。

注意：`storyboard.md` 中现有 `timeline` 和 `animations.trigger_at_sec` 语义重复，建议长期收敛为一个标准字段。

### 3.3 三类反馈闭环

| 反馈类型 | 输入 | 输出 | 用途 |
| --- | --- | --- | --- |
| 静态校验 | lesson_plan/storyboard | errors/warnings | schema、密度、图片、时长 |
| 浏览器 QA | HTML | layout report | 溢出、遮挡、空白、初始页 |
| 教学质量评估 | 教材 + storyboard + 视频/字幕 | quality_report | 知识点覆盖、理解题、音画同步 |

PresentAgent 的评估是生成后评估；本项目应做“生成前约束 + 生成后评估 + 可局部修复”。

## 4. 分阶段实施计划

### Phase 1：把现有能力整理成稳定产品基线

目标：先把项目已有但分散的能力收拢，建立质量报告雏形。

### 4.1 更新字幕路线

现状：`pipeline/subtitles.py`、`compose.py` 的 `subtitle_path`、`t2v subtitle`、`produce --no-subtitles` 已存在。`docs/improvements.md` 还把字幕列为待做，文档落后。

要做：

- 更新 `docs/improvements.md`：字幕改为“已实现，后续优化字幕质量”。
- 在 README 中明确 `produce` 默认生成/挂载字幕。
- 在 `quality_report.json` 中加入：
  - `subtitle_cues_count`
  - `subtitle_total_duration`
  - `subtitle_coverage_ratio`
  - `long_cue_warnings`

验收：

- `t2v produce ...` 默认输出 `.srt` 和带字幕轨 MP4。
- `pytest tests/test_subtitles.py tests/test_compose.py` 通过。

### 4.2 中间产物复用

要做：

- `produce --from-script`
- `produce --from-storyboard`
- `produce --from-html`

推荐行为：

| 参数 | 跳过步骤 | 仍执行 |
| --- | --- | --- |
| `--from-script` | parser/scriptwriter | storyboard/narrate/animate/record/mux |
| `--from-storyboard` | parser/scriptwriter/storyboard | narrate/animate/record/mux |
| `--from-html` | generate/animate | record/mux |

验收：

- 改主题和 CSS 时不需要重跑 LLM 讲稿/大纲。
- `tests/test_orchestrator.py` 增加接线测试。

### 4.3 第一版质量报告

新增模块：

```text
src/textbook2video/pipeline/quality.py
```

输入：

- storyboard JSON
- layout report JSON（如果存在）
- subtitle SRT
- final MP4（可选）

输出：

```json
{
  "ok": true,
  "scores": {
    "layout": 0.95,
    "audio": 0.90,
    "subtitle": 0.88,
    "image_grounding": 0.70
  },
  "warnings": [
    "segment[2] audio_duration_sec 过短，动画可能来不及完成"
  ],
  "artifacts": {
    "srt": "ch3_s0.srt",
    "layout_report": "ch3_s0.layout.json"
  }
}
```

第一版不需要 VLM，只做确定性指标：

- slide 数量一致。
- layout QA 是否通过。
- 音频文件是否齐全。
- 字幕是否覆盖所有 narration。
- 教材原图利用率。
- 每页音频时长是否大于最大动画延迟 + buffer。

验收：

- `t2v produce` 结束后输出 `*_quality.json`。
- `t2v validate` 可选择生成质量报告。

### Phase 2：建立“教材教学语义层”

目标：让项目从泛文档演示转为教学视频生成。

### 4.4 新增 lesson_plan 生成

新增文件：

```text
src/textbook2video/pipeline/lesson_plan.py
src/textbook2video/llm/prompts/lesson_plan.md
tests/test_lesson_plan.py
```

职责：

- 从 parser 输出的章节文本、标题、图片列表生成教学计划。
- 不生成讲稿，不生成画面，只抽教学结构。

建议 schema：

```json
{
  "lesson_title": "...",
  "audience": "大学通识课学生",
  "objectives": [],
  "knowledge_points": [],
  "source_outline": [],
  "required_images": [],
  "activities": [],
  "assessment_questions": []
}
```

方法：

1. parser 输出保留段落来源，例如 page/paragraph index。
2. LLM 生成 lesson_plan，并要求每个 knowledge point 带 `source_refs`。
3. `checks.py` 校验：
   - 每个 objective 至少被一个 knowledge point 覆盖。
   - 每个 required image 被至少一个 knowledge point 引用。
   - `assessment_questions` 数量 3-5。

为什么有价值：

- PresentAgent 做的是通用内容选择，本项目可以做教学目标驱动。
- 后续评估能围绕 objective/KP，而非只看模糊“内容质量”。

### 4.5 scriptwriter 改为 lesson_plan 驱动

当前 scriptwriter 从教材文本直接写讲稿。建议改为：

```text
lesson_plan + source_text -> script_segments
```

讲稿段结构建议从纯文本升级为结构化：

```json
{
  "id": 1,
  "knowledge_point_ids": ["kp1"],
  "narration": "...",
  "teaching_move": "definition|example|contrast|activity|summary",
  "estimated_duration_sec": 14
}
```

这样 storyboard 可以知道一页是定义、例子、对比还是活动，不必只猜 visual_type。

### 4.6 storyboard 绑定知识点和来源

segment 增加：

```json
{
  "knowledge_point_ids": ["kp1"],
  "source_refs": ["p12:3-6"],
  "grounding": {
    "images": [
      {"src": "fig3-1.png", "reason": "教材原图展示算法流程示例"}
    ]
  }
}
```

校验：

- 每个 `knowledge_point_id` 必须存在于 lesson_plan。
- 每张教材图必须说明 reason。
- 页面上出现教材图时，narration 或 elements 至少有一个相关关键词。

这能把“用了图”升级为“用对图”。

### Phase 3：旁白驱动的时间化动画

目标：形成比 PresentAgent 静态 slide 更明显的能力差异。

### 4.7 移除 LLM 精确秒数责任

问题：

- `storyboard.md` 要求 LLM 写 timeline 和 `trigger_at_sec`。
- 但真实时长来自 TTS，LLM 只能猜。

方案：

- storyboard 阶段只生成 `animation_intents`：

```json
[
  {"target": "e1", "intent": "intro"},
  {"target": "e2", "intent": "reveal_when_mentioned"},
  {"target": "e3", "intent": "highlight_contrast"}
]
```

- narrate/subtitles 后生成 timing：

```text
animation_intents + subtitle_cues + audio_duration_sec -> slideTimelines
```

新增模块：

```text
src/textbook2video/pipeline/timing.py
tests/test_timing.py
```

核心算法：

1. 对每个 element 抽取关键词：
   - `text`
   - `items`
   - `steps`
   - table headers/cells
2. 对每个 subtitle cue 抽取文本。
3. 用简单相似度匹配：
   - 中文可先用字符 n-gram/Jaccard，不引入重依赖。
   - 后续可接 embeddings。
4. 匹配成功：元素在该 cue start 附近出现。
5. 匹配失败：按元素顺序均匀分布。
6. 最后限制：
   - 第一个主标题 0-0.3s 出现。
   - 最后一个入场不超过 duration 的 80%。
   - 相邻动作至少间隔 0.3s。

验收：

- 给定 narration + elements，能稳定生成单调递增的 trigger 时间。
- 短音频页面自动压缩动画数量或合并触发。
- `validate_storyboard` 对过短页面给 warning。

### 4.8 增加教学动画类型

不要追求炫技动画，要围绕教学动作：

| 教学动作 | 动画表达 |
| --- | --- |
| 定义出现 | quote/highlight_box 淡入 |
| 对比关系 | 左右栏先后出现，然后中间 VS/箭头强调 |
| 流程 | step 逐个入场，当前步骤高亮 |
| 图像讲解 | 先显示整图，再显示局部框/标注 |
| 误区纠正 | 错误说法淡出，正确说法替换 |
| 活动指令 | 步骤卡片逐个出现，最后停留总结 |

新增 element：

- `callout`：图片局部标注。
- `focus_box`：教材图局部框选。
- `misconception_pair`：误区/正解对照。

模板渲染器优先支持这些类型，LLM 只产结构。

### Phase 4：可编辑 authoring workflow

目标：从一次性生成器变成教师可用工具。

### 4.9 Storyboard Preview

新增命令：

```bash
t2v preview output/ch3_s0_storyboard.json --theme dark-blue-academic
```

功能：

- 启动本地页面。
- 左侧列表：每页 narration、visual_type、render_mode、elements。
- 右侧 iframe：调用现有 `animate` 的模板渲染预览，或轻量只渲染单页。
- 支持修改 JSON 后保存。

第一版可以不用复杂前端框架：

- Python 起一个 `http.server`。
- 静态 HTML + 原生 JS。
- 保存通过本地 API 写回 JSON。

注意：

- 不要把它做成营销页。第一屏就是编辑器。
- 所有编辑都作用于 storyboard，不直接改最终 HTML。

### 4.10 局部重跑

支持：

```bash
t2v narrate storyboard.json --only 3
t2v animate storyboard.json --only 3
t2v produce ... --resume-from storyboard
```

优先级：

1. 先支持从已有 storyboard 继续 produce。
2. 再支持只重配某页音频。
3. 最后支持只重渲染某页 HTML 并重新合并。

价值：

- 教师改一页不需要重跑全链。
- 开发调视觉主题成本大幅下降。

### Phase 5：PresentEval 的教学版

目标：建立能说明本项目比 PresentAgent 更适合教材教学的评估体系。

### 4.11 TextbookEval 指标

分为四组：

#### A. Content Grounding

- `objective_coverage`：lesson objectives 被讲稿/storyboard 覆盖比例。
- `knowledge_point_coverage`：knowledge points 覆盖比例。
- `source_fidelity`：页面可见文字/旁白是否能追溯到 source_refs。
- `image_grounding`：教材图引用是否有 reason，是否与页面主题相关。

#### B. Teaching Clarity

- `progression`：是否从概念、例子、对比、活动到总结逐步推进。
- `cognitive_load`：每页元素密度是否过高。
- `misconception_handling`：是否显式处理常见误区。
- `activity_presence`：是否包含学习活动/提问。

#### C. Temporal Alignment

- `subtitle_coverage`：字幕是否覆盖 narration。
- `cue_element_alignment`：元素出现是否接近对应字幕 cue。
- `animation_pacing`：页面是否过久静止或过快堆叠。
- `audio_visual_duration_match`：音视频时长差。

#### D. Production Quality

- `layout_pass_rate`
- `audio_volume_ok`
- `blank_frame_rate`
- `subtitle_track_present`
- `failed_pages_count`

### 4.12 自动理解题

借 PresentAgent 的 quiz evaluation，但改成教学版：

1. 从 lesson_plan 的 objectives/knowledge_points 生成 3-5 个选择题。
2. 题目类型：
   - 概念识别
   - 结构理解
   - 例子应用
   - 误区判断
3. 生成视频后，用字幕文本 + slide 截图回答。

如果没有可用 VLM，第一版可以只用字幕文本做 text-only quiz eval；后续再接 VLM。

输出：

```json
{
  "quiz": {
    "questions": 5,
    "correct": 4,
    "score": 0.8,
    "failed": [
      {
        "question_id": "q3",
        "knowledge_point_id": "kp2",
        "reason": "视频未明确区分算法和程序"
      }
    ]
  }
}
```

### 4.13 评估命令

新增：

```bash
t2v evaluate storyboard.json --video final.mp4 --lesson-plan lesson_plan.json
```

也可由 `produce` 自动调用：

```bash
t2v produce textbook.docx -c 3 -s 0 --evaluate
```

## 5. 文件级实施清单

### 新增文件

```text
src/textbook2video/pipeline/lesson_plan.py
src/textbook2video/pipeline/timing.py
src/textbook2video/pipeline/quality.py
src/textbook2video/llm/prompts/lesson_plan.md
docs/presentagent-gap-plan.md
tests/test_lesson_plan.py
tests/test_timing.py
tests/test_quality.py
```

### 重点修改文件

| 文件 | 修改 |
| --- | --- |
| `pipeline/orchestrator.py` | 串入 lesson_plan、quality report、from-* resume |
| `pipeline/scriptwriter.py` | 支持 lesson_plan 驱动 |
| `pipeline/storyboard.py` | 增加 knowledge_point/source/image grounding 字段 |
| `pipeline/checks.py` | 校验 lesson_plan/storyboard grounding/timing |
| `animation_gen.py` | 接受 timed_storyboard 或统一后的 slideTimelines |
| `template_renderer.py` | 支持教学元素：callout/focus_box/misconception_pair |
| `cli.py` | 新增 `preview`、`evaluate`，扩展 `produce` 参数 |
| `docs/improvements.md` | 更新已完成项和引用本文 |

## 6. 推荐实施顺序

### 第 1 周：整理现有基线

- 更新字幕文档状态。
- 实现 `quality.py` 第一版确定性报告。
- `produce` 输出 `*_quality.json`。
- 增加 `--from-storyboard`。

验收：

- 不依赖新 LLM 能力。
- 全量 pytest 通过。
- 跑一个真实课节能看到质量报告。

### 第 2 周：Lesson Plan MVP

- 新增 `lesson_plan.py` 和 prompt。
- 在 `generate-docx/generate` 阶段保存 `*_lesson_plan.json`。
- scriptwriter/storyboard 暂时只读取 objectives 和 available_images，不大改结构。

当前落地状态（2026-06-23）：

- 已新增 `pipeline/lesson_plan.py`、`llm/prompts/lesson_plan.md` 和 `tests/test_lesson_plan.py`。
- `generate` / `generate-docx` / `script` / `produce` 默认生成并保存 `*_lesson_plan.json`，然后把 lesson plan 注入 scriptwriter 和 storyboard prompt。
- `storyboard` / `produce --from-storyboard` 会自动发现同目录的 `*_lesson_plan.json`，用于后续质量报告。
- `quality.py` 已在 lesson plan 存在时输出 `knowledge_point_coverage`，并对未覆盖知识点给 warning。

验收：

- 每个 storyboard segment 至少绑定一个 knowledge point。
- quality report 能输出 objective/KP 覆盖率。

### 第 3 周：Timed Storyboard

- 新增 `timing.py`。
- `narrate` 后生成 `*_timed_storyboard.json` 或回写 timing。
- `animate` 优先使用 timing 结果，而不是信任 LLM 秒数。

当前落地状态（2026-06-23）：

- 已新增 `pipeline/timing.py` 和 `tests/test_timing.py`。
- `run_tts` 会在真实 TTS 时长写回后，基于字幕 cue 和 element 文本生成 `animations[].trigger_at_sec`。
- 原 `*_storyboard.json` 会写入 timing，保证现有 `animation_gen.build_slide_timelines` 能直接使用。
- 同时额外输出 `*_timed_storyboard.json`，方便人工检查时间化结果。
- `generate` / `generate-docx` 的旧 CLI TTS 流程也已接入 timing。

验收：

- 短旁白不会出现最后动画太晚。
- 字幕 cue 与元素入场时间可解释。

### 第 4 周：Preview + 局部重跑

- `t2v preview` MVP。
- `produce --from-storyboard` 完善。
- 支持保存 JSON 后只重跑后半段。

当前落地状态（2026-06-23）：

- 已新增 `pipeline/preview.py` 和 `tests/test_preview.py`。
- 已新增 `t2v preview storyboard.json` 命令，可选 `--open`。
- 默认输出 storyboard 同目录的 `*_preview.html`，例如 `ch3_s0_storyboard.json` 会生成 `ch3_s0_preview.html`。
- 第一版只读预览：左侧按页浏览和搜索，右侧查看 narration、elements、animations、原始 segment JSON。
- 已新增 `t2v preview storyboard.json --edit --open`，启动本地服务并允许保存修改。
- 编辑模式先改当前页 segment JSON，再由服务端保存整份 storyboard。
- 保存前运行 `validate_storyboard`，有致命错误会拒绝写入。
- 第一次成功保存前会生成 `*.json.bak`，方便恢复编辑前版本。
- 还没有实现 `narrate --only` / `animate --only`。

验收：

- 人工改一页 narration/elements 后能重新出片。

### 第 5 周以后：教学评估与新元素

- TextbookEval quiz。
- `callout/focus_box/misconception_pair`。
- 可选接入 VLM 评价截图/视频片段。

## 7. 风险与取舍

### 7.1 不要过早追求 VLM 大评估

PresentAgent 用 VLM 做评估是亮点，但直接照搬会带来成本和不稳定。建议先做确定性质量报告，再接 VLM。

优先级：

1. 可确定的事实：文件、时长、字幕、布局、图像引用。
2. 可解释的文本评估：objective/KP coverage、quiz。
3. VLM 评估：视觉设计、图文一致性、观众理解。

### 7.2 不要把 PPTX 作为主输出

SlideTailor 强调可编辑 PPTX，但本项目的强项是 HTML 动画 + 浏览器录制。可以做 storyboard editor，不必立刻转 PPTX。

PPTX 会削弱：

- 动态动画能力。
- 浏览器布局 QA。
- 单文件 HTML 的可复现性。

### 7.3 不要继续加复杂 prompt

现有文档反复证明复杂 prompt 是历史病根。新增 lesson_plan/timing/profile 时，应尽量让 LLM 做语义决策，让 Python 做结构、时间、渲染。

原则：

- LLM 负责：抽象、取舍、解释、教学活动建议。
- Python 负责：schema 校验、时间分配、布局、动画类、文件合成。

## 8. 成功标准

如果这条路线完成，本项目相对 PresentAgent 的差异可以这样表达：

1. **不是只生成演示视频，而是生成有教学目标和知识点覆盖报告的教材讲解视频。**
2. **不是静态 slide 加旁白，而是旁白 cue 驱动的时间化教学动画。**
3. **不是一次性黑盒输出，而是 storyboard 可编辑、可预览、可局部重跑的 authoring workflow。**
4. **不是只看主观质量，而是输出可解释的 TextbookEval 质量报告。**
5. **不是泛用图片生成，而是优先使用教材原图并保留图文 grounding。**

这五点都落地后，项目才真正有“比 PresentAgent 更适合教材教学视频”的说法。
