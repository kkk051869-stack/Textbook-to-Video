# PoC 流程文档：从教材文本到教学视频

> **归档说明**（2026-05-18）：本文档记录 PoC 阶段的操作流程。
> 部分路径已变更，使用时注意：
> - `record.py` → `src/textbook2video/pipeline/recorder.py`（也可用 `t2v record` 命令）
> - `src/llm/prompts/animation_direct.md` → `src/textbook2video/llm/prompts/animation_direct.md`
> - `PROJECT_PLAN.md`（根目录）→ `docs/PROJECT_PLAN.md`
> - `libs/` 下的第三方库（Reveal.js、Animate.css、Chart.js）已被新方案替代（零外部依赖）
> - 新方案用自写 SlideController + `.anim` 系统，不再使用 Reveal.js
>
> 踩坑记录中的教训仍然有效。

> 记录 Sprint 1 PoC 的完整流程、踩坑记录和可复用的操作手册
>
> 日期：2026-05-18

---

## 一、PoC 目标

验证核心 Pipeline 可行性：**LLM 能否生成像样的 AI 教育动画页面，Playwright 能否录制为视频。**

### 选题

教材：《义务教育信息科技教学指南 人工智能与智慧社会 人工智能专册》第 4 课「人工智能的技术基础」

选择理由：
- 视觉化程度高（三要素关系、图表、进度条、神经网络）
- 概念层次清晰（数据→算力→算法，逐层递进）
- 涉及多种动画类型（粒子、SVG、Chart.js、进度条）

### 验收标准

| 指标 | 目标 | 结果 |
|------|------|------|
| LLM 生成 6 页动画 HTML | 可在浏览器正常显示 | ✅ 6 页，reveal.js 翻页正常 |
| Playwright 录制为 MP4 | 1080p, 30fps, 覆盖全部 6 页 | ✅ 894KB, 37s, 1920×1080 |
| 录制命令一键完成 | 单条命令产出视频 | ✅ `python record.py ... lesson4.mp4 36` |

---

## 二、环境配置

### Conda 环境

```bash
# 创建环境
conda create -p E:\Conda_Env\textbook2video python=3.11 -y

# 安装 ffmpeg（通过 conda-forge）
conda run -p E:\Conda_Env\textbook2video conda install -c conda-forge ffmpeg -y

# 安装 Python 依赖
conda run -p E:\Conda_Env\textbook2video pip install playwright edge-tts pydantic click litellm PyMuPDF -i https://pypi.tuna.tsinghua.edu.cn/simple

# Playwright 浏览器：复用系统 Edge（不需要额外下载）
# record.py 中使用 channel="msedge" 替代 Playwright 自带 chromium
```

### 验证安装

```bash
# 验证 ffmpeg
E:\Conda_Env\textbook2video\Library\bin\ffmpeg.exe -version

# 验证 Python 包
conda run -p E:\Conda_Env\textbook2video python -c "import playwright, edge_tts, fitz; print('OK')"

# 验证 Playwright + Edge
conda run -p E:\Conda_Env\textbook2video python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, channel='msedge')
    b.close()
    print('Playwright + Edge OK')
"
```

---

## 三、操作流程

### Step 1：提取教材内容

```bash
# 从 PDF 提取指定课程文本
python -c "
import fitz, sys
sys.stdout.reconfigure(encoding='utf-8')
doc = fitz.open('义务教育信息科技...专册.pdf')
for i in range(28, 34):  # 第4课页码范围
    print(doc[i].get_text())
"
```

产出：课程知识点文本。

### Step 2：生成动画 HTML

两种方式：

#### 方式 A：用 Prompt 模板手动调用 LLM

```bash
# Prompt 模板位置
src/llm/prompts/animation_direct.md

# 将模板中的 {topic_title}, {scenes_description} 替换为实际内容
# 粘贴到 Claude/GPT/GLM 对话中
# 复制生成的 HTML 保存到 output/
```

#### 方式 B：直接编写（本次 PoC 使用的方式）

根据知识点拆分为 6 个场景，直接编写 HTML。使用以下库：

| 库 | 路径 | 用途 |
|----|------|------|
| reveal.js | `libs/reveal.js/` | PPT 翻页框架 |
| Animate.css | `libs/animate.css/` | 入场动画 |
| Chart.js | `libs/chart.js/` | 图表（柱状图、折线图） |

**注意**：HTML 文件放在 `output/` 子目录时，库文件路径需用 `../libs/` 前缀。

产出：`output/lesson4-tech-foundations.html`

### Step 3：浏览器验证

```bash
# 启动本地 HTTP 服务器（从项目根目录）
python -m http.server 8765 --bind 127.0.0.1

# 浏览器打开
start http://127.0.0.1:8765/output/lesson4-tech-foundations.html
```

检查项：
- [ ] 6 页全部可正常翻页
- [ ] 粒子背景显示
- [ ] Chart.js 图表渲染
- [ ] SVG 动画（三角形流动线、神经网络信号）
- [ ] 控制台无 JS 错误（favicon 404 可忽略）

### Step 4：录制视频

```bash
# 基本命令
conda run -p E:\Conda_Env\textbook2video python record.py <input.html> <output.mp4> [duration_seconds]

# 实际命令
conda run -p E:\Conda_Env\textbook2video python record.py output/lesson4-tech-foundations.html output/lesson4.mp4 36
```

录制流程：
1. Playwright 启动 Edge（headless 模式）
2. 打开 HTML 文件（file:// 协议）
3. JS 注入 Reveal.js 自动翻页配置
4. 等待指定时长
5. 保存 WebM → ffmpeg 转 MP4（H.264）

产出：`output/lesson4-v2.mp4`（894KB, 37s, 1080p）

---

## 四、踩坑记录

### 坑 1：Chart.js canvas 无限撑高 ⚠️ 严重

**现象**：slide 3 的 Chart.js canvas 被渲染为 928×30,148px，整个 slide 高度膨胀到 119,345px。

**根因**：`maintainAspectRatio: false` + 容器无高度约束 → canvas 尝试填满父容器 → 正反馈循环。

**修复**：
```css
.chart-box { height: 280px; overflow: hidden; }
.chart-box canvas { max-height: 200px; }
```
```javascript
new Chart(ctx, { options: { maintainAspectRatio: true, aspectRatio: 4 } });
```

**预防**：Prompt 模板加入规则——所有 Chart.js 必须设置 `maintainAspectRatio: true` 和显式容器高度。

---

### 坑 2：Reveal.js autoSlide 不覆盖全部页面 ⚠️ 严重

**现象**：录制 12 秒视频只展示了前 1-2 页。

**根因**：Reveal.js 的 `autoSlide` 把每个 `fragment`（逐步出现的元素）当作独立步骤。按页数计算间隔不够。

**修复**：录制脚本先统计 slides + fragments 总步数：
```javascript
let totalSteps = 0;
slides.forEach(slide => {
    totalSteps += slide.querySelectorAll('.fragment').length + 1;
});
const interval = totalDuration / totalSteps;
```

---

### 坑 3：库文件相对路径 ⚠️ 中等

**现象**：HTML 在 `output/` 目录，引用 `libs/xxx` 实际指向 `output/libs/xxx`（不存在）。

**修复**：HTML 中使用 `../libs/` 前缀。

**长期方案**：要么 HTML 始终放根目录，要么 Prompt 模板明确指定输出位置对应的路径前缀。

---

### 坑 4：Playwright video.save_as 时序 ⚠️ 中等

**现象**：`video.save_as()` 报错 "Target page, context or browser has been closed"。

**修复**：context 关闭前用 `page.video.path()` 获取临时路径，关闭后用 `shutil.move` 移动文件。

---

### 坑 5：Playwright chromium 下载失败 ⚠️ 中等

**现象**：`playwright install chromium` 超时，npmmirror 镜像返回 404。

**修复**：使用系统 Edge 浏览器 `channel="msedge"` 替代 Playwright 自带 chromium。

---

## 五、产出物清单

```
Textbook-to-Video/
├── output/
│   ├── lesson4-tech-foundations.html   # 动画 HTML（6 页）
│   ├── lesson4-v2.mp4                  # 最终视频（894KB, 37s, 1080p）
│   ├── slide1-title.png                # 第1页截图
│   ├── slide3-fixed.png                # 修复后第3页截图
│   └── ...
├── record.py                           # Playwright 录制脚本
├── src/llm/prompts/
│   └── animation_direct.md             # LLM 动画生成 Prompt 模板
└── PROJECT_PLAN.md                     # 项目计划（含 PoC 踩坑记录）
```

---

## 六、可复用命令速查

```bash
# 激活环境（PowerShell）
conda activate E:\Conda_Env\textbook2video

# 启动本地服务器（从项目根目录）
python -m http.server 8765 --bind 127.0.0.1

# 录制视频
python record.py output/xxx.html output/xxx.mp4 36

# 从 PDF 提取文本
python -c "import fitz,sys; sys.stdout.reconfigure(encoding='utf-8'); doc=fitz.open('file.pdf'); [print(doc[i].get_text()) for i in range(start,end)]"
```
