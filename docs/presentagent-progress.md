# PresentAgent 差异化改进：通俗进展记录

> 这份文档是给项目负责人快速跟进用的。它不写太多代码细节，只记录“这一版解决了什么、为什么重要、现在怎么看成果、下一步做什么”。
>
> 专业实现方案仍放在 `docs/presentagent-gap-plan.md`。以后每一版改动，都先更新本文件，再补充技术文档。

## 一句话目标

我们不只是做一个“教材转视频”的 PresentAgent 平替，而是要做一个更适合教材教学的系统：

- 先理解一节课要教什么；
- 再生成讲稿和画面；
- 再按真实配音时间安排动画；
- 最后能检查知识点、字幕、图片、版面和音画同步。

## 当前总体状态

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| Phase 1：可复用和质量报告 | 已完成第一版 | 可以从中间产物继续出片，默认输出字幕和质量报告 |
| Phase 2：Lesson Plan 教学语义层 | 已完成 MVP | 生成讲稿前先生成教学计划，并检查知识点覆盖 |
| Phase 3：Timed Storyboard 时间层 | 已完成 MVP | TTS 后按字幕和元素文本生成可解释的动画触发时间 |
| Phase 4：预览和局部重跑 | 已完成局部检查工作流 | 可以编辑 storyboard，只重配指定页音频，只生成指定页 HTML，并显示下一步命令 |
| 差异化能力：教材图讲解 | 已完成 MVP | 教材图可叠加 focus_box/callout，支持局部框选和标注 |
| 差异化能力：教学活动页 | 已完成 MVP | Lesson Plan 里的活动、检测题和小结会进入 storyboard |
| Phase 5：教学评估 | 未开始 | 做 TextbookEval 风格的教学质量评价 |

## 你需要先理解的三个文件

### 1. `*_lesson_plan.json`

这是新增的“教学计划”。它回答：

- 这节课的学习目标是什么；
- 有哪些知识点；
- 哪些知识点适合用教材原图；
- 可以设计什么课堂活动；
- 可以用什么问题检查理解。

它的意义是：后面的讲稿和 storyboard 不再只是“把教材总结成视频”，而是围绕教学目标来组织。

### 2. `*_storyboard.json`

这是每一页画面的大纲。它回答：

- 每页讲什么；
- 页面上有哪些文字、图片、流程、表格等元素；
- 每页对应哪些知识点。

现在它会尽量带上 `knowledge_point_ids`，方便后面检查“有没有漏讲知识点”。

### 3. `*_quality.json`

这是质量报告。它回答：

- storyboard 结构是否正常；
- 音频段数是否齐；
- 字幕覆盖是否完整；
- 教材图片使用情况怎样；
- 如果有 lesson plan，知识点覆盖率是多少。

更白话地说，质量报告就是“生成后自动体检单”。它不是视频本身，而是程序在生成完视频后，自动检查这一节课的各个产物有没有明显问题，然后写成一个 JSON 文件。

例如输出目录里可能有：

```text
ch3_s0.mp4
ch3_s0_storyboard.json
ch3_s0_audio/
ch3_s0.srt
ch3_s0_quality.json
```

其中 `ch3_s0_quality.json` 就是质量报告。它现在更像第一版自动质检，不是“教学质量评分老师”。它不会真正判断“讲得好不好、学生能不能学会”，但会检查有没有明显生成事故：

- 生成了 8 页，但音频目录里只有 7 段音频；
- 某页音频只有 4 秒，但动画安排到第 6 秒才出现；
- 教材里提取了 5 张图，但 storyboard 一张都没引用；
- 字幕覆盖明显不足；
- 浏览器布局 QA 报告里有失败页面；
- 有 lesson plan 时，某些知识点没有被 storyboard 覆盖。

所以它的价值是：以后我们不是只看最后有没有 mp4，而是每次生成后都有一张“检查清单”，能快速发现哪里坏了。

## Timed Storyboard 是什么

### 先说结论

Timed Storyboard 就是“给每一页里的元素安排准确出现时间”。

可以这样理解：先把旁白录出来，知道这一页真实时长；再看旁白每句话大概在什么时候；最后让页面元素尽量在“被讲到”的附近出现。

普通 storyboard 只说：

> 这一页有标题、定义、例子、图片。

Timed Storyboard 进一步说：

> 0.0 秒显示标题，2.3 秒显示定义，5.8 秒高亮图片里的关键区域，8.4 秒显示例子。

### 为什么现在需要它

现在的问题是：LLM 在生成 storyboard 时，还不知道真实配音有多长。

比如 LLM 可能猜：

```json
{"target": "e3", "trigger_at_sec": 8.0}
```

但真实 TTS 配音出来后，这一页可能只有 6 秒。那第 8 秒的动画根本来不及出现。

反过来也可能：真实配音有 18 秒，但所有元素 3 秒内就全出来了，后面画面会显得很死。

所以更稳的做法是：

1. 先生成 storyboard，只决定“有哪些元素”和“动画意图”；
2. 再生成 TTS，拿到真实音频时长；
3. 再生成字幕 cue，知道旁白每一句大概在几秒；
4. 最后由 Python 算法把元素匹配到对应句子上，生成 Timed Storyboard。

更准确的流程是：

1. 先有 storyboard。
   它已经知道这一页有哪些元素，比如标题、定义卡片、图片、流程步骤、对比表等。
2. 再录旁白，也就是跑 TTS。
   TTS 完成后，系统才知道这一页真实音频多长，比如 8.6 秒。
3. 再把旁白切成字幕 cue。
   例如 `0.0-2.1 秒` 是第一句话，`2.1-5.0 秒` 是第二句话。
4. 然后把页面元素和字幕文本做匹配。
   如果元素文字是“明确步骤”，它就更可能在讲到“明确步骤”的时间附近出现。
5. 最后给每个元素写一个确定时间。
   例如 `e1` 在 0.0 秒出现，`e2` 在 1.2 秒出现，`e3` 在 3.0 秒出现。

如果匹配不上，系统就按元素顺序和页面总时长平均安排，保证不会乱跳，也不会太晚出现。

### 一个白话例子

旁白是：

```text
算法是一组解决问题的明确步骤。
它不等同于程序，程序只是算法的一种实现。
```

页面元素是：

```text
e1: 标题“算法”
e2: 定义卡片“解决问题的明确步骤”
e3: 对比卡片“算法 vs 程序”
```

Timed Storyboard 应该安排成：

| 时间 | 画面动作 |
| --- | --- |
| 0.0 秒 | 显示标题 e1 |
| 1.2 秒 | 旁白讲“明确步骤”时显示定义 e2 |
| 4.5 秒 | 旁白讲“不等同于程序”时显示对比卡片 e3 |

这比让 LLM 随便写秒数可靠，因为它用的是已经生成出来的真实音频和字幕。

### 它和 PresentAgent 的差异

PresentAgent 更接近“静态 slide + 配音”。Timed Storyboard 要让我们变成：

> 旁白讲到哪里，画面就动到哪里。

这是教材视频比普通演示视频更重要的地方，因为教学视频需要“跟着老师讲解一步步出现”，而不是一页东西一次性全部铺满。

## 版本记录

### 2026-06-23：Phase 1，产物复用和质量报告

提交：`2647155 feat: add produce reuse and quality report`

做了什么：

- `produce` 支持 `--from-script`、`--from-storyboard`、`--from-html`。
- 默认输出 `*_quality.json`。
- 质量报告检查 storyboard、音频、字幕、布局报告、教材图片使用率、动画触发时间风险。
- README 和 `docs/improvements.md` 更新了字幕、复用、质量报告状态。

为什么重要：

- 改一点样式或 HTML，不用重跑整条 LLM 链路。
- 以后每次生成视频，都能留下一个可检查的质量报告。

怎么看成果：

- 跑 `t2v produce ...` 后，看输出目录里的 `*_quality.json`。
- 如果已有 storyboard，可以用 `t2v produce ... --from-storyboard xxx_storyboard.json` 继续出片。

### 2026-06-23：Phase 2，Lesson Plan 教学语义层 MVP

提交：`8cedfd4 feat: add lesson plan semantic layer`

做了什么：

- 新增 `src/textbook2video/pipeline/lesson_plan.py`。
- 新增 `src/textbook2video/llm/prompts/lesson_plan.md`。
- `generate`、`generate-docx`、`script`、`produce` 会生成 `*_lesson_plan.json`。
- scriptwriter 和 storyboard 会读取 lesson plan，让讲稿和画面围绕教学目标、知识点展开。
- storyboard prompt 增加 `knowledge_point_ids`。
- `*_quality.json` 增加 `knowledge_point_coverage`。

为什么重要：

- 这是从“文档视频生成”转向“教学视频生成”的第一步。
- 后续评估可以说清楚：这节课哪些知识点讲到了，哪些没讲到。

怎么看成果：

- 输出目录会多一个 `*_lesson_plan.json`。
- `*_quality.json` 里会出现 `checks.lesson_plan` 和 `scores.knowledge_point_coverage`。

还没做到什么：

- 还没有强制每一页都必须绑定知识点。
- 还没有验证教材原文和知识点的严格对应关系。
- 还没有 Timed Storyboard，所以动画时间仍然不够聪明。

### 2026-06-23：Phase 3，Timed Storyboard 时间层 MVP

提交：`82b3bb6 feat: add timed storyboard generation`

做了什么：

- 新增 `src/textbook2video/pipeline/timing.py`。
- 新增 `tests/test_timing.py`。
- `run_tts` 在写入真实 `audio_duration_sec` 后，会自动生成元素级 `trigger_at_sec`。
- 输出目录会额外生成 `*_timed_storyboard.json`。
- 原 `*_storyboard.json` 也会写入 timing，现有 `animation_gen` 可以继续读取 `animations[].trigger_at_sec` 并注入 `slideTimelines`。
- CLI 的 `generate` / `generate-docx` 手写 TTS 流程也补上了 timing。

为什么重要：

- 动画时间不再主要依赖 LLM 猜秒数。
- 元素会尽量在旁白字幕讲到相关内容时出现。
- 匹配不上时按元素顺序均匀分配，结果可解释、可复现。
- 短音频页面会把最后动画限制在音频前段，避免“动画还没出现就切页”。

怎么看成果：

- 跑带 TTS 的生成流程后，查看 `*_timed_storyboard.json`。
- 看每个 segment 的 `animations[].trigger_at_sec`。
- 最终 HTML 里仍然由已有 `slideTimelines` 机制负责播放这些时间点。

还没做到什么：

- 现在是文本相似度和顺序分配，不是语义 embedding 匹配。
- 还没有把 `storyboard.md` 里旧的 timeline / trigger prompt 完全收敛掉。
- 还没有做逐页局部重跑和可视化预览。

### 2026-06-23：Phase 4，Storyboard Preview MVP

提交：`e8d7adb feat: add storyboard preview html`

做了什么：

- 新增 `src/textbook2video/pipeline/preview.py`。
- 新增 `t2v preview storyboard.json` 命令。
- 默认在 storyboard 同目录生成 `*_preview.html`。
- 支持 `--open`，生成后自动用浏览器打开。
- 预览页左侧显示页面列表，可搜索 narration、visual_type、元素文本。
- 右侧显示当前页的旁白、元素、动画时间和原始 JSON。
- 新增 `tests/test_preview.py`，覆盖 HTML 生成、默认输出路径和非法 JSON 拒绝。

为什么重要：

- 以前要理解 storyboard，只能直接读一大段 JSON。
- 现在可以按页查看：这一页讲什么、有哪些元素、动画什么时候出现。
- 这一步是后面“改一页、保存、从 storyboard 继续出片”的基础。

怎么看成果：

```bash
t2v preview output/ch3/ch3_s0_storyboard.json --open
```

如果不加 `--open`，它只会生成 HTML 文件，例如：

```text
output/ch3/ch3_s0_preview.html
```

还没做到什么：

- 目前是只读预览，不能在页面里直接保存修改。
- 还没有只重跑某一页音频或只重渲染某一页 HTML。
- 右侧现在展示的是 storyboard 结构预览，不是最终动画画面的 iframe 播放。

### 2026-06-23：Phase 4.2，可编辑预览和安全保存

提交：`0600673 feat: add editable storyboard preview`

做了什么：

- `t2v preview` 新增 `--edit`。
- `--edit` 会启动本地 preview server，而不是只生成静态 HTML。
- 页面里可以编辑当前页的 segment JSON。
- 点击 `Apply Segment` 先把当前页修改应用到浏览器内存。
- 点击 `Save Storyboard` 会把整份 storyboard 发给本地服务端保存。
- 服务端保存前会运行 `validate_storyboard`。
- 如果有致命错误，比如缺少 narration，会拒绝写入原文件。
- 第一次成功保存前，会自动生成 `原文件.json.bak` 备份。
- 新增测试覆盖编辑模式 HTML、保存备份、非法 storyboard 拒绝。

为什么重要：

- 你现在可以在预览页里改某一页，而不是用编辑器在整份 JSON 里找位置。
- 保存前有校验，能降低“手滑把 storyboard 写坏”的风险。
- `.bak` 文件让第一次编辑前的版本可以直接找回来。

怎么看成果：

```bash
t2v preview output/ch3/ch3_s0_storyboard.json --edit --open
```

使用方式：

- 左侧选中要改的页面。
- 右侧修改 `Segment JSON`。
- 点 `Apply Segment`，先确认这一页 JSON 能解析。
- 点 `Save Storyboard`，保存回原 storyboard。
- 如果想恢复第一次编辑前的版本，看同目录的 `ch3_s0_storyboard.json.bak`。

还没做到什么：

- 还没有表单化编辑，比如单独输入 narration、element text。
- 还没有单页动画 iframe 播放。
- 还没有 `narrate --only` / `animate --only`，所以改完后仍然主要配合 `produce --from-storyboard` 继续出片。

### 2026-06-23：Phase 4.3，`narrate --only` 音频局部重跑

提交：`9545d7c feat: support partial narrate reruns`

做了什么：

- `t2v narrate` 新增 `--only` 参数。
- 支持单页：`--only 3`。
- 支持多页和范围：`--only 2,4-6`。
- 页码是 1-based，也就是第 3 页对应 `s3.mp3`。
- 局部重配时，只替换指定页对应的 `sN.mp3`。
- 未选中的页会沿用已有 `audio_duration_sec`。
- 重配后会重新写回 storyboard，并刷新 `*_timed_storyboard.json`。
- 新增测试覆盖局部重配、页码解析和非法页码拒绝。

为什么重要：

- 在 preview 里改了第 3 页 narration 后，不需要重配整节课音频。
- 这让“改一页、看一页”的反馈速度明显变短。
- 文件命名保持不变，后续 `mux` / `produce --from-storyboard` 仍然能按 `s1.mp3、s2.mp3...` 找音频。

怎么看成果：

```bash
t2v narrate output/ch3/ch3_s0_storyboard.json --only 3
t2v narrate output/ch3/ch3_s0_storyboard.json --only 2,4-6
```

还没做到什么：

- 还没有安全替换完整 HTML 中的单页 slide。
- `produce` 还没有一键“只重配指定页再继续出片”的参数。
- preview 保存后还不会自动提示下一条命令。

### 2026-06-23：Phase 4.4，`animate --only` 局部 HTML 检查

提交：`4419951 feat: add partial animate html generation`

做了什么：

- `t2v animate` 新增 `--only` 参数。
- 支持单页：`--only 3`。
- 支持多页和范围：`--only 2,4-6`。
- 页码仍然是 1-based。
- 只把选中的 segment 送进动画生成流程。
- 输出文件名会带页码后缀，避免覆盖完整 HTML。

例子：

```bash
t2v animate output/ch3/ch3_s0_storyboard.json --only 3 --theme dark-blue-academic
```

可能输出：

```text
output/ch3_s0-p3-pipeline-dark-blue-academic.html
```

为什么重要：

- 在 preview 里改了第 3 页 elements 后，可以只生成第 3 页 HTML 看画面。
- 不需要为了检查一页画面，先等整节课所有页面都重新生成。
- 这和 `narrate --only` 拼起来，已经能支撑“先局部检查，再完整出片”的工作流。

重要边界：

- 这版不是把已有完整 HTML 的第 3 页原地替换。
- 它生成的是只包含指定页的局部 HTML。
- 真正最终成片仍建议在确认局部页没问题后，跑完整 `animate` 或 `produce --from-storyboard`。

还没做到什么：

- 还没有安全替换完整 HTML 中的单页 slide。

### 2026-06-23：Phase 4.5，Preview 保存后的操作提示

提交：`d57f858 feat: show preview save workflow commands`

做了什么：

- `preview --edit` 保存成功后，会在页面里显示下一步命令。
- 命令会根据当前页自动带上 `--only N`。
- 显示 `t2v validate ...`，先检查 storyboard 是否还能通过校验。
- 显示 `t2v narrate ... --only N`，只重配当前页音频。
- 显示 `t2v animate ... --only N`，只生成当前页 HTML 供检查。
- 显示 `t2v produce <textbook.pdf/docx> --from-storyboard ...`，确认没问题后完整出片。
- 保存接口返回 `commands` 字段，前端直接展示。
- 路径里有空格时，命令会自动加引号。

为什么重要：

- 你改完某一页后，不用再想“下一步跑什么”。
- 系统会把“检查 JSON、重配音、局部看画面、完整出片”按顺序摆出来。
- 这让 preview 更像一个 authoring workflow，而不只是 JSON 编辑器。

怎么看成果：

```bash
t2v preview output/ch3/ch3_s0_storyboard.json --edit --open
```

保存第 3 页后，页面会提示类似：

```text
t2v validate "output/ch3/ch3_s0_storyboard.json"
t2v narrate "output/ch3/ch3_s0_storyboard.json" --only 3
t2v animate "output/ch3/ch3_s0_storyboard.json" --only 3
t2v produce <textbook.pdf/docx> --from-storyboard "output/ch3/ch3_s0_storyboard.json"
```

改坏后怎么恢复：

- 如果只是页面还没点 `Save Storyboard`，刷新 preview 即可。
- 如果已经保存，第一次保存前会留下 `xxx_storyboard.json.bak`。
- 可以用这个 `.bak` 对照或恢复到编辑前版本。
- 如果保存被拒绝，说明 `validate_storyboard` 发现致命错误，原 storyboard 不会被覆盖。

还没做到什么：

- preview 还没有表单化编辑控件，目前仍然是编辑当前页 JSON。
- 还没有安全替换完整 HTML 中的单页 slide。

### 2026-06-28：教材图 Grounded Animation MVP

提交：`339ea8c feat: add textbook image focus overlays`

做了什么：

- 新增 `focus_box` 元素，用来在教材图上框选局部区域。
- 新增 `callout` 元素，用来在教材图上叠加短标注。
- `focus_box` / `callout` 都绑定到某个 `image.id`。
- 位置用 `bbox: [x, y, w, h]` 表示，支持 0-1 或 0-100 坐标。
- 模板渲染器会把它们叠加到教材图容器上。
- overlay 带 `data-anim-id`，因此后续可以被 `trigger_at_sec` 控制出现时间。
- 校验器会检查 target、bbox、callout label，以及 target 是否指向本页图片。
- storyboard prompt 已要求有教材图时优先加入 1-3 个局部讲解标注。

为什么重要：

- 这比“把教材图放到页面上”更进一步。
- 画面可以在旁白讲到某个结构时框选图中对应区域。
- 这是比 PresentAgent 更突出的方向：教材图 grounded animation。
- 它让最终视频更像老师在指着教材图讲解，而不是静态展示图片。

怎么看成果：

storyboard 里可以写：

```json
{
  "type": "focus_box",
  "id": "f1",
  "target": "img1",
  "bbox": [0.12, 0.20, 0.35, 0.18],
  "label": "输入层"
}
```

或者：

```json
{
  "type": "callout",
  "id": "c1",
  "target": "img1",
  "bbox": [12, 55, 20, 15],
  "label": "关键步骤"
}
```

还没做到什么：

- bbox 目前需要 storyboard / LLM 给出，还不是自动从图片中识别。
- 还没有 VLM 帮忙判断框选区域是否真的对应旁白概念。
- 还没有专门的教材图讲解质量指标。

### 2026-06-28：Lesson Plan 教学活动页 MVP

提交：`2a99916 feat: add lesson plan teaching slides`

做了什么：

- 新增 `enrich_storyboard_with_lesson_plan()` 后处理。
- storyboard 生成后，如果传入 lesson plan，会自动补教学页。
- 如果 lesson plan 里有 `activities`，会补一页“想一想”。
- 如果 lesson plan 里有 `assessment_questions`，会补一页“知识点检测”。
- 如果 lesson plan 里有 `knowledge_points`，会补一页“本节小结”。
- 原有 storyboard 页面如果缺 `knowledge_point_ids`，会尽量按文本相似度补一个知识点绑定。
- 新增页面会带 `pedagogical_role`：`reflection_activity`、`knowledge_check`、`lesson_summary`。
- `metadata.total_slides` 会同步更新。

为什么重要：

- Lesson Plan 不再只是“计划文件里有活动和检测题”。
- 活动、检测题、小结会真正进入 storyboard，后续会被配音、渲染、录制进视频。
- 这让系统更像教学视频生成，而不是教材摘要视频生成。
- 这也是相对 PresentAgent 更清楚的差异：显式建模 instructional events。

怎么看成果：

生成 storyboard 后，看 `segments` 里是否出现：

```json
{"pedagogical_role": "knowledge_check", "visual_type": "activity"}
```

完整流程中，这些新增页会继续走：

```text
storyboard -> TTS -> timing -> HTML -> video
```

还没做到什么：

- 目前是确定性补页，不是根据节奏智能插入到最合适的位置；第一版默认追加在末尾。

### 2026-06-28：教学活动页质量检查

提交：`feat: check lesson plan instructional events`

做了什么：

- `*_quality.json` 现在会检查 Lesson Plan 要求的教学活动页是否真的出现在 storyboard。
- 如果 lesson plan 里有 `activities`，质量报告会要求出现 `reflection_activity`。
- 如果 lesson plan 里有 `assessment_questions`，质量报告会要求出现 `knowledge_check`。
- 如果 lesson plan 里有 `knowledge_points`，质量报告会要求出现 `lesson_summary`。
- 报告新增 `checks.lesson_plan.instructional_events`。
- 分数新增 `scores.instructional_event_coverage`。

为什么重要：

- 上一版是“把活动页放进视频链路”。
- 这一版是“自动检查它有没有真的放进去”。
- 这让 Lesson Plan -> storyboard -> quality report 形成一个小闭环。

怎么看成果：

生成 `*_quality.json` 后，看：

```json
{
  "scores": {
    "instructional_event_coverage": 1.0
  }
}
```

如果缺少教学活动页，`warnings` 里会出现 instructional event coverage 相关提示。

还没做到什么：

- 质量报告现在只检查“有没有对应页面”，还不判断题目质量和活动设计好坏。

### 2026-06-28：知识点检测题结构化

提交：待提交

做了什么：

- 新增 `quiz_card` element。
- Lesson Plan 里的 `assessment_questions` 会转成结构化题卡。
- 每道题保留 `question`、`answer`、`explanation`、`knowledge_point_ids`。
- 模板渲染器会显示题干、参考答案、解析和关联知识点。
- storyboard 校验器会检查题卡结构：缺题干是错误，缺答案/解析是 warning。
- quality report 新增 `checks.lesson_plan.instructional_events.quiz`。
- quality report 新增 `scores.quiz_structure`。

为什么重要：

- 检测题不再只是“把问题列出来”。
- 它开始有答案、解析和知识点绑定，后面可以继续做自动评分、解析页、互动暂停。
- 这让 Lesson Plan 的 `assessment_questions` 真正进入教学闭环。

怎么看成果：

storyboard 里会出现：

```json
{
  "type": "quiz_card",
  "questions": [
    {
      "question": "算法必须有明确步骤吗？",
      "answer": "是。",
      "explanation": "算法需要可执行、明确且有限的步骤。",
      "knowledge_point_ids": ["kp1"]
    }
  ]
}
```

质量报告里会出现：

```json
{
  "scores": {
    "quiz_structure": 1.0
  }
}
```

还没做到什么：

- 现在是视频内展示题目、答案和解析，还不是浏览器里可点击作答的交互。
- 还没有自动判断题目难度和题目质量。

## 下一版计划：交互式作答 / 教材图区域自动定位

下一版可以从两个方向选一个：

- 继续教学闭环：让知识点检测页支持暂停、选择、显示答案解析。
- 继续差异化：做教材图区域自动定位，让系统根据图注和旁白建议 bbox。
- 改善易用性：做 preview 表单化编辑，不必直接改 JSON。

## 历史计划：Phase 4.6 表单化编辑

下一版重点是减少直接改 JSON 的负担：

- 给 narration 单独文本框，不必直接改 JSON。
- 给 element text / animation trigger 做更轻量的编辑控件。
- 保留 raw JSON 作为高级模式。

## 历史计划：Phase 3 Timed Storyboard

当时计划的核心不是“再加一个花哨动画”，而是解决时间问题：

- 不再让 LLM 随便猜 `trigger_at_sec`；
- 先根据真实 TTS 和字幕生成每页的时间表；
- 让元素尽量在旁白讲到它的时候出现或高亮；
- 太短的页面自动压缩动画，太长的页面避免前 3 秒全出完。

预计新增：

- `src/textbook2video/pipeline/timing.py`
- `tests/test_timing.py`
- 可能输出 `*_timed_storyboard.json`，或先回写到 storyboard 的动画字段里。

验收方式：

- 给定 narration、字幕 cue、elements，能稳定算出递增的触发时间。
- 最后一个动画不会晚于音频时长。
- 短音频页面不会出现“动画还没播完，页面已经切走”的问题。
