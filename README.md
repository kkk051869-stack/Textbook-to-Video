# Textbook-to-Video

把教材（PDF / DOCX）全自动转成**带动画 + 配音**的教学视频。Python 包 `textbook2video`，命令行工具 `t2v`。

## Pipeline

```
教材(PDF/DOCX) → 解析 → 讲稿 → 画面大纲(storyboard) → TTS配音 → 动画HTML → 录制 → 配音合成 → MP4
                parser  scriptwriter  storyboard       narrator   animate    record   compose
```

**音频先行**：先用 TTS 拿到每段旁白时长，再据此决定每页画面展示多久，实现音画对齐。

**确定性渲染（F5）**：storyboard 的结构化 `elements` 由 `template_renderer` 套框架确定性渲染成 HTML，不依赖 LLM 手写样式；只有不支持的视觉类型才回退到 LLM。

**可复用与可观察**：`produce` 默认生成 SRT 字幕轨和 `*_quality.json` 确定性质量报告；也可用 `--from-script` / `--from-storyboard` / `--from-html` 从中间产物继续，避免小改动重跑整条 LLM 链路。

**教学语义层**：`generate` / `generate-docx` / `produce` 会先生成 `*_lesson_plan.json`，把教学目标、知识点、活动和检测题作为 script/storyboard 的共同约束；`*_quality.json` 会在存在 lesson plan 时报告知识点覆盖率。

**时间化动画**：TTS 生成真实时长后，会输出 `*_timed_storyboard.json` 并回写 `animations[].trigger_at_sec`，让元素尽量跟随旁白/字幕节奏出现。

## 快速开始

### 1. 环境（Python ≥ 3.11）

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate                  # 激活虚拟环境
pip install -e ".[dev]"
playwright install chromium                # 若系统无 Edge/Chrome；网络不稳多试几次
brew install ffmpeg                         # 录制/配音/合成都用它（Linux 用 apt 等）
```

**Windows（PowerShell）**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1               # 激活；若被策略拦截，先执行下一行再重试
# Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e ".[dev]"
playwright install chromium                # Windows 自带 Edge，默认录制即用它，这步可省
winget install Gyan.FFmpeg                  # 安装 ffmpeg（或 choco install ffmpeg），装完重开终端
```

> **激活虚拟环境后**，下文直接用 `t2v ...`。
> 若不想激活：macOS/Linux 用 `.venv/bin/t2v ...`，Windows 用 `.\.venv\Scripts\t2v ...`。

### 2. 配置 LLM 凭据

在项目根新建 `.env`（已 gitignore，**勿提交/打印密钥**）：

```
ECNU_API_KEY=...                              # 华东师大大模型网关
ECNU_BASE_URL=https://chat.ecnu.edu.cn/open/api/v1
ECNU_DEFAULT_MODEL=ecnu-plus                   # 推荐 ecnu-plus（快）；ecnu-max 慢且偶发超时
```

也支持通用 `LLM_API_KEY` / `LLM_BASE_URL`（优先级更高）。Windows 下可用记事本或 `ni .env` 创建。

### 3. 自检 + 一键出片

```bash
# 跑前自检环境（凭据/ffmpeg/浏览器/TTS）
t2v doctor

# 端到端一步出有声成片（教材 → MP4，写成一行，跨平台通用）
t2v produce textbook.docx --chapter 3 --section 0 --theme dark-blue-academic --model ecnu-plus -o output/ch3

# 从已有 storyboard 继续出片（跳过解析/讲稿/storyboard，重新配音+渲染+录制+合成）
t2v produce textbook.docx --from-storyboard output/ch3/ch3_s0_storyboard.json --theme dark-blue-academic --model ecnu-plus -o output/ch3
```

## 命令一览

`t2v <command>`，全部 `--help` 可查。

| 命令 | 作用 |
|------|------|
| **`produce`** | ★端到端：教材 → 有声 MP4（generate→animate→record→配音合成） |
| `produce --from-*` | 从已有 script/storyboard/html 继续出片，缩短迭代反馈 |
| `batch` | 对多个课节批量 `produce`（`--sections "3:0,3:1"`，单节失败不影响其余） |
| `doctor` | 运行前环境自检（凭据/ffmpeg/浏览器/TTS，`--ping` 测 LLM 连通） |
| `list-lessons` | 列出教材可解析的章节/课 |
| `generate` / `generate-docx` | 教材 → 讲稿 + storyboard(+配音)（PDF / DOCX 含图片提取） |
| `script` | 只生成讲稿 → `*_script.txt`（先审讲稿再做画面） |
| `storyboard` | 从 `*_script.txt` 重做画面大纲（讲稿满意、只想重做画面时） |
| `narrate` | 读 storyboard.json 重生成 TTS 配音并回写时长；`--only` 可只重配指定页 |
| `validate` | 静态校验 storyboard JSON（类型/必填字段/图片 src/段数一致性） |
| `preview` | storyboard JSON → 本地 HTML 预览页；`--edit` 可本地编辑并保存 JSON |
| `animate` | storyboard JSON → 单文件动画 HTML；`--only` 可只生成指定页局部 HTML |
| `record` | 动画 HTML → MP4（**只录画面、无声**） |
| `mux` | 把分段配音合成进已录视频 → 有声 MP4 |

### 分步用法（便于中途审阅/重做）

```bash
t2v generate-docx textbook.docx -c 3 -s 0 --model ecnu-plus -o output/ch3
t2v preview output/ch3/ch3_s0_storyboard.json --open
t2v preview output/ch3/ch3_s0_storyboard.json --edit --open
t2v narrate output/ch3/ch3_s0_storyboard.json --only 3
t2v animate output/ch3/ch3_s0_storyboard.json --only 3 --theme dark-blue-academic --model ecnu-plus
t2v animate output/ch3/ch3_s0_storyboard.json --theme dark-blue-academic --model ecnu-plus
t2v record output/ch3/ch3_s0.html out.mp4 --duration 90
t2v mux out.mp4 output/ch3/ch3_s0_audio out_voiced.mp4   # record 无声，需此步加配音
```

> 提示：`record` 单独跑出来的是**哑视频**，要声音用 `produce` 一步到位，或 `record` 后再 `mux`。
> `preview --edit` 保存成功后会显示下一步建议命令；第一次保存前会自动生成 `*.json.bak`，方便恢复。

### Windows 注意事项

- **ffmpeg 必须在 PATH**：录制、取时长、配音合成都依赖它。`winget install Gyan.FFmpeg` 或 `choco install ffmpeg` 后**重开终端**，再用 `t2v doctor` 确认能找到。
- **浏览器**：Windows 自带 Edge，默认 `--browser msedge` 开箱即用，通常无需 `playwright install`；若没有 Edge，会自动回退到内置 chromium（先 `playwright install chromium`）。
- **中文输出**：控制台已自动切到 UTF-8，无需 `chcp 65001`。
- **多行命令换行符不同**：bash 用 `\`，PowerShell 用反引号 `` ` ``，cmd 用 `^`。**最稳妥是把命令写成一行**（本文 `produce` 示例即一行）。
- **路径分隔符**：示例里的 `output/ch3/...` 在 PowerShell 中也能用 `/`；若用 cmd 习惯反斜杠 `\` 亦可。

## 项目结构

```
Textbook-to-Video/
├── src/textbook2video/
│   ├── cli.py                   # CLI 入口（13 个子命令）
│   ├── animation_gen.py         # ★storyboard JSON → 单文件 HTML（分批生成/提取/合并/布局QA/修复）
│   ├── template_renderer.py     # ★F5：结构化 elements 确定性渲染成框架类 HTML
│   ├── css_hotfix.py            # 布局 QA 失败时的 0-token CSS 热修复
│   ├── pipeline/
│   │   ├── parser.py            # PDF(页码表) + DOCX(样式) 解析 + 教材图提取
│   │   ├── docx_parser.py       # DOCX 另一套解析（按 Heading 样式）
│   │   ├── scriptwriter.py      # 教材文本 → 讲稿分段（LLM）
│   │   ├── storyboard.py        # 讲稿 → 画面大纲 JSON（LLM）
│   │   ├── narrator.py          # TTS 配音（edge-tts）+ ffmpeg 取时长
│   │   ├── recorder.py          # 动画 HTML → MP4（Playwright + ffmpeg）
│   │   ├── compose.py           # 音画合成：拼接配音 + mux 到视频
│   │   ├── subtitles.py         # storyboard → SRT 字幕
│   │   ├── quality.py           # 确定性质量报告（字幕/音频/布局/图片/时长）
│   │   ├── orchestrator.py      # 生成编排 + 端到端 produce
│   │   ├── checks.py            # validate 校验 + doctor 自检 + batch 解析
│   │   └── config.py            # 全局配置 + LLM 凭据选择（.env）
│   ├── llm/
│   │   ├── client.py            # litellm 封装（OpenAI 兼容网关）
│   │   ├── image_gen.py         # AI 配图 + SVG 矢量占位生成
│   │   └── prompts/             # script / storyboard / slide_content_core / *_repair 模板
│   ├── themes/                  # 主题 JSON：bright / dark-blue-academic / 3b1b-math
│   └── templates/               # base.css / base-template.html / slide-controller.js / particle-canvas.js
├── docs/                        # 项目文档（见下）
├── tests/                       # 测试（不依赖真实 LLM/网络）
├── output/                      # 产物（.gitignore）
├── CLAUDE.md                    # 给 AI 助手的项目上下文 + 关键陷阱
├── pyproject.toml
└── README.md
```

## 技术栈

| 层 | 技术 |
|----|------|
| 解析 | pdfplumber / python-docx + 教材图提取 |
| LLM | litellm（OpenAI 兼容网关，默认 ECNU `ecnu-plus`） |
| 动画 | 确定性模板渲染 + 自写 SlideController + Canvas 粒子 + `.anim` 延迟系统 |
| TTS | edge-tts |
| 录制 | Playwright (Chromium/Edge) |
| 合成 | ffmpeg |

## 文档

- [文档索引](docs/文档索引.md) — 按架构、运行、设计、研究和历史分类的完整入口。
- [项目原理](docs/架构/项目原理.md) — 教材到 MP4 的架构、产物关系和时间同步机制。
- [云端全流程出片手册](docs/运行/云端全流程出片手册.md) — 云端稳定批量出片的操作门禁。
- [分镜增强器改造任务书](docs/设计/分镜增强器改造任务书.md) — 页面元素收敛与后续改造计划。

## 测试

```bash
pytest tests/ -q          # 已激活虚拟环境后；或 .venv/bin/python -m pytest tests/ -q
```

全部不依赖真实 LLM/网络（mock 或纯逻辑）；浏览器/ffmpeg 相关用例在缺环境时自动 skip。

## License

MIT
