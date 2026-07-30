# 改进建议（Roadmap）

> 当前项目状态：端到端 pipeline 跑通，模板渲染 + 混合 LLM 模式（`render_mode`）+ icon_group 多版式 + 元素间距分级已上线（PR #1）。
> 本文档按"价值 / 改动成本"分级，列出后续可做的改进点。每条都标了"为什么需要 / 怎么做 / 预估成本"，便于按需取用。
>
> 创建日期：2026-06-07

---

## ✅ 已落地，后续继续打磨

### 1. 自动字幕轨道（SRT mux 进 MP4）

**状态**：已实现。`produce` 默认从 storyboard 生成 `.srt` 并作为软字幕轨 mux 进 MP4；也提供 `t2v subtitle` 和 `t2v mux --subtitle`。

**后续打磨**：
- 字幕质量纳入 `*_quality.json`：cue 数、覆盖时长、长字幕告警。
- 后续可做双语字幕、硬字幕烧录样式、TTS word boundary 对齐。

**额外收益**：字幕可作为 SEO / 搜索语料；可作为 CI 检测点（OCR slide vs SRT 对照）。

---

## 🔥 高价值且改动不大

### 2. 中间产物缓存复用（`--from-storyboard` / `--from-script`）

**问题**：改 theme、改主题动画、调字号都得重跑 LLM 生成 script/storyboard，反馈慢、烧 token。

**状态**：第一版已实现，`produce` 支持 `--from-script`、`--from-storyboard`、`--from-html`（复用 HTML 时需同时给 `--from-storyboard` 以确定配音和时长）。

**额外收益**：开发反馈循环秒级；调主题/字号迭代效率 10×。

**后续打磨**：支持单页 `--only N` 重配音/重渲染。

---

### 3. 教材原图利用率检查

**问题**：parser 提取的教材原图，storyboard prompt 不一定优先使用。实测 8 页里仅 1 张教材图被引用，但教材里图通常有 5+ 张——视觉丰富度被白白浪费。

**方案**：
- `storyboard.py` 把"可用教材图列表"显式塞进 prompt
- prompt 加约束："有可用教材原图时，**至少 60% 相关页应引用**，而非要求 AI 重画"
- `validate` 加软警告：图片利用率 < N% 提示用户

**额外收益**：原图都是真实场景，比 AI 生成的抽象图教学价值高，且不耗 token / 图像费用。

**成本**：~2 小时。

---

### 4. 音画时长校验

**问题**：页内 `.anim` 元素有 `d1`-`d12` 延迟（最多约 1s 全部入场），如果 `narration` 只有 2s，用户可能没看完动画就翻页。

**方案**：
- `validate_storyboard` 加规则：`audio_duration_sec >= max_delay_in_page + 0.5s buffer`
- 不达标的页输出警告（不强制失败），让人工或上游 LLM 决定改 narration 还是减元素

**成本**：~1 小时。

---

## 🛠 中等价值

### 5. 教材解析通用化

**问题**：`parser.py` 现在依赖《数字素养》样式 ID 2/4/5、PDF 走《人工智能》页码硬编码（`LESSON_PAGE_RANGES`）。换一本教材就得改死代码，没法对外推广。

**方案**：
- DOCX：基于 Heading 1/2/3 层级 + 标题正则（"第N章/N.M 节"）通用解析
- PDF：用 PyMuPDF 的 outline / bookmark 自动识别章节，落空时回退到现有页码表
- 老映射作为"教材适配 profile" `t2v --profile digital-literacy`

**额外收益**：换教材即用，能扩到 K12/职业培训等场景。

**成本**：~1 天。需要 1-2 本结构差异大的教材做测试集。

---

### 6. 多音色支持

**问题**：edge-tts 现在全片单一音色，标题页、正文、引用、结束页全是一个调调，单调。

**方案**：
- storyboard 段级加可选 `voice` 字段（默认继承课级默认值）
- 提供几个预设组合（`narrator` / `accent` / `quote` / `emphasis`），映射到 edge-tts 不同 voice id
- `title`/`closing` 走更有情感的音色（如 `zh-CN-YunxiNeural`），`text` 走稳重音色

**成本**：~3 小时。edge-tts 支持多音色，主要工作是 voice 字段的 schema + prompt 引导。

---

### 7. 失败页可观测产物

**问题**：layout 修复 LLM 失败时静默跳过保留当前页。无法回查"哪页为什么失败"。

**方案**：
- `animate` 结束时输出 `*_failed_pages.json`，每条记录：
  - `slide_index` / `seg_id` / `failure_reason` / `qa_report_snippet` / `last_attempted_html_path`
- 没有失败页时不写文件

**额外收益**：CI 友好；定位生成质量问题不用刨日志。

**成本**：~2 小时。

---

## 🎨 锦上添花

### 8. theme 携带动画风格

**问题**：3 个主题（bright/dark-blue-academic/3b1b-math）只换配色字体，动画曲线完全一样。`3b1b-math` 该有 manim 风格的 spring physics，`bright` 该活泼，`dark-blue-academic` 该稳重——目前都长一样。

**方案**：
- `themes/*.json` 加 `animation` 字段：`{easing, duration_scale, particle_density, transition_style}`
- `base.css` 的 `.anim-*` keyframes 改用 CSS 变量

**成本**：~半天。

---

### 9. 项目级 `.t2v.toml` 配置

**问题**：`--theme --model --output --chapter --section` 每次都打太烦。

**方案**：
- 项目根读 `.t2v.toml`：`[defaults] theme=..., model=..., output_dir=...`
- CLI 参数覆盖配置文件
- `t2v init` 命令快速生成模板配置

**成本**：~2 小时。

---

### 10. 视频质量自动评估

**问题**：跑完后没有自动的"这视频质量行不行"信号，全靠人看 8 页 200 秒视频。

**方案**：
- 跑完后自动：
  - OCR 每页文字 vs storyboard 文本，检测被裁切/缺失的字
  - ffmpeg `volumedetect` 检测音轨异常（mean_volume < -30dB 警告）
  - 帧差异检测视觉熵（避免一片黑/纯白页）
- 输出 `quality_report.json`，CI 可基于此 fail

**成本**：~半天。

---

## 接下来做哪个？

如果只挑一个，推荐 **#1 字幕轨道**：最低改动、最显见的"产品完成度"提升，且为 #10 的 OCR-vs-SRT 校验铺路。

如果想治"视觉单调"的根本问题，推荐 **#3 教材原图利用率**：免费提升视觉丰富度，且不依赖 LLM 创意，确定性强。

如果想为对外推广做准备，推荐 **#5 教材解析通用化**：当前只能跑特定两本书，限制了使用场景。
