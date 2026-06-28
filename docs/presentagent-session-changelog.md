# PresentAgent Gap Work：本轮对话修改记录

> 这份文档按时间顺序记录本轮对话中做过的改动。
> 重点回答四件事：改了什么、改在哪些文件/文档、目的是什么、成功没有。
>
> 更通俗的阶段进展仍看 `docs/presentagent-progress.md`。
> 专业方案和后续规划仍看 `docs/presentagent-gap-plan.md`。

## 当前分支和状态

- 分支：`docs/presentagent-gap-plan`
- 远端：`origin/docs/presentagent-gap-plan`
- 已推送到 GitHub 的最后提交：`fe77c91 docs: record textbook image grounding work`
- 当前“教学活动页质量检查”代码已提交为 `feat: check lesson plan instructional events`，本次正在补充文档记录并准备推送。

## 2026-06-23：建立 PresentAgent 差距规划

提交：

- `b57841e docs: add PresentAgent gap plan`
- `8d143f5 docs: add agent project context`

改了什么：

- 新增 `docs/presentagent-gap-plan.md`。
- 新增项目上下文说明，方便后续继续开发时不丢失背景。

改在哪：

- `docs/presentagent-gap-plan.md`
- `AGENTS.md` 或项目上下文相关文件

目的：

- 明确这个项目相对 PresentAgent 的差异化方向。
- 把后续工作拆成可执行阶段：可复用、质量报告、Lesson Plan、Timed Storyboard、Preview、局部重跑、评估体系。

成功没：

- 成功。
- 已提交并推送。

## 2026-06-23：Phase 1，产物复用和质量报告

提交：

- `2647155 feat: add produce reuse and quality report`

改了什么：

- `produce` 支持从已有中间产物继续：
  - `--from-script`
  - `--from-storyboard`
  - `--from-html`
- 默认输出 `*_quality.json`。
- 质量报告检查 storyboard、音频、字幕、布局报告、教材图片使用率、动画触发时间风险。
- README 和 `docs/improvements.md` 更新字幕、复用、质量报告状态。

改在哪：

- `src/textbook2video/pipeline/orchestrator.py`
- `src/textbook2video/pipeline/quality.py`
- `src/textbook2video/cli.py`
- `README.md`
- `docs/improvements.md`
- 相关测试文件

目的：

- 解决“小改动必须重跑整条 LLM 链路”的问题。
- 让每次生成后都有自动体检单，而不是只看有没有 MP4。

成功没：

- 成功。
- 已提交并推送。
- 后续文档中解释了 `*_quality.json` 的含义。

## 2026-06-23：Phase 2，Lesson Plan 教学语义层 MVP

提交：

- `8cedfd4 feat: add lesson plan semantic layer`

改了什么：

- 新增 `lesson_plan` 层。
- 生成讲稿/storyboard 前先生成教学计划。
- 教学计划包含学习目标、知识点、活动、检测题、图片使用建议。
- scriptwriter 和 storyboard prompt 开始读取 lesson plan。
- quality report 增加知识点覆盖检查。

改在哪：

- `src/textbook2video/pipeline/lesson_plan.py`
- `src/textbook2video/llm/prompts/lesson_plan.md`
- `src/textbook2video/pipeline/scriptwriter.py`
- `src/textbook2video/pipeline/storyboard.py`
- `src/textbook2video/pipeline/orchestrator.py`
- `src/textbook2video/pipeline/quality.py`
- `tests/test_lesson_plan.py`
- `tests/test_quality.py`

目的：

- 从“文档转视频”推进到“教学目标驱动的视频生成”。
- 为后续和 PresentAgent 对比提供教学维度，而不是只比视觉生成。

成功没：

- 成功。
- 已提交并推送。
- 目前仍是 MVP：lesson plan 对后续生成的约束还偏软。

## 2026-06-23：新增通俗进展文档

提交：

- `9617b80 docs: add readable PresentAgent progress log`

改了什么：

- 新增 `docs/presentagent-progress.md`。
- 用更通俗的语言记录每一版做了什么、为什么重要、怎么看成果。

改在哪：

- `docs/presentagent-progress.md`

目的：

- 解决原专业文档太难读的问题。
- 以后每版改动都在这份文档里记录清楚。

成功没：

- 成功。
- 已提交并推送。

## 2026-06-23：Phase 3，Timed Storyboard 时间层 MVP

提交：

- `82b3bb6 feat: add timed storyboard generation`
- `17034f6 docs: record timed storyboard progress`
- `b1268bc docs: clarify quality report and timed storyboard`

改了什么：

- 新增 `pipeline/timing.py`。
- TTS 写入真实 `audio_duration_sec` 后，自动生成 `animations[].trigger_at_sec`。
- 输出 `*_timed_storyboard.json`。
- 原 `*_storyboard.json` 也会写入 timing，现有动画播放器可直接使用。
- 文档里补充了质量报告和 Timed Storyboard 的通俗解释。

改在哪：

- `src/textbook2video/pipeline/timing.py`
- `src/textbook2video/pipeline/orchestrator.py`
- `src/textbook2video/cli.py`
- `tests/test_timing.py`
- `tests/test_narrate.py`
- `docs/presentagent-progress.md`
- `docs/presentagent-gap-plan.md`

目的：

- 不再让 LLM 在不知道真实音频时长时乱猜动画秒数。
- 让元素尽量在旁白讲到相关内容时出现。

成功没：

- 成功。
- 已提交并推送。
- 当前算法是文本匹配 + 顺序兜底，不是 embedding 或 VLM 对齐。

## 2026-06-23：Phase 4.1，Storyboard Preview 只读预览

提交：

- `e8d7adb feat: add storyboard preview html`
- `8f39016 docs: record storyboard preview progress`

改了什么：

- 新增 `t2v preview storyboard.json`。
- 生成本地 HTML 预览页。
- 左侧看页面列表，右侧看 narration、elements、animations、原始 JSON。
- 默认生成 `*_preview.html`。

改在哪：

- `src/textbook2video/pipeline/preview.py`
- `src/textbook2video/cli.py`
- `tests/test_preview.py`
- `README.md`
- `docs/presentagent-progress.md`
- `docs/presentagent-gap-plan.md`

目的：

- 解决人工直接读 storyboard JSON 太痛苦的问题。
- 为后续可编辑工作流打基础。

成功没：

- 成功。
- 已提交并推送。
- 验证过相关测试通过。

## 2026-06-23：Phase 4.2，可编辑预览和安全保存

提交：

- `0600673 feat: add editable storyboard preview`
- `9d8814a docs: record editable preview workflow`

改了什么：

- `t2v preview` 新增 `--edit`。
- `--edit` 启动本地 preview server。
- 页面里可以编辑当前页 segment JSON。
- 点击保存后，服务端先运行 `validate_storyboard`。
- 保存前自动生成 `*.json.bak`。

改在哪：

- `src/textbook2video/pipeline/preview.py`
- `src/textbook2video/cli.py`
- `tests/test_preview.py`
- `README.md`
- `docs/presentagent-progress.md`
- `docs/presentagent-gap-plan.md`

目的：

- 让用户能直接修改 storyboard 的某一页。
- 避免手滑把 JSON 写坏。
- 给本地恢复留备份。

成功没：

- 成功。
- 已提交并推送。
- 仍然是 JSON 编辑，不是表单化编辑。

## 2026-06-23：Phase 4.3，`narrate --only` 音频局部重跑

提交：

- `9545d7c feat: support partial narrate reruns`
- `330d1e5 docs: record partial narrate reruns`

改了什么：

- `t2v narrate` 新增 `--only`。
- 支持单页：`--only 3`。
- 支持范围：`--only 2,4-6`。
- 只替换指定页对应的 `sN.mp3`。
- 未选中页面沿用原有 `audio_duration_sec`。
- 重配后刷新 storyboard 和 `*_timed_storyboard.json`。

改在哪：

- `src/textbook2video/pipeline/orchestrator.py`
- `src/textbook2video/cli.py`
- `tests/test_narrate.py`
- `README.md`
- `docs/presentagent-progress.md`
- `docs/presentagent-gap-plan.md`

目的：

- 改一页 narration 后，不必重配整节课音频。
- 缩短人工修改反馈周期。

成功没：

- 成功。
- 已提交并推送。
- 验证过相关测试通过。

## 2026-06-23：Phase 4.4，`animate --only` 局部 HTML 检查

提交：

- `4419951 feat: add partial animate html generation`
- `b419a09 docs: record partial animate workflow`

改了什么：

- `t2v animate` 新增 `--only`。
- 支持单页或范围。
- 只把选中 segment 送进动画生成流程。
- 输出文件名带页码后缀，例如 `ch3_s0-p3-pipeline-dark-blue-academic.html`。

改在哪：

- `src/textbook2video/animation_gen.py`
- `src/textbook2video/cli.py`
- `tests/test_animation_selection.py`
- `README.md`
- `docs/presentagent-progress.md`
- `docs/presentagent-gap-plan.md`

目的：

- 在 preview 里改了某页 elements/animations 后，只生成这一页 HTML 看效果。
- 不直接替换完整 HTML，避免 durations/timelines/custom CSS 等全局结构错位。

成功没：

- 成功。
- 已提交并推送。
- 边界已写清楚：这不是“原地替换完整 HTML 中某一页”，只是局部 HTML 检查。

## 2026-06-23：Phase 4.5，Preview 保存后的操作提示

提交：

- `d57f858 feat: show preview save workflow commands`
- `4d826ec docs: record preview workflow prompts`

改了什么：

- `preview --edit` 保存成功后，页面显示下一步建议命令。
- 自动根据当前页带上 `--only N`。
- 显示：
  - `t2v validate ...`
  - `t2v narrate ... --only N`
  - `t2v animate ... --only N`
  - `t2v produce <textbook.pdf/docx> --from-storyboard ...`
- 路径有空格时自动加引号。

改在哪：

- `src/textbook2video/pipeline/preview.py`
- `tests/test_preview.py`
- `README.md`
- `docs/presentagent-progress.md`
- `docs/presentagent-gap-plan.md`

目的：

- 把“改页 -> 校验 -> 重配音 -> 局部看画面 -> 完整出片”串成工作流。
- 用户保存后不用再翻文档找下一步命令。

成功没：

- 成功。
- 已提交并推送。
- 验证过相关测试通过。

## 2026-06-28：重新判断差异化方向

提交：

- 暂无，仅对话分析。

分析结论：

- 目前项目比 PresentAgent 强在工程可控、教学语义、质量报告、可编辑和局部重跑。
- 但如果只看最终视频，差异还不够突出。
- 真正值得拉开差距的方向是“教材图 grounded animation + 旁白同步高亮”。

计划：

- 优先做教材图讲解元素：
  - `focus_box`：框选教材图局部。
  - `callout`：给教材图局部加标注。
- 让这些元素进入校验、模板渲染、prompt 和 timing。
- 后续再做更强的图像区域自动识别和 VLM 辅助定位。

成功没：

- 分析和计划已完成。
- 代码实现正在进行，见下一节。

## 2026-06-28：教材图局部讲解 MVP

提交：

- `339ea8c feat: add textbook image focus overlays`

改了什么：

- `template_renderer.py` 支持 `focus_box` 和 `callout`。
- `focus_box` / `callout` 会绑定到某个 `image.id`。
- 使用 `bbox: [x, y, w, h]` 在教材图上叠加框选或标注。
- 图片容器改成可叠加 overlay 的结构。
- overlay 带 `data-anim-id`，后续可被 timing / slideTimelines 控制出现时间。
- `checks.py` 认识新元素，并校验：
  - 必须有 `target`；
  - 必须有合法 `bbox`；
  - `target` 必须指向本页存在的 image id；
  - `callout` 必须有 `label` 或 `text`。
- `storyboard.md` prompt 增加 `focus_box` / `callout` 要求。
- 测试补了模板渲染和校验器用例。

改在哪：

- `src/textbook2video/template_renderer.py`
- `src/textbook2video/pipeline/checks.py`
- `src/textbook2video/llm/prompts/storyboard.md`
- `tests/test_template_renderer.py`
- `tests/test_checks.py`

目的：

- 让最终视频不只是“教材图放上去”，而是能讲到哪里框到哪里。
- 形成比 PresentAgent 更突出的功能差异：教材图 grounded animation。
- 为论文里的方法亮点提供更硬的功能抓手。

成功没：

- 成功。
- 已运行相关测试：

```text
86 passed, 1 warning
```

- 已提交。
- 文档补充正在进行。
- 还没做自动识别教材图区域，当前 bbox 仍需要 storyboard/LLM 给出。

## 2026-06-28：Lesson Plan 教学活动页 MVP

提交：

- `2a99916 feat: add lesson plan teaching slides`

改了什么：

- 新增 `enrich_storyboard_with_lesson_plan()`。
- storyboard 生成后会根据 lesson plan 自动补教学页。
- `activities` 会进入“想一想”页。
- `assessment_questions` 会进入“知识点检测”页。
- `knowledge_points` 会进入“本节小结”页。
- 原有页面缺 `knowledge_point_ids` 时，会用文本相似度尽量补一个绑定。
- 新增测试覆盖增强函数和 `generate_storyboard(..., lesson_plan=...)` 集成。

改在哪：

- `src/textbook2video/pipeline/lesson_plan.py`
- `src/textbook2video/pipeline/storyboard.py`
- `tests/test_lesson_plan.py`
- `tests/test_storyboard.py`

目的：

- 让 Lesson Plan 不只是计划，而是真的影响最终视频内容。
- 把活动、检测题、小结变成 storyboard 页面，进入 TTS、HTML 和视频链路。
- 让项目更像“教学视频生成”，而不是“教材摘要视频生成”。

成功没：

- 成功。
- 已运行相关测试：

```text
76 passed, 1 warning
```

- 已提交。
- 已推送。

## 2026-06-28：教学活动页质量检查

提交：

- `feat: check lesson plan instructional events`

改了什么：

- `quality.py` 新增 instructional events 检查。
- 如果 lesson plan 里有 `activities`，质量报告要求 storyboard 里出现 `reflection_activity`。
- 如果 lesson plan 里有 `assessment_questions`，质量报告要求 storyboard 里出现 `knowledge_check`。
- 如果 lesson plan 里有 `knowledge_points`，质量报告要求 storyboard 里出现 `lesson_summary`。
- `*_quality.json` 新增 `checks.lesson_plan.instructional_events`。
- `scores` 新增 `instructional_event_coverage`。
- 测试新增缺失教学活动页时的 warning 覆盖。

改在哪：

- `src/textbook2video/pipeline/quality.py`
- `tests/test_quality.py`
- `docs/presentagent-progress.md`
- `docs/presentagent-gap-plan.md`
- `docs/presentagent-session-changelog.md`

目的：

- 让 Lesson Plan -> storyboard -> quality report 形成闭环。
- 不只生成教学活动页，还能自动检查活动页有没有真的进入最终 storyboard。
- 继续强化相对 PresentAgent 的差异：显式检查 instructional events。

成功没：

- 成功。
- 已运行相关测试：

```text
29 passed, 1 warning
```

- 已提交。

## 2026-06-28：新窗口交接文档与验证记录

提交：

- 待提交

改了什么：

- 新增 `docs/next-window-handoff.md`。
- 写清楚新窗口最少需要读哪些文档。
- 汇总当前分支、最近关键提交、已经完成的差异化能力。
- 记录本次 smoke 验证结果。
- 记录全量测试暂时被环境依赖挡住的原因。
- 写出下一步建议：交互式答题、教学活动页质量评分、教材图区域自动定位、全量环境修复。

改在哪：

- `docs/next-window-handoff.md`
- `docs/presentagent-session-changelog.md`

目的：

- 让用户新开窗口时，不需要重新解释整段对话。
- 降低后续接手成本。
- 避免后续助手不知道哪些测试已经跑过、哪些没跑通是环境原因。

成功没：

- 成功。
- 已完成 smoke 验证。
- 已完成相关测试：

```text
77 passed, 1 warning
```

- 全量测试未完成，原因是当前环境缺少依赖并且没有可用 Python 3.11+ 测试环境。
- 待提交。

## 当前未完成事项

1. 推送“新窗口交接文档与验证记录”。
2. 继续做更突出差异：
   - 教材图局部区域自动定位；
   - 旁白 cue 与 focus_box/callout 更精确对齐；
   - 教学活动页质量评分 / 交互式答题逻辑；
   - TextbookEval 评估命令。

## 一句话总结

本轮对话已经把项目从“教材转视频 pipeline”推进到“可检查、可编辑、可局部重跑的教学视频生成系统”。但要真正比 PresentAgent 更突出，下一步重点不该继续堆工具，而应该围绕“教材图 grounded animation”和“教学评估”继续做出可见差异。
