# LLM Slide 内容生成 Prompt 模板 Core

> 用于分批生成 slide 内容。视觉风格由主题 prompt 注入，本模板只保留通用结构、输出和布局约束。

---

## Prompt 模板

```
生成以下教学页面的 HTML 内容（仅 slide div，不含 CSS 框架/JS/head/body）。

## 输出格式（强制）
- 只输出 `<div class="slide">...</div>` 块，每页一个 slide div。
- 第一页加 `class="slide active"`，其余只用 `class="slide"`。
- 不要输出 markdown、解释文字、`<style>`、`<script>`、`<!DOCTYPE>`、`<html>`、`<head>`、`<body>`。
- 不要增删页面；输出顺序必须与页面内容一致。
- 可见文字只能来自每页 `内容` 中列出的 elements；`旁白`、`演讲稿`、`非可见参考旁白` 只用于语义理解和音频时长，不得作为任何可见 HTML 文本输出。

## 可用框架类
- 布局：`.slide`、`.content-card`、`.two-col`、`.three-col`。
- 组件：`.icon-card`、`.flow-step`、`.chart-container`、`.comparison-panel`、`.activity-step`、`.bubble`、`.badge`、`.highlight-box`。
- 文字可直接用 HTML 标签和 inline style 控制字号、字重、行高、颜色。
- 配色优先使用 CSS 变量：`var(--primary)`、`var(--accent)`、`var(--secondary)`、`var(--success)`、`var(--gold)`、`var(--text)`、`var(--text-dim)`、`var(--border)`。

## 动画系统
- 需要入场的 HTML 容器元素添加 `.anim` + 动画类 + 延迟类。
- 入场动画类（需 `.anim` 基类 + `.dN` 延迟类）：
  - 方向：`.anim-up`（标题/文字）、`.anim-down`、`.anim-left`、`.anim-right`
  - 弹性：`.anim-scale`（通用缩放）、`.anim-icon`（图标/emoji）、`.anim-card`（卡片/面板）
  - 特效：`.anim-anticipate`（预备+弹入）、`.anim-anticipate-up`（标题专用）、`.anim-number`（数字/统计值）、`.anim-bar`（柱状图）、`.anim-emphasis`（强调闪现）
- 持续微动类（不需要 `.show`，始终播放，给装饰元素增加呼吸感）：
  - `.anim-float`（上下浮动）、`.anim-sparkle`（闪烁缩放）、`.anim-wiggle`（摇摆）
  - `.anim-glow`（光晕呼吸）、`.anim-sway`（轻柔摇摆）、`.anim-pulse`（脉搏缩放）
- 装饰延迟：`.deco-follow`（比主元素慢 0.3s，用于辅助装饰）
- 延迟类：`.d1` 到 `.d12`，间隔 0.2s。
- 使用原则：
  - 标题用 `.anim-up` 或 `.anim-anticipate-up`
  - 图标/emoji 用 `.anim-icon`
  - 卡片/面板 用 `.anim-card`
  - 数字/统计 用 `.anim-number`
  - 重点强调 用 `.anim-emphasis`
  - 每页应有 2-3 个装饰元素使用 `.anim-float` 或 `.anim-sparkle`，保持页面呼吸感
  - 延迟类要有层次变化（不要所有元素都用 d1-d3），让入场有节奏感
- 示例：`<div class="anim anim-card d3">内容</div>`
- SlideController 会自动管理 `.show` 类，不要写 JavaScript 触发动画。
- 绝对不要在 SVG 内部元素（`<g>`、`<circle>`、`<rect>`、`<path>` 等）上加 `.anim`；SVG 内部动画用 `<animate>` 或 `<animateTransform>`。

## 分步揭示
- 希望元素随叙述逐步出现时，加 `data-step="N"`（N=1,2,3...）。
- 不加 `data-step` 或 `data-step="0"`：页面出现时立即入场。
- `data-step="1"`：在第一段叙述结束时入场。
- `data-step="2"`：在第二段叙述结束时入场。
- 同一 step 的多个元素同时出现（各自保留自己的 `.anim` + delay 类）。
- 每页最多 3-4 个 step，不要过度拆分。
- 示例：`<div class="anim anim-scale d1" data-step="1">第二批内容</div>`

## 时间轴元素标记
- 需要精确时间控制的元素加 `data-anim-id="eN"`，对应 storyboard 中 element 的 id。
- 带 `data-anim-id` 的元素由 controller 在精确时刻触发，不需要 `data-step`。
- 示例：`<div class="anim anim-icon d2" data-anim-id="e3">图标内容</div>`

## 布局防漂移
- 每页内容必须保持在 1920x1080 视口内，标题和主体尽量保留 48px 安全边距。
- 顶层内容容器使用 `box-sizing:border-box`，优先用 flex/grid、`gap` 和 `max-height` 控制空间。
- 不要在 `.slide` 上写会覆盖框架定位的 inline style，例如 `position`、`height:100vh`、`top`、`left`。
- 子容器不要使用 `height:100vh`；需要全屏感时用 `height:100%`、`min-height:0`、`flex:1`、`max-height`。
- SVG 或图表区域用 `viewBox` 控制比例，避免固定大像素高度撑破页面。
- 内容过多时优先缩小字体、压缩 gap、减少装饰尺寸，不要删减教学含义或旁白对应内容。

## 课程
{LESSON_TITLE}
{LESSON_DESCRIPTION}

## 页面内容与非可见参考（按顺序生成）
{SCENES_DESCRIPTION}

## 组件摘要（如有）
{COMPONENT_GUIDANCE}

## 最终检查
- 每页只输出 slide div，且 slide 数量与页面内容一致。
- 使用主题和布局约束决定视觉风格，不要套用未要求的固定风格。
- 保留 `.anim` 入场效果，但不要给 SVG 内部元素加 `.anim`。
- 检查输出中没有把 `旁白`、`演讲稿` 或非可见参考内容渲染为可见文字。
- 不使用外部图片 URL，不使用 `...` 占位。
```
