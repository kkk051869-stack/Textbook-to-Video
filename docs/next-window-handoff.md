# 新窗口交接文档

> 这份文档给新的 Codex / AI 助手快速接手用。
> 如果用户新开窗口，不需要把整段聊天历史都贴过去，优先让它读这份文档。

## 先读哪些文件

最少读这几个：

1. `AGENTS.md`
2. `docs/next-window-handoff.md`
3. `docs/presentagent-progress.md`
4. `docs/presentagent-gap-plan.md`

如果要追溯本轮对话每一步改了什么，再读：

5. `docs/presentagent-session-changelog.md`

如果要理解动画生成历史问题，再读：

6. `docs/animation-generation.md`
7. `docs/animation-iteration.md`
8. `docs/fix-plan-json-to-html.md`
9. `docs/improvements.md`
10. `README.md`

## 当前分支和远端

- 分支：`docs/presentagent-gap-plan`
- 远端：`origin/docs/presentagent-gap-plan`
- GitHub：`https://github.com/kkk051869-stack/Textbook-to-Video`

最近关键提交：

```text
3f50350 docs: add next window handoff
a45e142 feat: check lesson plan instructional events
5917171 docs: record lesson plan teaching pages
2a99916 feat: add lesson plan teaching slides
fe77c91 docs: record textbook image grounding work
339ea8c feat: add textbook image focus overlays
```

## 项目当前定位

项目不是只做“教材摘要视频生成”，而是在往“教学视频生成系统”推进。

当前主线是：

```text
教材 -> Lesson Plan -> 讲稿 -> storyboard -> TTS/timing -> HTML -> MP4 -> quality report
```

已经做出的相对 PresentAgent 差异：

- Lesson Plan 教学语义层。
- Timed Storyboard，根据 TTS / 字幕推导动画触发时间。
- 质量报告 `*_quality.json`。
- preview 和局部重跑。
- 教材图 grounded animation：`focus_box` / `callout`。
- Lesson Plan 教学活动页：`reflection_activity` / `knowledge_check` / `lesson_summary`。
- 教学活动页质量检查：`instructional_event_coverage`。

## 最近刚完成什么

### Lesson Plan 教学活动页

代码位置：

- `src/textbook2video/pipeline/lesson_plan.py`
- `src/textbook2video/pipeline/storyboard.py`

核心函数：

```python
enrich_storyboard_with_lesson_plan(storyboard, lesson_plan)
```

作用：

- 如果 lesson plan 里有 `activities`，自动补一页 `reflection_activity`。
- 如果 lesson plan 里有 `assessment_questions`，自动补一页 `knowledge_check`。
- 如果 lesson plan 里有 `knowledge_points`，自动补一页 `lesson_summary`。
- 如果原 storyboard 页面缺 `knowledge_point_ids`，尽量按文本相似度补一个绑定。

### 教学活动页质量检查

代码位置：

- `src/textbook2video/pipeline/quality.py`
- `tests/test_quality.py`

新增质量报告字段：

```json
{
  "scores": {
    "instructional_event_coverage": 1.0
  },
  "checks": {
    "lesson_plan": {
      "instructional_events": {
        "required_roles": ["reflection_activity", "knowledge_check", "lesson_summary"],
        "present_roles": ["reflection_activity", "knowledge_check", "lesson_summary"],
        "missing_roles": [],
        "coverage": 1.0
      }
    }
  }
}
```

作用：

- 不只生成教学活动页，还检查它们是否真的进入 storyboard。
- 如果缺页，`warnings` 会出现 `instructional event coverage is incomplete`。

## 已验证什么

### 全量测试通过

正确环境是 conda 环境 `textbook2video`，不是项目根目录下那个未装依赖的 `.venv`。

命令：

```powershell
conda run -n textbook2video python -m compileall -q src tests
conda run -n textbook2video python -m pytest tests -q
```

结果：

```text
242 passed in 20.63s
```

### 相关测试通过

命令：

```powershell
python -m pytest tests\test_lesson_plan.py tests\test_storyboard.py tests\test_quality.py tests\test_checks.py tests\test_script_split.py tests\test_orchestrator.py -q
```

结果：

```text
77 passed, 1 warning
```

### 最小 smoke 通过

做了什么：

- 构造 1 页 storyboard。
- 构造包含 knowledge point、activity、assessment question 的 lesson plan。
- 调用 `enrich_storyboard_with_lesson_plan()`。
- 再调用 `build_quality_report()`。

结果：

```json
{
  "segments": 4,
  "roles": [
    "reflection_activity",
    "knowledge_check",
    "lesson_summary"
  ],
  "knowledge_point_coverage": 1.0,
  "instructional_event_coverage": 1.0,
  "warnings": [
    "audio_duration_sec coverage 1/4"
  ]
}
```

这个 warning 是预期的：smoke 没跑 TTS，所以新补的 3 页没有 `audio_duration_sec`。

## 当前环境

```powershell
conda run -n textbook2video python --version
# Python 3.11.15
```

注意：不要直接用系统 `python` 或当前 `.venv` 判断测试状态。当前机器上系统 Python / `.venv` 不是项目的完整运行环境。

## 下一步建议

优先做这几个方向：

1. 交互式答题 / 题目解析结构

让 `knowledge_check` 不只是展示问题，而是有：

- `question`
- `answer`
- `explanation`
- `knowledge_point_ids`

可考虑新增 element 类型，或先用现有 `icon_group` / `text` 兼容渲染。

2. 教学活动页质量评分

现在只检查“有没有页面”，下一步检查：

- 检测题是否覆盖关键知识点。
- 检测题是否有答案 / 解析。
- 活动页是否有明确任务。
- 小结页是否覆盖所有核心知识点。

3. 教材图区域自动定位

现在 `focus_box` / `callout` 已能渲染，但 `bbox` 还需要 storyboard / LLM 给。

下一步可以做：

- 根据图注、旁白、元素文本建议 bbox。
- 或接 VLM 检查 bbox 是否真的框到了对应概念。

4. 全量运行 smoke

下一次做大改前，优先用 `conda run -n textbook2video python -m pytest tests -q` 跑全量测试。

## 不要误改的点

- 不要绕开 `template_renderer.py` 去让 LLM 写大量 HTML。
- 不要把教材图 `src` 链路改断，图片在 storyboard 同级 `images/` 目录。
- 不要把 `record` 当成有声输出，它只录画面；有声成片走 `produce` 或 `mux`。
- 不要硬编码密钥，不要提交 `.env`。
- 不要回滚用户本地改动。

## 给新窗口的一句话任务

请先读 `AGENTS.md` 和 `docs/next-window-handoff.md`，然后继续做“交互式答题 / 题目解析结构”或“教材图区域自动定位”。动手前先跑相关测试，改完后更新 `docs/presentagent-progress.md`、`docs/presentagent-gap-plan.md` 和 `docs/presentagent-session-changelog.md`。
