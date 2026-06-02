# Pipeline 实现文档

> 记录当前 Pipeline 各模块功能、接口和 JSON 数据结构。
> 创建日期：2026-05-19
> 最近更新：2026-05-31（新增 DOCX 支持、timeline 时间轴字段、大学受众适配）

---

## 一、代码文件说明

### CLI 入口

| 文件 | 功能 |
|------|------|
| `cli.py` | CLI 入口，提供 `t2v` 三条子命令 |

**命令列表：**
```
t2v record <input.html> <output.mp4>                        — 录制动画 HTML 为视频
t2v generate <input.pdf> --lesson <N>                       — 完整 Pipeline（PDF）
t2v generate <input.docx> --chapter <名> --section <名>     — 完整 Pipeline（DOCX）
t2v list-lessons <input.pdf|docx>                           — 列出教材中可提取的课程/章节
```

### Pipeline 模块（`pipeline/`）

| 文件 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `parser.py` | PDF/DOCX 按课/节提取教材文本 | PDF(课号) 或 DOCX(章节名) | 文本字符串 |
| `scriptwriter.py` | 调用 LLM 生成讲稿 | 教材文本 | 讲稿分段列表 |
| `storyboard.py` | 调用 LLM 生成画面大纲 | 讲稿分段 | 画面大纲 JSON |
| `narrator.py` | TTS 配音 | 讲稿文本列表 | MP3 文件 + 音频时长 |
| `recorder.py` | HTML 动画 → MP4 录制 | HTML 文件路径 | MP4 视频文件 |
| `composer.py` | 音频拼接 + 音视频合并 | 音频/视频文件 | 合成后的视频文件 |
| `config.py` | 全局配置（LLM / 录制 / TTS 参数） | — | 配置常量 |

### LLM 模块（`llm/`）

| 文件 | 功能 |
|------|------|
| `client.py` | LLM 调用封装（华东师范大学大模型服务，OpenAI 兼容接口） |
| `prompts/script.md` | 讲稿生成 Prompt 模板 |
| `prompts/storyboard.md` | 画面大纲生成 Prompt 模板（含完整 JSON schema） |
| `prompts/animation_direct.md` | 动画页面生成 Prompt 模板（v2，供动画阶段使用） |

### 动画模板（`templates/`）

| 文件 | 功能 |
|------|------|
| `base.css` | 通用 CSS（噪点、.anim 系统） |
| `slide-controller.js` | 自写 slide 控制器 |
| `particle-canvas.js` | Canvas 粒子系统 |

### 测试（`tests/`）

| 文件 | 测试内容 |
|------|---------|
| `test_parser.py` | PDF 提取（页码范围校验、实际提取内容、无效课号） |
| `test_scriptwriter.py` | 讲稿解析逻辑（纯函数，不调 LLM） |
| `test_storyboard.py` | 画面大纲 JSON 解析（纯函数，不调 LLM） |
| `test_cli.py` | CLI 参数解析 |

---

## 二、Pipeline 流程

```
Step 1: PDF 提取         parser.py
    ↓
Step 2: 讲稿生成          scriptwriter.py + prompts/script.md + LLM
    ↓
Step 3: 画面大纲          storyboard.py + prompts/storyboard.md + LLM
    ↓
Step 4: TTS 配音          narrator.py（回填音频时长到 JSON）
    ↓
Step 5: 动画 HTML 生成    （动画团队负责，不在本 pipeline 中）
    ↓
Step 6: 录制合成          recorder.py + composer.py
```

**音频先行**：Step 4 先生成音频拿时长，回填到 JSON 后传给 Step 5，确保动画时长精确匹配旁白。

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

### element.type 枚举（15 种）

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
| `image` | `description` | 示意图片（动画师根据描述创作） |
| `label` | `text` | 标注文字 |
| `code` | `language`, `code` | 代码片段 |
| `comparison_panel` | `items: {title, content}[]` | 对比面板 |

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

---

## 四、用法

```bash
# 列出可提取的课程
t2v list-lessons the_aim.pdf

# 完整 Pipeline（PDF → 讲稿 → 画面大纲 → TTS 配音）
t2v generate the_aim.pdf --lesson 5

# 跳过 TTS，只生成讲稿 + 画面大纲
t2v generate the_aim.pdf --lesson 5 --skip-tts

# 指定模型
t2v generate the_aim.pdf --lesson 5 --model ecnu-plus
```

### 输出产物

```
output/
  lesson{N}_raw.txt          # PDF 提取的教材原文
  lesson{N}_script.txt       # 讲稿分段
  lesson{N}_storyboard.json  # 画面大纲 JSON（含音频时长）
  lesson{N}_audio/           # TTS 音频文件（s1.mp3 ~ s{N}.mp3）
```