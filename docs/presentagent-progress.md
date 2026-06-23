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
| Phase 4：预览和局部重跑 | 未开始 | 让人能改一页、只重跑一页 |
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

## Timed Storyboard 是什么

### 先说结论

Timed Storyboard 就是“给每一页里的元素安排准确出现时间”。

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

## 下一版计划：Phase 4 Preview + 局部重跑

下一版重点是让你能更直观看到和修改结果：

- 新增 `t2v preview` MVP；
- 左侧看页面列表和 narration/elements；
- 右侧预览单页或整段动画；
- 修改 storyboard 后保存；
- 优先支持保存后从已有 storyboard 继续出片。

验收方式：

- 可以打开本地预览页面看 storyboard。
- 改一页 JSON 后，不需要从教材解析重新开始。
- 能配合 `--from-storyboard` 完成更短反馈周期。

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
