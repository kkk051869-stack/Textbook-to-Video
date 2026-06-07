# Pipeline 实现文档

> 记录当前 Pipeline 各模块功能、接口和 JSON 数据结构。
> 创建日期：2026-05-19
> 最近更新：2026-06-04（全链路打通：13 个 t2v 命令、端到端 produce、F5 确定性渲染、音画合成）

---

## 一、代码文件说明

### CLI 入口

| 文件 | 功能 |
|------|------|
| `cli.py` | CLI 入口，提供 `t2v` 13 条子命令 |

**命令列表：**
```
# 端到端 / 批处理
t2v produce <教材> -c <章> -s <节>（或 --lesson N）         — ★教材 → 有声 MP4（一步到位）
t2v batch <教材> --sections "3:0,3:1"                       — 多课节批处理
t2v doctor                                                  — 运行前环境自检

# 内容生成（教材 → storyboard）
t2v generate <input.pdf> --lesson <N>                       — PDF → 讲稿+storyboard(+配音)
t2v generate-docx <input.docx> -c <章号> -s <节号>          — DOCX（含图片提取，0-based 整数）
t2v list-lessons <input.pdf|docx>                           — 列出可提取的课程/章节
t2v script <教材> ...                                       — 只生成讲稿 *_script.txt
t2v storyboard <*_script.txt>                               — 从讲稿重做画面大纲
t2v narrate <*_storyboard.json>                             — 重生成 TTS 配音并回写时长
t2v validate <*_storyboard.json>                            — 静态校验 storyboard

# 出片
t2v animate <*_storyboard.json>                             — storyboard → 单文件动画 HTML
t2v record <input.html> <output.mp4>                        — HTML → MP4（只录画面，无声）
t2v mux <video> <audio_dir>                                 — 把分段配音合成进视频
```

### Pipeline 模块（`pipeline/`）

| 文件 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `parser.py` | PDF/DOCX 按课/节提取教材文本 + 图片 | PDF(课号) 或 DOCX(章/节号) | 文本 + 教材图 |
| `docx_parser.py` | DOCX 另一套解析（按 Heading 样式），`generate` 用 | DOCX | 文本 |
| `scriptwriter.py` | 调用 LLM 生成讲稿 | 教材文本 | 讲稿分段列表 |
| `storyboard.py` | 调用 LLM 生成画面大纲 | 讲稿分段 | 画面大纲 JSON |
| `narrator.py` | TTS 配音（容错：单段失败不中止整批） | 讲稿文本列表 | MP3 文件 + 音频时长 |
| `recorder.py` | HTML 动画 → MP4 录制（**只录画面、无声**） | HTML 文件路径 | 无声 MP4 |
| `compose.py` | 分段配音拼接 + mux 到视频 → 有声成片 | 视频 + 音频目录 | 有声 MP4 |
| `orchestrator.py` | 生成编排（build_script/storyboard_*）+ 端到端 `produce` | 教材 | 全链路产物 |
| `checks.py` | `validate` 校验 + `doctor` 自检 + batch 课节解析 | storyboard / 环境 | 报告 |
| `config.py` | 全局配置（LLM / 录制 / TTS 参数） | — | 配置常量 |

### LLM 模块（`llm/`）

| 文件 | 功能 |
|------|------|
| `client.py` | LLM 调用封装（OpenAI 兼容网关，默认 ECNU `ecnu-plus`） |
| `image_gen.py` | AI 配图（figurative/abstract 分类 + 生成）+ 无图元素的 SVG 矢量占位 |
| `prompts/script.md` | 讲稿生成 Prompt 模板 |
| `prompts/storyboard.md` | 画面大纲生成 Prompt 模板（含完整 JSON schema） |
| `prompts/slide_content_core.md` | 分批生成 slide 的核心 prompt（LLM 兜底路径） |
| `prompts/slide_repair.md` · `slide_single_repair.md` | 布局 QA 失败后的修复 prompt |

> 注：动画 HTML 生成在包根的 `animation_gen.py` + `template_renderer.py`（F5 确定性渲染）+
> `css_hotfix.py`，不在 `pipeline/` 下，详见 `docs/animation-generation.md`。

### 动画模板（`templates/`）

| 文件 | 功能 |
|------|------|
| `base.css` | 通用 CSS（噪点、.anim 系统、框架类、卡片变量） |
| `base-template.html` | 最终 HTML 外壳 |
| `slide-controller.js` | 自写 slide 控制器 |
| `particle-canvas.js` | Canvas 粒子系统 |

### 测试（`tests/`，全部不依赖真实 LLM/网络）

| 文件 | 测试内容 |
|------|---------|
| `test_parser.py` · `test_docx_parser.py` | PDF/DOCX 提取 |
| `test_scriptwriter.py` · `test_storyboard.py` | 讲稿/画面大纲解析（纯函数） |
| `test_template_renderer.py` · `test_slide_extraction.py` · `test_animation_*` | F5 渲染、slide 提取、布局修复、prompt |
| `test_compose.py` · `test_orchestrator.py` · `test_narrate*.py` | 音画合成、端到端编排、TTS 容错 |
| `test_checks.py` · `test_script_split.py` · `test_cli.py` | 校验/自检、讲稿拆分、CLI 参数 |

---

## 二、Pipeline 流程

```
Step 1: 教材提取(PDF/DOCX)  parser.py / docx_parser.py（+ 教材图）
    ↓
Step 2: 讲稿生成            scriptwriter.py + prompts/script.md + LLM
    ↓
Step 3: 画面大纲            storyboard.py + prompts/storyboard.md + LLM
    ↓
Step 4: TTS 配音            narrator.py（回填音频时长到 JSON）
    ↓
Step 5: 动画 HTML 生成      animation_gen.py + template_renderer.py(F5) + css_hotfix.py
    ↓
Step 6: 录制（无声）        recorder.py（Playwright + ffmpeg）
    ↓
Step 7: 配音合成           compose.py（拼接分段音频 + mux）→ 有声 MP4
```

Step 1–7 已全部打通，`orchestrator.produce` 把它们串成 `t2v produce` 一条命令。

**音频先行**：Step 4 先生成音频拿时长，回填到 JSON 后传给 Step 5，确保动画时长精确匹配旁白；
Step 7 按段顺序拼接音频，长度≈视频，mux 时 `-shortest` 对齐。

---

## 三、画面大纲 JSON 数据结构

Pipeline Step 3 的输出，也是传给动画团队的核心接口。

```json
{
  "lesson_title": "第5课",
  "segments": [
    {
      "id": 1,
      "narration": "同学们好！今天我们来学习...",
      "visual_type": "title",
      "elements": [
        {"id": "e1", "type": "heading", "text": "第5课 文本处理"},
        {"id": "e2", "type": "icon_group", "items": ["分词", "词表", "BPE"]},
        {"id": "e3", "type": "image", "description": "屏幕上散落着彩色卡片..."}
      ],
      "animations": [
        {"target": "e1", "effect": "bounceIn"},
        {"target": "e2", "effect": "fadeInUp", "stagger": true}
      ]
    }
  ],
  "metadata": {
    "total_slides": 7
  }
}
```

### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `lesson_title` | string | 课程标题 |
| `segments` | array | 页面列表，每页一个元素 |
| `metadata.total_slides` | int | 页面总数 |

### segment 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 页面序号（从 1 开始） |
| `narration` | string | 旁白文本（TTS 输入） |
| `visual_type` | string | 页面视觉类型（见下方枚举） |
| `render_mode` | string | **可选**：`"template"`（默认，模板确定性渲染）或 `"llm"`（LLM 自由生 HTML）。LLM 自路由：title/closing/纯插画 illustration → `llm`，其余 → `template`。详见 §三.render_mode |
| `elements` | array | 页面元素列表（每页 5-10 个） |
| `animations` | array | 入场动画配置（每页 5-8 个） |
| `timeline` | array | **新增 v2**：精确时间轴动画触发（每页 3-6 个节点） |
| `audio_duration_sec` | float | **TTS 后回填**：音频精确时长（秒） |

### timeline 字段（新增 v2）

每个 segment 的 timeline 数组定义了**旁白讲到哪个时间点触发什么动画动作**，实现音画精确对齐，避免"开场全弹然后静止 25 秒"。

```json
"timeline": [
  {"at_sec": 0.0,   "action": "show",      "target": "e1"},
  {"at_sec": 2.5,   "action": "show",      "target": "e2,e3", "stagger": true},
  {"at_sec": 7.0,   "action": "highlight", "target": "e4"},
  {"at_sec": 12.0,  "action": "show",      "target": "e5,e6", "stagger": true}
]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `at_sec` | float | 本页开始的相对秒数（0 = 本页音频开始） |
| `action` | string | 触发动作（见下表） |
| `target` | string | 对应的 element id，多个用逗号分隔 |
| `stagger` | bool | 可选，多个元素错开依次触发 |

**timeline action 枚举：**

| 动作 | 说明 | 适用场景 |
|------|------|---------|
| `show` | 元素入场（配合 animation.effect） | 默认，新元素出现 |
| `highlight` | 高亮闪烁 | 讲到重点、关键数据 |
| `pulse` | 脉冲呼吸效果 | 数字、图标强调 |
| `fadeOut` | 元素退场 | 旧元素消失让位 |
| `transform` | 文字/形状变化 | A→B 演变 |
| `counter` | 数字从 0 滚动到目标值 | 数据卡片 |
| `draw` | SVG 路径绘制 | 图表连线 |

**设计原则：** 每页至少 3-6 个节点，at_sec 从 0.0 开始均匀分布到 audio_duration_sec 内，至少每 5-8 秒有一个动作。

### visual_type 枚举（11 种）

| 类型 | 用途 |
|------|------|
| `title` | 标题页 |
| `definition` | 概念定义 |
| `process` | 流程图（左→右） |
| `comparison` | 对比面板 |
| `data-chart` | 折线/曲线图 |
| `data-bar` | 柱状图 |
| `network` | 网络拓扑（神经网络、节点连线） |
| `tree` | 树形结构（决策树、分类） |
| `timeline` | 时间线 |
| `illustration` | 图解说明（配图+文字） |
| `activity` | 学习活动（操作步骤+演示） |

### element.type 枚举（16 种；`stat_card` 已下架，详见 animation-iteration.md v1.1）

| 类型 | 字段 | 说明 |
|------|------|------|
| `heading` | `text` | 主标题（大字号） |
| `subheading` | `text` | 副标题 |
| `text` | `text` | 正文文字 |
| `icon_group` | `items: string[]` | 一组图标/关键词（用文字标签，不用 emoji） |
| `flow_step` | `steps: string[]` | 流程步骤（带箭头连接） |
| `bar` | `items: {label, value}[]` | 柱状图 |
| `chart_line` | `description` | 折线图 |
| `node` | `text`, `description` | 网络节点 |
| `connection` | `from`, `to` | 节点间连线 |
| `activity_step` | `steps: string[]` | 活动步骤（编号列表） |
| `image` | `description`, `src?` | 示意图片（`src` 引用教材原图，否则 AI 配图 / SVG） |
| `label` | `text` | 标注文字 |
| `code` | `language`, `code` | 代码片段 |
| `comparison_panel` | `items: {title, content}[]` | 对比面板（左右两栏） |
| `quote` | `text`, `author?` | 引用框（突出金句/定义） |
| `table` | `headers: string[]`, `rows: string[][]` | 数据表格（多维/时期演变/分类对比） |

### animation.effect 枚举（8 种）

| 效果 | 说明 |
|------|------|
| `bounceIn` | 弹入（适合标题、强调元素） |
| `fadeInUp` | 从下往上淡入（最常用） |
| `fadeInLeft` | 从左往右淡入 |
| `fadeInRight` | 从右往左淡入 |
| `fadeIn` | 直接淡入 |
| `drawPath` | SVG 路径描边绘制 |
| `growBar` | 柱状图从 0 增长 |
| `typeWrite` | 逐字出现 |

### animation 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `target` | string | 对应的 element id（如 `"e1"`） |
| `effect` | string | 动画效果 |
| `stagger` | bool | 可选，是否让多个元素错开依次入场 |
| `delay` | int | 可选，延迟几档（每档 0.2s）后触发 |

### render_mode（v1.2 起新增）

每个 segment 可携带 `render_mode` 字段，决定该页 HTML 走哪条生成路径：

| 取值 | 行为 | 适用 |
|------|------|------|
| `"template"`（默认） | 走 `template_renderer.render_slide()` 确定性渲染；不支持的 visual_type/element 才 fallback 到 LLM | 信息密集页（comparison/process/data/timeline/definition...）—— 求稳，对齐/字号/动效都预设 |
| `"llm"` | 跳过模板渲染，直接进 LLM 自由生成 HTML | 结构简单但需视觉冲击的页（title/closing/纯隐喻 illustration）—— 求美，模板做不出彩 |

LLM 在 storyboard 阶段自路由：缺省/拿不准就给 `template`，一份 storyboard 通常 ≤30% 页面给 `llm`。`animation_gen.py` 路由日志会显示：
- `🧩 模板渲染 N/M 页`
- `🎨 render_mode=llm 显式交 LLM 自由生成 K 页`
- `🤖 LLM fallback 生成 N 页（不支持的 visual_type）`

`validate_storyboard` 接受 `template`/`llm`；非法值降级为 `template` 并发出 warning。

---

## 四、用法

```bash
# 列出可提取的课程
t2v list-lessons the_aim.pdf

# 端到端一步出有声成片
t2v produce textbook.docx -c 3 -s 0 --theme dark-blue-academic --model ecnu-plus -o output/ch3
t2v produce the_aim.pdf --lesson 5 --model ecnu-plus            # PDF 路径

# 只生成 storyboard（PDF / DOCX）
t2v generate the_aim.pdf --lesson 5 --model ecnu-plus
t2v generate-docx textbook.docx -c 3 -s 0 --model ecnu-plus     # 0-based 整数章/节
t2v generate the_aim.pdf --lesson 5 --skip-tts                  # 跳过 TTS
```

### 输出产物（以 DOCX 第 3 章第 0 节为例，stem=ch3_s0）

```
output/ch3/
  images/                    # 教材提取的原图
  ch3_s0_raw.txt             # 教材原文
  ch3_s0_script.txt          # 讲稿分段
  ch3_s0_storyboard.json     # 画面大纲 JSON（含音频时长）
  ch3_s0_audio/              # TTS 音频（s1.mp3 ~ sN.mp3）
  ch3_s0-<theme>.html        # 动画 HTML（animate 产物）
  ch3_s0.mp4                 # 有声成片（produce 产物）
```
（PDF 路径的 stem 为 `lesson{N}`。）