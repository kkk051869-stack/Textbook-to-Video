# Textbook-to-Video

中小学 AI 教育教材 → 带动画 + 配音的教学视频，全自动生成。

## Pipeline

```
教材 PDF → 知识点解析 → 讲稿生成 → TTS 配音 → 动画 HTML → 录制合成 → MP4 视频
```

6 步流程，音频先行（先生成 TTS 拿时长，再生成匹配时长的动画）。

## 快速开始

### 1. 环境准备

```bash
# 创建 conda 环境
conda create -n textbook2video python=3.11 -y
conda activate textbook2video

# 安装依赖
pip install -e .

# 安装 Playwright 浏览器
playwright install chromium

# 安装 ffmpeg（conda 环境内）
conda install -c conda-forge ffmpeg
```

### 2. 下载第三方资源

```bash
# 参考素材（体积大，不在 git 中）
# 从项目 Release 或网盘下载 references/ 目录，放到项目根目录
```

### 3. 运行

```bash
# 录制动画 HTML 为视频
t2v record docs/research/animation-research/demos/lesson4-v2.html output/demo.mp4 --duration 35

# 完整 pipeline（开发中）
t2v generate input/textbook.pdf --output output/
```

## 项目结构

```
Textbook-to-Video/
├── src/textbook2video/          # Python 包
│   ├── cli.py                   # CLI 入口：t2v record / t2v generate
│   ├── pipeline/                # Pipeline 各模块
│   │   ├── recorder.py          # HTML→视频（Playwright）
│   │   ├── narrator.py          # TTS 配音（edge-tts）
│   │   ├── composer.py          # 音视频合并（ffmpeg）
│   │   └── config.py            # 全局配置
│   ├── llm/                     # LLM 调用 + Prompt 模板
│   │   └── prompts/animation.md # 动画生成 Prompt
│   └── templates/               # 动画基础资源
│       ├── base.css             # 通用 CSS（噪点、.anim 系统）
│       ├── slide-controller.js  # 自写 slide 控制器
│       └── particle-canvas.js   # Canvas 粒子系统
│
├── docs/                        # 项目文档
│   ├── PROJECT_PLAN.md          # 项目计划
│   ├── COLLABORATION.md         # 协作路线图
│   ├── poc-process.md           # PoC 流程记录
│   ├── TeachMaster.md           # 论文分析（参考）
│   ├── animation-generation.md  # 动画生成子系统说明
│   ├── fix-plan-json-to-html.md # JSON→HTML 根因分析与修复史
│   └── research/                # 早期研究（归档）+ animation-research/（动画 demo & 组件原型）
│
├── tests/                       # 测试
├── output/                      # 产物（.gitignore）
├── references/                  # 参考素材（.gitignore）
├── .gitignore
├── pyproject.toml
└── README.md
```

## 技术栈

| 层 | 技术 |
|----|------|
| 动画 | 自写 SlideController + Canvas 粒子 + SVG 噪点 + `.anim` 延迟系统 |
| TTS | edge-tts（当前）/ Fish Audio（规划中） |
| 录制 | Playwright (Chromium) |
| 合成 | ffmpeg |
| LLM | litellm（Claude/GPT/GLM/Qwen 可切换） |

## 文档

- [项目计划](docs/PROJECT_PLAN.md) — 完整项目规划、技术决策、开放问题
- [协作计划](docs/COLLABORATION.md) — GitHub 协作路线图
- [PoC 流程记录](docs/poc-process.md) — 第一个 demo 的完整过程

## License

MIT
