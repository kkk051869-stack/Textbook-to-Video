# Textbook-to-Video 协作计划

> 本文档为 GitHub 协作的路线图、分工方案和开放问题追踪。
> 技术方案、架构设计、难点分析等见 [PROJECT_PLAN.md](PROJECT_PLAN.md)。
>
> 创建日期：2026-05-18

---

## 一、项目现状

### 已完成

- ✅ PoC 全流程跑通（第4课 6 页动画 → 1080p 视频）
- ✅ 确认 Pipeline 6 步流程：教材→讲稿→画面大纲→生成音频→生成动画→合成
- ✅ 确认音频先行方案（先生成 TTS 拿时长，再生成匹配的动画）
- ✅ 确认动画技术栈：自写 slide 控制器 + Canvas 粒子 + SVG 噪点 + `.anim` 延迟系统
- ✅ 确认亮色主题配色方案
- ✅ 完成 50+ 参考动画分析，提炼 5 个核心视觉技巧
- ✅ TTS (edge-tts) + Playwright 录制 + ffmpeg 合并全链路可用
- ✅ recorder.py 兼容新旧两种 slide 方案（旧：Reveal.js，新：SlideController）

### 当前瓶颈

动画质量是核心瓶颈，Pipeline 工程侧基本可用但需要系统化。

---

## 二、Roadmap

### Phase 0：基建

**目标**：项目 clone 后一键跑起来

| # | 任务 | 产出 |
|---|------|------|
| 0.1 | `git init` + 首次提交 | git 仓库 |
| 0.2 | `.gitignore` | 排除 output/、references/、libs/、.env 等 |
| 0.3 | `pyproject.toml` | 可 `pip install -e .`，依赖列表 |
| 0.4 | `README.md` | 项目目标 + 环境配置 + 快速开始 |
| 0.5 | 重构目录结构 | 规范布局（见第五节） |
| 0.6 | 散落脚本收进 `src/textbook2video/` | `record.py` → `pipeline/recorder.py` 等 |
| 0.7 | 从 lesson4-v2.html 提炼基础模板 | `templates/base.css` + `slide-controller.js` |
| 0.8 | libs/ 改为 CDN 引用或下载脚本 | HTML 模板不依赖本地 libs/ |

### Phase 1：双轨并行

Phase 1 采用双轨并行策略，两条轨道前期互不依赖，通过约定的接口 JSON 联调。

```
         约定接口 JSON（画面大纲格式，见下方）
                    │
        ┌───────────┴───────────┐
        │                       │
   Track A: 动画质量         Track B: Pipeline 工程
   （前端/视觉/Prompt）      （后端/Python/集成）
        │                       │
   不需要 Pipeline 跑通      不需要动画好看
   手写 HTML demo 验证       用 lesson4-v2.html 当 fixture
        │                       │
        └───────────┬───────────┘
                    ▼
              合并 → 端到端联调
```

#### 接口 JSON Schema（两条轨道的对齐点）

Track B 生成、Track A 消费的唯一桥梁。双方必须遵守此格式。

```json
{
  "metadata": {
    "lesson_title": "人工智能的技术基础",
    "total_slides": 6
  },
  "segments": [
    {
      "id": 1,
      "narration": "同学们好！今天我们来学习人工智能的技术基础...",
      "audio_duration_sec": 11.0,
      "slide_type": "title",
      "elements": [
        {"type": "heading", "text": "人工智能的技术基础"},
        {"type": "icon_group", "items": ["数据", "算力", "算法"]}
      ],
      "animations": [
        {"target": "heading", "effect": "bounceIn"},
        {"target": "icons", "effect": "fadeInUp", "stagger": true}
      ]
    }
  ]
}
```

**slide_type 枚举（10 种）：**

| type | 用途 | 典型课程 |
|------|------|---------|
| `title` | 标题页 | 每课开头 |
| `definition` | 概念定义 | 术语解释 |
| `process` | 流程图（左→右） | 数据处理、AI 流程 |
| `comparison` | 对比面板 | AI vs 人类、新旧对比 |
| `data-chart` | 折线/曲线图 | 损失曲线、趋势 |
| `data-bar` | 柱状图 | 准确率对比 |
| `network` | 网络拓扑 | 神经网络、节点连线 |
| `tree` | 树形结构 | 决策树、分类 |
| `timeline` | 时间线 | AI 发展史、步骤序列 |
| `illustration` | 图解说明 | 配图+文字说明 |

**element.type 枚举：** `heading`、`subheading`、`text`、`icon_group`、`flow_step`、`bar`、`chart_line`、`node`、`connection`、`image`、`label`

**animation.effect 枚举：** `bounceIn`、`fadeInUp`、`fadeInLeft`、`fadeInRight`、`fadeIn`、`drawPath`（SVG 描边）、`growBar`（柱状图增长）、`typeWrite`（逐字出现）

> Schema 变更需双方对齐，每天同步时确认。冻结后不得单方面修改。

#### Track A：动画质量

**目标**：LLM 生成的动画稳定在"可用"水平

**技能要求**：HTML/CSS/JS + Prompt 工程 + 视觉审美

| # | 任务 | 产出 | 工作量 |
|---|------|------|--------|
| A1 | Prompt 模板 v2 迭代 | `prompts/animation.md` 稳定版 | ★★ |
| A2 | LLM 选型 benchmark | 同一内容 4 模型对比 + 选型结论 | ★★ |
| A3 | 10 种 slide_type demo | 10 个 HTML（每种 type 各一个） | ★★★ |
| A4 | Playwright 自动验证 | `validator.py`（截图+检查溢出/报错） | ★★ |
| A5 | 多轮迭代机制 | 生成→审查→修复循环 | ★★★ |
| A6 | `.anim` 动态节奏 | 根据音频时长自动调整动画间隔 | ★★ |

**Track A 的核心难点：**

1. **Prompt 稳定性** — 同一 prompt 跑 10 次可能只有 3 次能用的；不同课型差异大，一套 prompt 难通吃
2. **多轮迭代不收敛** — LLM 修了溢出可能删动画，修了动画可能改配色，越迭代越差
3. **"好看"没有客观标准** — 不报错 ≠ 效果好，VLM 打分目前不可靠

#### Track B：Pipeline 工程

**目标**：教材文本到带配音视频的一键流程

**技能要求**：Python + LLM API (litellm) + ffmpeg + PDF 处理

| # | 任务 | 产出 | 工作量 |
|---|------|------|--------|
| B1 | 教材解析 | `parser.py`（PDF→结构化知识点） | ★★★ |
| B2 | 讲稿生成 | `scriptwriter.py` + `prompts/script.md` | ★★ |
| B3 | 画面大纲生成 | `storyboard.py` + `prompts/storyboard.md` | ★★ |
| B4 | TTS 时长输出 | `narrator.py` 升级（输出每段精确秒数） | ★ |
| B5 | 音画同步 | `recorder.py` 升级（读取 slideTimes） | ★★ |
| B6 | CLI 串联 | `t2v generate` 端到端命令 | ★★ |

**Track B 的核心难点：**

1. **PDF 解析质量** — 教材有表格、图注、侧边栏、分栏，提取出来很脏，garbage in garbage out
2. **画面大纲 JSON 设计** — 太具体限制 LLM 创造空间，太抽象 LLM 不知道画什么
3. **音画同步毫秒精度** — Playwright 录制走真实时间，`setTimeout` 偏差、渲染卡顿都会累积

#### 联调节奏

- **每日对齐**：JSON schema 变更、进度同步、接口问题
- **第一周**：A 做完 A1+A2，B 做完 B1+B4 → 第一次端到端联调
- **第二周**：A 做完 A3+A4，B 做完 B2+B3 → JSON schema 冻结
- **第三周**：A 做完 A5+A6，B 做完 B5+B6 → 完整联调

#### 共享资源

| 资源 | 说明 |
|------|------|
| LLM API | 各自使用自己的 API Key，通过 `.env` 配置 |
| 测试 fixture | `animation-research/demos/lesson4-v2.html` 作为 B 的录制 fixture；B 的 parser 输出作为 A 的 prompt 测试输入 |
| JSON schema | 接口格式变更需双方对齐，冻结前可自由调整，冻结后需协商 |

### Phase 2：质量与扩展

**目标**：稳定产出多课程视频

| # | 任务 | 产出 |
|---|------|------|
| 2.1 | VLM 自动审查（截图→质量评分） | `reviewer.py` |
| 2.2 | TTS 升级（Fish Audio / CosyVoice） | 多 TTS 后端 |
| 2.3 | 10 个课程的视频产出 | 10 个 MP4 |
| 2.4 | 动画组件沉淀（复用率高的代码） | 组件库 v1 |
| 2.5 | 字幕生成 | SRT 输出 |

---

## 三、开放问题与优化方向（按优先级）

### P0 — 不解决就没法用

| # | 问题 | 说明 | 状态 |
|---|------|------|------|
| OP-1 | **音画同步** | 当前均匀分配时间，讲稿和画面会错位。需要按音频段落时长分配 slide 停留时间 | 🔴 未开始 |
| OP-2 | **Prompt 模板 v2** | 当前模板没有整合视觉技巧（噪点、渐变、Canvas 粒子等），LLM 不知道这些模式 | 🟡 已有研究成果，待写模板 |
| OP-3 | **LLM 选型** | 不知道哪个模型生成动画质量最好，需要 benchmark | 🔴 未开始 |

### P1 — 影响质量但不阻塞

| # | 问题 | 说明 | 状态 |
|---|------|------|------|
| OP-4 | **动画内容过于文字堆砌** | 当前动画页文字太多，缺乏视觉隐喻。需要 Prompt 引导"图文并茂" | 🔴 未开始 |
| OP-5 | **多轮迭代自动化** | AI_Animation 项目的 Prompt 模式是多轮的，需要自动"生成→审查→修复"循环 | 🔴 未开始 |
| OP-6 | **Playwright 自动验证** | 生成 HTML 后自动检查每页高度是否溢出 1080px | 🔴 未开始 |
| OP-7 | **主题参数化** | 亮色/暗色、配色方案可配置，Prompt 中一个参数切换 | 🔴 未开始 |

### P2 — 锦上添花

| # | 问题 | 说明 | 状态 |
|---|------|------|------|
| OP-8 | **VLM 审查** | 生成动画后自动截图，用视觉模型评估质量 | 🟢 后续 |
| OP-9 | **Manim 集成** | 数学/物理复杂场景使用 Manim 渲染 | 🟢 后续 |
| OP-10 | **Lottie 动画** | 引入 After Effects 导出的专业动画 | 🟢 后续 |
| OP-11 | **字幕生成** | 从讲稿文本 + 时间轴生成 SRT 字幕 | 🟢 后续 |
| OP-12 | **Web UI** | FastAPI + React 前端 | 🟢 后续 |

---

## 四、项目结构

```
Textbook-to-Video/
├── src/textbook2video/          # Python 包
│   ├── __init__.py
│   ├── cli.py                   # CLI 入口：t2v generate
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── config.py            # 全局配置
│   │   ├── parser.py            # Phase 1: PDF→知识点（待开发）
│   │   ├── scriptwriter.py      # Phase 2: 知识点→讲稿+画面大纲（待开发）
│   │   ├── animator.py          # Phase 3: 画面大纲→HTML 动画（待开发）
│   │   ├── narrator.py          # Phase 4: 讲稿→TTS 音频（含时长）
│   │   ├── recorder.py          # Phase 5: HTML→视频（Playwright 录制）
│   │   └── composer.py          # Phase 6: 音频拼接 + 音视频合并
│   ├── llm/
│   │   ├── client.py            # LLM 调用封装 (litellm)（待开发）
│   │   └── prompts/             # Prompt 模板
│   │       ├── animation.md     # 动画 HTML 生成（核心 Prompt）
│   │       ├── script.md        # 讲稿生成（待开发）
│   │       └── storyboard.md    # 画面大纲生成（待开发）
│   └── templates/               # 动画基础资源
│       ├── base.css             # 基础 CSS（噪点、粒子、.anim 系统）
│       ├── slide-controller.js  # 自写 slide 控制器代码
│       └── particle-canvas.js   # Canvas 粒子系统代码
│
├── animation-research/          # 动画研究 & demo
│   ├── demos/                   # 手写/手调的动画 demo HTML
│   ├── components/              # 可复用的动画组件原型
│   └── examples/                # 参考动画（如 transformer-attention.html）
│
├── tests/                       # 测试
├── output/                      # 产物（.gitignore）
├── references/                  # 参考素材（.gitignore）
├── docs/
│   ├── PROJECT_PLAN.md          # 项目计划
│   ├── COLLABORATION.md         # 本文档
│   ├── poc-process.md           # PoC 流程记录
│   └── research/                # 早期研究（归档）
│       └── 可行性分析.md        # Pipeline 架构、学术参考、成本分析
├── pyproject.toml
├── .gitignore
└── README.md
```

**不进 git 的目录**：

| 目录/文件 | 理由 |
|-----------|------|
| `output/` | 产物文件，每个开发者本地生成 |
| `references/` | 参考素材 + 教材原文，体积大 |
| `libs/` | 旧方案残留的 JS 库，新方案零外部依赖 |
| `.env` | API keys 等敏感信息 |

---

## 五、上 GitHub 前的 Checklist

- [ ] `git init` + 首次提交
- [x] `.gitignore` 配置
- [x] `pyproject.toml` 编写（依赖列表）
- [x] `README.md` 最简版（项目目标 + 环境配置 + 快速开始）
- [ ] 检查无敏感信息（API key、密码）
- [x] `libs/` 已不进 git（新方案零外部依赖）
- [x] `references/` 不提交，README 说明获取方式
- [ ] 创建 GitHub repo + 推送

### Phase 0 完成状态

| # | 任务 | 状态 |
|---|------|------|
| 0.1 | `git init` + 首次提交 | ⬜ 待执行 |
| 0.2 | `.gitignore` | ✅ 已完成 |
| 0.3 | `pyproject.toml` | ✅ 已完成 |
| 0.4 | `README.md` | ✅ 已完成 |
| 0.5 | 重构目录结构 | ✅ 已完成（删除旧脚本，新建 animation-research/，文档归档） |
| 0.6 | 散落脚本收进包 | ✅ 已完成（record.py→pipeline/recorder.py 等，旧文件已删除） |
| 0.7 | 提炼基础模板 | ✅ 已完成（templates/base.css + slide-controller.js + particle-canvas.js） |
| 0.8 | Prompt 模板 v2 | ✅ 已完成（llm/prompts/animation_direct.md 更新为新方案） |
| 0.9 | 项目结构重构 | ✅ 已完成（animation-research/ 独立，过时文档归档，教材进 references/） |
