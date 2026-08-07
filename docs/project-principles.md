# Textbook-to-Video 项目原理

## 1. 项目要解决的问题

Textbook-to-Video 将 PDF 或 DOCX 教材转成带动画、旁白和字幕的教学视频。它不是把教材页截图后直接配音，而是先抽取知识内容，再分别生成讲稿与页面结构，最后以真实旁白的时长驱动页面切换。

核心原则是：**音频先行，页面时长由音频决定，成片前必须校验音频、定时大纲和 HTML 属于同一次任务。**

```text
教材
  -> 解析后的课程文本和教材图片
  -> lesson plan（教学设计）
  -> script（逐段旁白）
  -> storyboard（逐页教学内容与视觉元素）
  -> WAV/MP3（真实旁白）
  -> timed storyboard（写入每页真实时长）
  -> HTML（页面、动画、切页时序）
  -> silent MP4（浏览器录制的无声画面）
  -> final MP4（合成旁白和字幕后的成片）
```

任何箭头右侧的产物都依赖左侧产物。尤其不能用新的音频配旧 HTML，也不能用某一章的音频去合成另一章的无声视频。

## 2. 系统分层

### 输入与解析层

- `pipeline/parser.py`：PDF 课程解析、课程页范围和教材图片提取。
- `pipeline/docx_parser.py`：DOCX 按 Heading 样式解析。
- `pipeline/checks.py`：输入结构、环境和 storyboard 的基础校验。

解析层产出的是课程正文、章节标题、图片及其引用关系。不同教材的标题样式和 PDF 页码组织常不同，因此接入新教材时，首先应验证这里能否正确划分课节，而不是直接调整提示词。

### 教学内容层

- `pipeline/lesson_plan.py`：生成教学目标、知识点、活动、测验和小结等教学设计。
- `pipeline/scriptwriter.py`：根据教材正文与 lesson plan 生成逐段旁白。
- `pipeline/storyboard.py`：把每段旁白转成逐页页面大纲。
- `llm/client.py`：统一调用 OpenAI 兼容的模型服务。
- `llm/prompts/`：教学设计、讲稿、storyboard 和修复提示词。

lesson plan 不是仅供展示的文件。它决定讲稿如何组织知识点、何时插入“想一想”、检测和小结，因此它应在 script 和 storyboard 之前生成并传入后续阶段。

### 视觉呈现层

- `template_renderer.py`：优先将结构化 elements 确定性渲染为 HTML。
- `variants/`：标题、文本、图片、流程、对比、表格、活动步骤等元素的布局变体。
- `themes/`：主题色、字体、背景粒子和样式变量；当前教学视频采用 `dark-blue-academic`。
- `templates/base.css`、`base-template.html`：单页框架、动画及全局样式。
- `animation_gen.py`：组织渲染、提取、合并、布局 QA、修复和最终 HTML 输出。

视觉层采用“**确定性模板优先，LLM 兜底**”的策略。常见元素由 Python 模板按固定规则渲染，减少模型直接写 CSS 带来的重叠、乱码和不可复现布局；只有模板不支持的特殊图形或不兼容元素才回退到 LLM 生成 HTML。布局问题应优先修改变体、模板或 CSS，而不是不断增加 storyboard 提示词。

### 媒体层

- `pipeline/narrator.py`：生成旁白、读出音频时长，并对 CPU、GPU、NPU、AI 等缩写做配音文本规范化。
- `pipeline/timing.py`：将实测音频时长写入 storyboard，生成 timed storyboard。
- `pipeline/recorder.py`：用 Playwright/Chromium 播放 HTML 并录制无声视频。
- `pipeline/subtitles.py`：从旁白生成字幕。
- `pipeline/compose.py`：拼接分段音频、合并字幕和无声视频。
- `pipeline/artifact_integrity.py`：校验并写入 render manifest。

## 3. 最关键的时间同步机制

过去出现“声音和 PPT 翻页对不上”的根因通常是：HTML 在真实配音之前已经生成，每页采用默认展示时长；或录制时每页切换误差累积。

现在的正确链路如下：

1. storyboard 中每个 `segment` 有一段 `narration`。
2. TTS 为每个 segment 生成一个独立音频文件，例如 `s1.wav`、`s2.wav`。
3. 系统用 ffprobe/ffmpeg 读取每个文件的真实时长，并写入 `audio_duration_sec`。
4. `timing.py` 依据这些时长生成 timed storyboard。
5. HTML 将 timed storyboard 的逐页毫秒数嵌入 `slideDurations`。
6. Chromium 录制 HTML，页面控制器严格按 `slideDurations` 翻页。
7. 合成阶段按相同编号拼接音频并 mux 到录制视频。

因此，页面时长的唯一可信来源是已生成音频，而不是文字长度、估算语速或固定的 5 秒默认值。

`artifact_integrity.verify_render_bundle` 是录制前的关闭式校验：只要 timed storyboard、HTML 中的 `slideDurations`、音频段数或总时长存在不一致，就拒绝录制。通过后会由 `write_render_manifest` 写入 manifest，其中记录文件名、SHA-256、页数、每页时长和总时长。它是产物可追溯性的锚点。

## 4. 一次课节的产物关系

以第二章为例，一个任务目录应包含类似内容：

```text
chapter2-YYYYMMDD-HHMM/
  chapter2_raw.txt
  chapter2_lesson_plan.json
  chapter2_script.txt
  chapter2_storyboard.json
  chapter2_timed_storyboard.json
  chapter2_audio/
    s1.wav ... sN.wav
  chapter2-dark-blue-academic.html
  chapter2-dark-blue-academic.manifest.json
  chapter2-silent.mp4
  chapter2.srt
  chapter2-final.mp4
```

- `storyboard.json`：内容和页面元素的设计稿，可在配音前审阅。
- `timed_storyboard.json`：同一设计稿加上真实音频时长；它才可用于渲染和录制。
- `html`：由 timed storyboard 导出的播放文件，不能手改时长数组。
- `manifest`：声明本 HTML 与 timed storyboard、音频是否一致。
- `silent.mp4`：纯画面中间件，不是可交付成片。
- `final.mp4`：唯一的最终视频。

每章必须使用独立任务目录。这样即使一章失败，也不会污染其他章节；重做某章时也不会误取上一轮生成的 HTML 或 WAV。

## 5. 录制原理

录制不是截取静态图片。`recorder.py` 启动 Chromium，打开单文件 HTML，由 `slide-controller.js` 控制当前页、入场动画和切页时机。浏览器页面被 Playwright 捕获，再借助 ffmpeg 编码为视频。

录制阶段只产出无声画面，原因是浏览器切页时序与音频合成由不同工具负责。随后 `compose.py` 将按编号排序的分段音频拼接为一条音轨，并 mux 到 silent MP4。这一职责分离便于单独检查画面、音频和合成时长。

云端录制还依赖一套完整的 Chromium 运行时：Playwright Python 包、Chromium、系统共享库和 ffmpeg。运行时必须放在 `/ai/data`，并先通过 5 秒 smoke MP4 后才能进入正式任务。

## 6. 云端模型与资源编排

云端 LLM 使用本地 OpenAI 兼容接口的 Qwen3-32B AWQ vLLM；配音使用 MegaTTS3。两者都可能占用 GPU，**不能同时启动**。

批量生成采用阶段式串行队列：

```text
A. 仅 vLLM：所有章节完成 lesson plan、script、storyboard
B. 停止 vLLM，确认显存释放
C. 仅 MegaTTS3：所有章节完成 TTS、timed storyboard、HTML、manifest
D. 停止 MegaTTS3，确认显存释放
E. 两者均不启动：逐章串行录制、字幕、mux、终检
```

这比“每一章端到端并行”更可靠：显存不会竞争，多个 Chromium 不会并发抢占 CPU/内存，且每个阶段都能针对同类错误集中复核。每次切换服务前必须用 `nvidia-smi` 和精确进程列表确认前一服务已退出。

详细运行命令、目录限制、浏览器烟雾测试和批量门禁见 [云端全流程出片手册](cloud-only-video-production-runbook.md)。

## 7. 质量保障的层次

项目的质量控制分为四层：

1. **内容校验**：解析结果、lesson plan、旁白和 storyboard 是否覆盖课程知识点，教学页顺序是否为正文、活动、检测、小结、结束。
2. **结构校验**：`validate_storyboard` 检查元素类型、字段、图片引用等；模板渲染优先确保常见页面结构稳定。
3. **视觉校验**：`animation_gen.py` 调用布局 QA，检查 HTML 在浏览器中的重叠、越界和缺失；截图前需等待动画 delay，否则可能误判元素未出现。
4. **时间校验**：manifest 校验逐页时长、音频段数和音频总长；最终以 `ffprobe` 校验 final MP4 与 manifest 总时长相符。

这四层不能互相替代。一份页面漂亮的 HTML 仍可能来自旧时长；一条音频正确的 WAV 也可能因错误 mux 到另一章视频而失效。

## 8. 维护时如何定位问题

| 现象 | 优先检查 | 通常的修复位置 |
| --- | --- | --- |
| 章节内容不完整或标题错位 | 输入解析和 lesson plan | `parser.py`、`docx_parser.py`、`lesson_plan.py` |
| 讲稿不符合教学顺序 | lesson plan 是否传入 scriptwriter | `lesson_plan.py`、`scriptwriter.py`、提示词 |
| 页面元素过多、版式不统一 | visual type 与 variants | `template_renderer.py`、`variants/`、`base.css` |
| 页面重叠或溢出 | 浏览器布局 QA 与元素尺寸 | `animation_gen.py`、`css_hotfix.py`、变体 CSS |
| CPU/GPU 等读错 | TTS 输入是否被规范化 | `narrator.py` |
| 声音和翻页不一致 | timed storyboard、HTML、manifest | `timing.py`、`artifact_integrity.py`、不要复用旧 HTML |
| 录制失败 | Chromium/Playwright/ffmpeg smoke | `recorder.py` 和云端浏览器运行时 |
| 最终视频无声或时长错误 | 音频编号、mux 输入和 ffprobe | `compose.py`、任务目录一致性 |

## 9. 不应破坏的约定

- 不把模型、浏览器、缓存、音频或视频写到 `/root`；云端长期数据只放 `/ai/data`。
- 不把 `.env`、密钥、模型和生成产物提交到 Git。
- 不手动编辑 HTML 的 `slideDurations`；应从音频重新生成 timed storyboard 和 HTML。
- 不跨章节混用 `audio/`、HTML、manifest 或 silent MP4。
- 不在 vLLM 与 MegaTTS3 同时运行时启动批量任务。
- 不因一次视觉问题盲目扩大 prompt；先判断应由数据、模板、变体还是 CSS 修复。

遵守这些边界后，这个项目的每一步都可独立审阅、重做和验证，最终视频也能追溯到具体教材、模型输出、音频与渲染版本。
