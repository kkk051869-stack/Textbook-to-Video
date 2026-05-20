# LLM Slide 内容生成 Prompt 模板 v4

> 用于分批生成 slide 内容（仅 slide div，不含 CSS/JS/HTML 框架）
> Pipeline 会预构建 CSS 框架和 JS，LLM 只需要生成每页 slide 的 HTML 内容
> v4: slide-content-only 模式 + CSS 类名参考 + 组件注入

---

## Prompt 模板

```
生成以下教学页面的 HTML 内容（仅 slide div，不含 CSS 框架/JS/head/body）。

## ⚠️ 输出格式（最重要）
只输出 <div class="slide">...</div> 块，每页一个 slide div。
第一页的 slide 加上 class="slide active"，其余只有 class="slide"。
不要输出 <style>、<script>、<!DOCTYPE>、<html>、<head>、<body> 等标签。
不要在开头或结尾添加任何说明文字或 markdown 代码块标记。

## 可用 CSS 类（框架已提供，直接使用）

### 布局
- `.slide` — 全屏幻灯片（position: absolute, 100vw×100vh, flex居中, padding: 60px 80px）
- `.content-card` — 圆角卡片容器（border-radius: 24px, 白色背景, 多层阴影, padding: 40px）
- `.two-col` — 两列布局（flex, gap: 40px, 居中对齐）
- `.three-col` — 三列布局（flex, gap: 30px）

### 文字
- 直接用 HTML 标签 + inline style 控制大小
- 标题建议: `<h2 style="font-size:48px;font-weight:800;">标题</h2>`
- 副标题建议: `<h3 style="font-size:32px;font-weight:600;color:var(--text-dim);">副标题</h3>`
- 正文建议: `<p style="font-size:24px;line-height:1.8;">内容</p>`

### 组件
- `.icon-card` — 图标卡片（flex column居中, 内部用 `.emoji-circle` 放大emoji, `.card-label` 文字标签）
- `.flow-step` — 流程步骤（flex row, 内部用 `.step-number` 做编号圆圈, `.step-content` 步骤描述）
- `.chart-container` — 图表容器（居中, 白色背景, 圆角, 内部放 SVG）
- `.comparison-panel` — 对比面板（flex, 内部 `.panel-left` `.panel-right` `.vs-badge`）
- `.activity-step` — 活动步骤（flex row, 内部 `.step-num` 做编号圆圈）
- `.bubble` — 对话气泡（圆角, 渐变背景, 三角箭头）
- `.badge` — 标签徽章（inline, 小圆角, 配色用 `.badge.primary` `.badge.accent` `.badge.success` `.badge.secondary`）
- `.highlight-box` — 高亮框（左侧彩色边条, 浅色背景）

### 动画（.anim 系统）
- 每个需要入场动画的元素添加 `.anim` + 方向类 + 延迟类
- 方向类: `.anim-up`（从下上来）、`.anim-down`、`.anim-left`、`.anim-right`、`.anim-scale`
- 延迟类: `.d1`（0.2s）到 `.d12`（2.4s），间隔 0.2s
- 示例: `<div class="anim anim-up d1">第一个出现</div>`
- ⚠️ 不需要写 JavaScript 触发动画，SlideController 会自动管理 `.show` 类
- ⚠️ **绝对不要在 SVG 内部元素（`<g>`、`<circle>`、`<rect>` 等）上加 `.anim` 类！** CSS transform 会覆盖 SVG 的 `transform` 属性，导致元素位置错乱甚至叠在一起。`.anim` 只能加在 HTML `<div>` 等容器元素上，SVG 的动画用 `<animate>` / `<animateTransform>` 实现

### Keyframe 动画（可直接用 animation 属性）
- `bounceIn` — 弹跳入场（scale 0→1.2→1）
- `pulseGlow` — 发光脉冲
- `floatUp` — 轻微上下浮动
- `dashFlow` — 虚线流动
- `drawLine` — SVG 路径逐步绘制
- `barGrow` — 柱状图增长
- `wiggle` — 左右摇摆
- `sparkle` — 闪烁
- `rubberBand` — 橡皮筋拉伸回弹

### CSS 变量（配色）
- `var(--primary)` = #4361ee（蓝）
- `var(--accent)` = #f97316（橙）
- `var(--secondary)` = #8b5cf6（紫）
- `var(--success)` = #22c55e（绿）
- `var(--gold)` = #f59e0b（金）
- `var(--text)` = #1e293b（深灰）
- `var(--text-dim)` = #64748b（浅灰）

## 主题
{LESSON_TITLE}
{LESSON_DESCRIPTION}

## 页面内容（按顺序生成）
{SCENES_DESCRIPTION}

## 组件参考代码（如有，参考此代码的结构和样式）
{COMPONENT_CODE}

## 🎨 视觉风格：卡通趣味教育风

### 整体感觉
像儿童教育 app 的动画页面。色彩明快、图形圆润、动画有弹性。

### 配色
- 卡通糖果色系（紫 #6c5ce7、粉 #fd79a8、青 #00cec9、金 #fdcb6e、珊瑚 #e17055、薄荷 #00b894）
- 标题文字加 text-shadow 多层描边增加立体卡通感
- 适当使用 emoji 作为视觉点缀（🤖🧠💡📊🎯✨🚀⭐🎉🔬）

### 圆润设计
- 所有卡片容器 border-radius: 20px~30px
- 多层 box-shadow 营造立体感
- 图形优先圆形和圆角矩形

### 弹性动画
- 入场使用弹性过冲缓动: cubic-bezier(0.68, -0.55, 0.265, 1.55)
- 持续时间 0.6s~0.8s
- 每页至少 8-12 个 .anim 元素

## 约束
- 使用上面列出的 CSS 类，不要自己发明新的 CSS 类名
- 如果需要自定义样式，用 inline style 属性
- 不要使用外部图片 URL
- 代码量要丰富，不要省略任何内容
- 不要使用 "..." 占位
- **每个 slide 的所有内容必须包裹在 `.content-card` 容器内**，不能有内容直接放在 slide 层
- **每页至少 8 个 `.anim` 元素**，保证入场动画丰富度

## ⚠️ 背景色要求（强制！）
- **所有 slide 背景必须使用纯色 `#fef9f2`**（温暖米白色）
- **绝对禁止使用 linear-gradient、radial-gradient 或任何渐变背景**
- 不要在 slide 上设置 `style="background: ..."`，让框架的默认背景生效
- 如果想要区分页面，可以通过 `.content-card` 的边框颜色或装饰元素来区分，不要改背景色

## ⚠️ 布局防漂移（极其重要！）
- 每页所有内容的总高度不得超过 **850px**（视口高度 1080px - padding 120px - 卡片 padding 80px ≈ 880px，留安全余量）
- **不要使用固定像素高度的容器**（如 `height: 380px`），改用 `max-height` 或百分比
- 使用 `display: flex` + `flex-direction: column` + `gap` 控制间距，不要用 `margin-bottom` 累加
- SVG 图形的高度控制在 **280px 以内**，用 `viewBox` 控制比例而非放大实际尺寸
- 如果一页内容太多放不下，优先缩小字体和间距，而非撑出容器
- `.content-card` 已设置 `max-height: calc(100vh - 120px)` + `overflow: hidden`，超出部分会被截断
- 所有元素使用 `box-sizing: border-box` 确保 padding 不会撑破布局

## ⚠️ SVG 图形要求（最重要！）
- **每页必须用 <svg> 画至少一个标志性的卡通图形**，例如：机器人、大脑、齿轮、灯泡、火箭、眼睛、电脑、杠铃等
- **禁止用纯 emoji 代替图形！** emoji 只能做点缀，不能做主体视觉
- 每个 SVG 至少包含 10+ 个子标签（circle/path/line/rect/ellipse/polygon/animateTransform 等）
- SVG 必须有动画效果（旋转齿轮、流动信号、脉冲发光、浮动装饰等），使用 <animate> 或 <animateTransform>
- SVG 尺寸要大（width 300-500px），视觉占比要突出，不能是角落里的小图标
- 配色使用 CSS 变量（var(--primary)、var(--accent) 等）或糖果色系（#6c5ce7 #fd79a8 #00cec9 #fdcb6e #e17055）
- 参考示例风格：
  - 大脑图：圆形轮廓 + 内部齿轮旋转 + 电路线条流动 + 信号点闪烁
  - 机器人：圆形头部 + 矩形身体 + 弯曲手臂 + 眼睛闪烁
  - 流程图：圆角矩形步骤框 + 虚线箭头流动 + 节点脉冲发光
  - 对比图：左右两个大面板 + 进度条增长 + VS 徽章发光
```

---

## 使用说明

1. 将 `{LESSON_TITLE}`、`{LESSON_DESCRIPTION}`、`{SCENES_DESCRIPTION}`、`{COMPONENT_CODE}` 替换为实际内容
2. Pipeline 自动处理 CSS 框架注入和 JS 注入
3. 验证清单：
   - [ ] 输出只包含 <div class="slide"> 块（无 HTML 框架代码）
   - [ ] 每个 slide 使用了框架 CSS 类（content-card, anim, d1-d12 等）
   - [ ] 每页至少 8 个 .anim 元素
   - [ ] **每页至少 1 个 <svg> 图形，包含 10+ 个 SVG 子标签**
   - [ ] **没有用纯 emoji 代替图形**
   - [ ] 无 <style>、<script>、<!DOCTYPE> 标签
