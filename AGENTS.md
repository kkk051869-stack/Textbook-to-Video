# AGENTS.md

本文件为 Codex / AI 助手提供项目上下文。请在动手前通读"关键约定与陷阱"。

## 项目是什么

**Textbook-to-Video**：把教材（PDF / DOCX）全自动转成带动画 + 配音的教学视频。Python 包名 `textbook2video`，CLI 命令 `t2v`。

完整 pipeline：

```
教材(PDF/DOCX) → [解析] → [讲稿] → [storyboard JSON] → [TTS配音] → [动画HTML] → [录制] → MP4
                  parser   scriptwriter  storyboard      narrator    animate      record
```

"音频先行"：先用 TTS 拿到每段时长，再据此决定每页 slide 的展示时长。

## 常用命令

```bash
# 环境（首次）
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium      # 若系统无 Edge/Chrome；网络不稳时多试几次
# LLM 凭据写入项目根 .env（见下方"配置"），不要硬编码或打印密钥

# 测试（不依赖真实 LLM/网络，部分浏览器用例无浏览器时自动 skip）
.venv/bin/python -m pytest tests/ -q

# 跑前先自检环境（凭据/ffmpeg/浏览器/TTS；--ping 顺带测 LLM 连通）
.venv/bin/t2v doctor

# ★端到端一步出有声成片（教材 → MP4，内部 generate→animate→record→配音合成）
.venv/bin/t2v produce textbook.docx --chapter 3 --section 0 --theme dark-blue-academic --model ecnu-plus -o output/xxx
.venv/bin/t2v produce input.pdf --lesson 4 --theme dark-blue-academic --model ecnu-plus -o output/xxx   # PDF 路径
.venv/bin/t2v batch textbook.docx --sections "3:0,3:1,4:0" --model ecnu-plus    # 多课节批处理（单节失败不影响其余）

# —— 或分步（便于中途审阅/重做）——
.venv/bin/t2v generate-docx textbook.docx --chapter 3 --section 0 --model ecnu-plus --output output/xxx
.venv/bin/t2v generate input.pdf --lesson 4 --model ecnu-plus --output output/xxx   # PDF 走页码表
.venv/bin/t2v list-lessons <file>          # 先看可解析的章节/课
.venv/bin/t2v script textbook.docx --chapter 3 --section 0 --model ecnu-plus -o output/xxx   # 只出讲稿 *_script.txt
.venv/bin/t2v storyboard output/xxx/ch3_s0_script.txt --model ecnu-plus      # 讲稿满意、只重做画面大纲（--tts 顺带配音）
.venv/bin/t2v narrate output/xxx/ch3_s0_storyboard.json    # 改了 narration 后只重配音，回写 audio_duration_sec
.venv/bin/t2v validate output/xxx/ch3_s0_storyboard.json   # animate 前静态校验 JSON（element/字段/图片 src）

# storyboard JSON → 单文件 HTML
.venv/bin/t2v animate output/xxx/lesson_storyboard.json --theme dark-blue-academic --model ecnu-plus
#   --theme: bright | dark-blue-academic | 3b1b-math    --no-images: 跳过 AI 配图
#   --batch-size N  --repair N(布局修复轮数)            --browser msedge

# HTML → MP4（注意：record 只录画面、无声；要有声用 produce 或 record 后再 mux）
.venv/bin/t2v record animation.html out.mp4 --duration 35
.venv/bin/t2v mux out.mp4 output/xxx/ch3_s0_audio out_voiced.mp4   # 把分段配音合成进视频
```

## 架构

```
src/textbook2video/
├── cli.py                      # t2v 命令入口（produce/batch/script/storyboard/narrate/mux/validate/doctor + generate/generate-docx/list-lessons/animate/record）
├── animation_gen.py            # ★核心：storyboard JSON → 单文件 HTML（分批生成→提取→合并→布局QA→修复→校验）
├── template_renderer.py        # ★F5：把结构化 elements 确定性渲染成框架类 HTML（不靠 LLM 写样式）
├── css_hotfix.py               # 布局QA失败时的 0-token CSS 热修复（Playwright 改 DOM 后写回）
├── pipeline/
│   ├── parser.py               # PDF(LESSON_PAGE_RANGES 页码表) + DOCX(style 2/4/5) 解析 + 教材图提取
│   ├── docx_parser.py          # DOCX 另一套解析（按 Heading 样式），CLI generate 用
│   ├── scriptwriter.py         # 教材文本 → 讲稿分段（LLM）
│   ├── storyboard.py           # 讲稿 → 画面大纲 JSON（LLM），可引用教材原图
│   ├── narrator.py             # edge-tts 配音 + ffmpeg 取时长
│   ├── recorder.py             # HTML → MP4（Playwright + ffmpeg，★只录画面无声）
│   ├── compose.py              # 音画合成：分段音频拼接 + mux 到视频（补"成片无声"断点）
│   ├── orchestrator.py         # 生成编排：build_script/build_storyboard_* + 端到端 produce
│   ├── checks.py               # validate_storyboard 校验 + doctor 自检 + batch 课节解析
│   └── config.py               # 全局配置 + LLM 凭据选择（.env）
├── llm/
│   ├── client.py               # litellm 封装（OpenAI-compatible 网关）
│   ├── image_gen.py            # AI 配图（figurative/abstract 分类 + 生成）
│   └── prompts/*.md            # script / storyboard / slide_content_core / *_repair 模板
├── themes/*.json               # 主题（配色/字体/粒子/布局）+ __init__.py(theme_to_css_vars)
└── templates/                  # base.css(框架类+动画) / base-template.html(壳) / slide-controller.js / particle-canvas.js
scripts/check_layout.py         # Playwright 多视口布局几何自检（被 animate 调用）
docs/历史/分镜到HTML修复历史.md   # ★根因分析 + 修复历史（F1-F5/A/B/C），改 pipeline 前先读
```

## 配置（LLM）

`.env`（项目根，已 gitignore）：

```
ECNU_API_KEY=...                               # 华东师大大模型网关，勿打印/提交
ECNU_BASE_URL=https://chat.ecnu.edu.cn/open/api/v1
ECNU_DEFAULT_MODEL=ecnu-plus                    # 见陷阱②
```

也支持通用 `LLM_API_KEY`/`LLM_BASE_URL`（优先级更高）。所有 LLM 走 `llm/client.py` 的 litellm `openai/<model>`。

## 关键约定与陷阱（务必先读）

1. **animate 是"模板渲染优先 + LLM 兜底"**：每页先用 `template_renderer.render_slide` 确定性渲染；只有不支持的 visual_type（`network`/`tree`）或含不支持 element 的页才 fallback 到 LLM 生成。环境变量 `T2V_DISABLE_TEMPLATE_RENDERER=1` 可全关。改视觉效果优先改 `template_renderer.py` + `base.css`，而不是调 prompt。

2. **模型：`ecnu-max` 慢且偶发超时，默认用 `ecnu-plus`**。`ecnu-max`(DeepSeek) 生成长 HTML 约需 350s 且常超时崩溃；`ecnu-plus`(Qwen3.6-27B) 数秒返回、质量够用。命令统一加 `--model ecnu-plus`。

3. **timeout 必须靠禁用底层重试才精确**：`client.py` 已设 `num_retries=0` + `max_retries=0`。否则 OpenAI SDK 默认 `max_retries=2` 会把传入 timeout 放大约 3 倍（180s→~540s）。生成超时上限 `GENERATE_TIMEOUT`（默认 420s，可用 `T2V_GENERATE_TIMEOUT` 覆盖）。

4. **fullscreen 主题下 `.slide` 不居中**：`body[data-layout="fullscreen"] .slide` 是 `align-items:stretch; justify-content:flex-start`，且 `.content-card` 被改成撑满全屏的透明画布。渲染器/手写 slide 要自己用 `position:absolute;inset:0` + flex 居中，**不要把 `.content-card` 当普通小卡用**（会撑爆）。

5. **卡片背景用 `var(--card-bg)`，别硬编码 `white`**：否则深色主题下白底配浅色文字看不清。卡片色由各主题 json 的 `card_bg` 经 `theme_to_css_vars` 注入。

6. **教材原图链路**：storyboard 的 `image` 元素带 `src`（如 `fig1-1_xxx.png`）指向 JSON 同级 `images/` 目录。`animate` 阶段 `load_textbook_images` 读图 → base64 → 复用 `{{IMG_eN}}` 占位注入。`image_gen` 会跳过有 `src` 的元素（不 AI 重画）。

7. **slide 提取容错**：`_extract_slide_divs` 先用零开销栈匹配（快路径），div 开闭不平衡导致提取为空时回退到浏览器 DOM 解析（复用 msedge）。下游消费者全用浏览器 DOM，所以提取也要和它们一致。

8. **css_hotfix 序列化前必须复位 slide 运行时状态**：它用 `page.content()` 把运行时 DOM 写回，会固化 `active`/`transition-*`/`.anim.show`——复位为"只第 1 页 active"才不会打开时初始页错乱。

9. **prompt 模板有 4500 字符硬上限**（`test_animation_prompts.py` 守护）。`slide_content_core.md` 已接近上限，加内容前先想能否删。

10. **解析依赖教材特定结构**：PDF 走硬编码 `LESSON_PAGE_RANGES`（《人工智能与智慧社会》），DOCX `parser.py` 依赖样式 ID 2/4/5（《数字素养》）。**换教材通常要适配这些映射 + 图注正则 `图X-Y 标题`**。

11. **验证视觉别只靠截图**：`.anim` 入场带 `.dN`(animation-delay) 延迟，截图等待不够会误判"内容被切/缺失"。要么等足够久（d5≈1s + 动画时长），要么结合 DOM `getBoundingClientRect` 实测，并手动给目标 slide 加 `.active` + 其内 `.anim` 加 `.show`。

12. **大文件**：`textbook.docx`(68MB)、`output/`(产物，gitignore)、教材图均不宜随意提交；密钥永不入库。

## 测试

`tests/` 全部不依赖真实 LLM（mock 或纯逻辑）。浏览器相关用例（提取兜底、教材图）在无浏览器环境自动 skip。新增 pipeline 改动应配套测试，尤其提取/数量/渲染这类"面对脏 LLM 输出"的鲁棒性点（历史上这里是测试盲区）。

## 云端上传与版本管理

本地项目路径：

```text
D:\Code\vibe coding\Textbook-to-Video
```

云端使用 SSH alias：

```bash
ssh digital_book
```

每次进入云端 shell 后先加载环境：

```bash
source /ai/data/use_ai_env.sh
```

云端代码目录使用：

```text
/ai/data/repos/Textbook-to-Video
```

云端数据、输入教材、生成视频、音频、HTML、临时输出等不要放进 Git 仓库，统一放在：

```text
/ai/data/textbook-to-video
```

版本管理规则：

- 代码、文档、配置样例、测试、prompt、小模板走 Git。
- `.env`、密钥、生成视频/音频、`output/`、缓存、模型文件、大体积临时产物不要提交。
- 提交前先运行 `git status --short`，只加入本次任务相关文件。
- 当前默认分支是 `master`，远端是 `origin https://github.com/kkk051869-stack/Textbook-to-Video.git`。
- 本地推送后，云端用 `git pull --ff-only` 同步；不要在同一个云端 worktree 里并行让多个 agent 修改。

常用同步流程：

```powershell
git status --short
git add <files>
git commit -m "Describe change"
git push origin master
```

云端拉取：

```bash
ssh digital_book "source /ai/data/use_ai_env.sh && cd /ai/data/repos/Textbook-to-Video && git pull --ff-only"
```

仅数据或生成产物需要上传时用 `scp`，不要塞进 Git：

```powershell
scp <local-file> digital_book:/ai/data/textbook-to-video/
```

删除云端文件前必须先确认精确路径：

```bash
realpath <target>
du -sh <target>
```

不要递归删除这些路径，除非用户明确确认完整路径和意图：

```text
/ai/data
/ai/data/repos
/ai/data/textbook-to-video
/ai/data/models
/ai/data/model-cache
```
