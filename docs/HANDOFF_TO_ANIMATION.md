# 给动画生成同学的交接文档

本文档说明：我做了什么、输出什么格式的 JSON、你需要消费什么、怎么跑通联调。

## 1. 项目整体目标

把中文 AI 教育教材（DOCX）自动转换成带配音和动画的教学视频（MP4）。

完整链路：

```
教材 DOCX
  → 按章节抽取文本（parser）
  → 生成讲稿分段（scriptwriter + LLM）
  → 生成画面大纲 JSON（storyboard + LLM）
  → TTS 配音 + 回填音频时长（narrator）
  → 【你的工作】根据 JSON 生成动画 HTML
  → Playwright 录制 HTML 为无声 MP4（recorder）
  → ffmpeg 合成音频 + 视频 → 最终 MP4（composer）
```

你只需要关注中间那一步：**读取 storyboard JSON → 输出动画 HTML**。

## 2. 我做了什么（你不用管的部分）

### 2.1 项目结构

```
src/textbook2video/
├── cli.py                    # CLI 入口，命令 `t2v`
├── pipeline/
│   ├── config.py             # 全局配置（LLM、TTS、录制参数）
│   ├── parser.py             # DOCX/PDF 文本抽取
│   ├── scriptwriter.py       # LLM 生成讲稿
│   ├── storyboard.py         # LLM 生成画面大纲 JSON
│   ├── narrator.py           # edge-tts 生成音频
│   ├── recorder.py           # Playwright 录制 HTML → MP4
│   └── composer.py           # ffmpeg 音视频合成
├── llm/
│   ├── client.py             # LLM API 封装（华东师大大模型服务）
│   └── prompts/
│       ├── script.md         # 讲稿生成 prompt
│       ├── storyboard.md     # 画面大纲生成 prompt（JSON schema 定义在这里）
│       └── animation_direct.md  # 直接生成 HTML 的 prompt（备用方案）
└── templates/
    ├── base.css              # 基础样式（.anim 动画系统、slide 布局）
    ├── slide-controller.js   # 自研翻页控制器
    └── particle-canvas.js    # Canvas 粒子背景
```

### 2.2 各模块职责

| 模块 | 做什么 | 输出 |
|------|--------|------|
| parser | 从 DOCX 按章节/小节抽取正文 | 纯文本 |
| scriptwriter | 调 LLM 把教材文本转成口语化讲稿，拆成 6-10 段 | `list[str]` |
| storyboard | 调 LLM 为每段讲稿设计画面，输出结构化 JSON | `dict`（见下文） |
| narrator | 用 edge-tts 为每段讲稿生成 MP3，读取时长回填到 JSON | MP3 文件 + `audio_duration_sec` |
| recorder | Playwright 打开 HTML，按每页时长翻页并录屏 | 无声 MP4 |
| composer | 拼接所有 MP3 + 合并到 MP4 | 最终 MP4 |

### 2.3 LLM 服务

用的是华东师范大学的大模型 API（兼容 OpenAI 格式）：

- 模型：`ecnu-max`（DeepSeek-V4-Flash，1M 上下文）
- 地址：`https://chat.ecnu.edu.cn/open/api/v1`
- 需要 `.env` 里配 `ECNU_API_KEY`

## 3. 你需要消费的 JSON 格式

接口文件路径约定：

```
output/<section_id>_storyboard.json
```

### 3.1 完整结构示例

```json
{
  "lesson_title": "绪论 - 时代背景",
  "metadata": {
    "source_type": "docx",
    "chapter": "第一章 绪论",
    "section": "一、时代背景",
    "total_slides": 9
  },
  "segments": [
    {
      "id": 1,
      "narration": "同学们好，今天我们来了解...",
      "audio_duration_sec": 11.0,
      "visual_type": "title",
      "elements": [
        {"id": "e1", "type": "heading", "text": "百年未有之大变局"},
        {"id": "e2", "type": "subheading", "text": "数字素养：我们的必修课"},
        {"id": "e3", "type": "icon_group", "items": ["经济重心东移", "科技革命", "新兴国家崛起"]},
        {"id": "e4", "type": "image", "description": "世界地图，箭头从西指向东，浅蓝色背景"}
      ],
      "animations": [
        {"target": "e1", "effect": "bounceIn"},
        {"target": "e2", "effect": "fadeInUp"},
        {"target": "e3", "effect": "fadeInUp", "stagger": true},
        {"target": "e4", "effect": "fadeIn"}
      ],
      "timeline": [
        {"at_sec": 0.0, "action": "show", "target": "e1"},
        {"at_sec": 2.0, "action": "show", "target": "e2"},
        {"at_sec": 4.0, "action": "show", "target": "e3", "stagger": true},
        {"at_sec": 7.0, "action": "show", "target": "e4"},
        {"at_sec": 9.0, "action": "highlight", "target": "e1"}
      ]
    }
  ]
}
```

### 3.2 字段说明

| 字段 | 说明 |
|------|------|
| `lesson_title` | 章节标题，可用于封面 |
| `metadata.total_slides` | 总页数 = `segments.length` |
| `segments[].id` | 段落编号（从 1 开始） |
| `segments[].narration` | 该页对应的讲稿旁白（你不需要渲染它，但可以参考内容来理解画面意图） |
| `segments[].audio_duration_sec` | 该页音频时长（秒）。**这是你控制每页停留时间的依据** |
| `segments[].visual_type` | 页面类型，决定整体布局风格 |
| `segments[].elements` | 页面中的结构化元素列表 |
| `segments[].animations` | 每个元素的入场动画建议 |
| `segments[].timeline` | 精确时间轴：旁白讲到第几秒时触发什么动作 |

### 3.3 枚举值速查

**visual_type（11 种页面类型）：**

`title` · `definition` · `process` · `comparison` · `data-chart` · `data-bar` · `network` · `tree` · `timeline` · `illustration` · `activity`

**element.type（16 种元素类型）：**

`heading` · `subheading` · `text` · `icon_group` · `flow_step` · `bar` · `chart_line` · `node` · `connection` · `activity_step` · `image` · `label` · `code` · `comparison_panel` · `quote` · `stat_card`

**animation.effect（14 种动画效果）：**

`bounceIn` · `fadeInUp` · `fadeInLeft` · `fadeInRight` · `fadeInDown` · `fadeIn` · `zoomIn` · `slideInLeft` · `slideInRight` · `drawPath` · `growBar` · `typeWrite` · `pulse` · `highlight`

**timeline.action（7 种时间轴动作）：**

`show` · `highlight` · `pulse` · `fadeOut` · `transform` · `counter` · `draw`

## 4. 你需要输出什么

一个单文件 HTML：

```
output/<section_id>_animation.html
```

### 4.1 必须满足的条件

1. **暴露精确翻页时长**（最重要）：

```javascript
// 单位毫秒，顺序与 segments 一一对应
window.SLIDE_TIMES = [11000, 15000, 13200, ...];
```

2. **视口 1920×1080**，所有内容不超出可视区域
3. **自动播放**，不依赖用户点击
4. **无阻断性 JS 错误**（控制台可以有 warning，不能有 error）
5. **单页主体内容高度控制在 900px 内**（留 margin 给顶部/底部装饰）

### 4.2 推荐使用项目已有模板

项目里已经准备了基础设施，你可以直接内联到 HTML 中：

```
src/textbook2video/templates/base.css          → 动画类 .anim + .d1~.d12 延迟
src/textbook2video/templates/slide-controller.js → 自动翻页控制器
src/textbook2video/templates/particle-canvas.js  → Canvas 粒子背景（可选）
```

SlideController 用法：

```javascript
const ctrl = new SlideController({
  slideDurations: [11000, 15000, 13200]  // 等同于 SLIDE_TIMES
});
ctrl.start();
```

### 4.3 不要用的东西

- Reveal.js（翻页时序不可控，PoC 踩过坑）
- Chart.js（Canvas 渲染在 Playwright 录制时有 bug）
- Animate.css（和项目自研 .anim 系统冲突）
- 任何 CDN 外部依赖（录制时可能断网）

### 4.4 设计风格

- 大学通识课风格：专业、简洁、有质感
- 亮色/浅色背景，主色调蓝色系，辅助色橙色/绿色
- 扁平化信息图风格，不要低幼化卡通
- `image` 类型元素：用 CSS/SVG 画示意图，不需要真实图片

## 5. 怎么跑通联调

### 5.1 环境准备

```bash
# 克隆项目
git clone <repo>
cd Textbook-to-Video-master

# 安装 Python 包（需要 Python 3.11+）
pip install -e .

# 安装 Playwright 浏览器（录制用）
playwright install chromium

# 安装 ffmpeg（音视频合成用）
conda install -c conda-forge ffmpeg

# 配置 API Key（如果需要自己跑 LLM 生成）
cp .env.example .env
# 编辑 .env 填入 ECNU_API_KEY
```

### 5.2 最小联调流程

```bash
# 1. 我已经生成好了示例 JSON，你可以直接用：
#    output/demo_ch1s1/section_storyboard.json

# 2. 你读取 JSON，生成 HTML：
#    output/demo_ch1s1/section_animation.html

# 3. 我来录制：
t2v record output/demo_ch1s1/section_animation.html output/demo_ch1s1/section_animation.mp4 --duration 90

# 4. 后续接 TTS + 合成（我来做）
```

### 5.3 现成的示例 JSON

仓库里已有可直接使用的 storyboard JSON：

```
output/demo_ch1s1/section_storyboard.json      → 第一章第一节"时代背景"，9 段
output/demo_ch1s1_v2/section_storyboard.json   → 同上，带 audio_duration_sec
output/demo_final/section_storyboard.json      → 最终版
```

你可以先拿 `demo_ch1s1_v2` 的 JSON 开始做，因为它已经有真实音频时长。

## 6. 双方边界总结

**我负责（你不用管）：**

- DOCX 教材解析
- LLM 讲稿生成
- LLM 画面大纲 JSON 生成
- TTS 配音 + 音频时长回填
- HTML 录制成 MP4
- 音视频合成
- CLI 工具串联

**你负责：**

- 读取 `*_storyboard.json`
- 根据 `visual_type` / `elements` / `animations` / `timeline` 生成动画 HTML
- 在 HTML 中写入 `window.SLIDE_TIMES`（精确到毫秒）
- 保证 1920×1080 可录制、无溢出、无 JS 阻断错误

**接口文件：**

```
我给你：output/<section_id>_storyboard.json
你给我：output/<section_id>_animation.html
```

## 7. 注意事项

### 7.1 音画同步是第一优先级

动画好看很重要，但**不能和旁白错位**。每页停留时间必须严格等于 `audio_duration_sec`。

如果 JSON 里暂时没有 `audio_duration_sec`，可以先用默认值 10 秒联调，但最终必须接回真实时长。

### 7.2 一段 segment = 一页 slide

默认 `segments[0]` → slide 1，`segments[1]` → slide 2 ...

如果你需要把一段拆成多页或合并多段，提前告诉我，因为会影响翻页和音频对齐。

### 7.3 JSON schema 可能小幅调整

当前字段已经够联调。如果你发现某些字段太抽象、不够生成动画，直接告诉我，我改 storyboard prompt。

### 7.4 timeline 字段的用法

`timeline` 定义了"旁白讲到第几秒时触发什么动作"。比如旁白说到"请看这张图"时，对应的 `at_sec` 会触发 `show` 图片元素。

你可以选择：
- 严格按 timeline 实现（最佳体验）
- 或者简化为按顺序依次入场（最小可用版本）

### 7.5 后续我会补自动验证

计划用 Playwright 自动检查你的 HTML：

- 每页是否超出视口
- 是否有 JS error
- 是否有空白页
- 是否能按时长正常翻页
- 是否能正常录制

所以 HTML 结构尽量清晰，关键状态不要藏太深。

## 8. 有问题找我

如果遇到：
- JSON 字段看不懂 → 问我
- 某个 visual_type 不知道怎么布局 → 问我，我可以调 prompt 让 JSON 给更多信息
- 需要新的 element.type → 告诉我，我加到 schema 里
- 录制出来效果不对 → 把 HTML 发我，我用 recorder 跑一下看看
