# LLM 动画页面生成 Prompt 模板 v3

> 用于让 LLM 生成教学动画 HTML 页面
> 基于自写 SlideController + Canvas 粒子 + SVG 噪点 + .anim 延迟系统
> 零外部依赖，单文件 HTML
> v3: 卡通趣味教育风格 + 弹性动画

---

## Prompt 模板

```
生成一个中小学 AI 教育教学动画页面，卡通趣味教育风格。

## ⚠️ 输出格式（最重要）
只输出纯 HTML 代码。不要在开头或结尾添加任何说明文字、markdown 代码块标记（```html）或注释。
直接以 <!DOCTYPE html> 开头，以 </html> 结尾。

## 主题
{topic_title}
{topic_description}

## 教学内容（按页面顺序）
{scenes_description}

## 技术要求（严格遵守）

### 1. 单文件 HTML
所有 CSS、JS 内联在一个 .html 文件中，**零外部依赖**。
不使用任何 CDN 或本地库引用。

### 2. Slide 系统（自写，不用 Reveal.js）
使用自写 SlideController，HTML 结构如下：
```html
<canvas id="particleCanvas"></canvas>
<div class="slide-container">
  <div class="slide active"><!-- 第1页 --></div>
  <div class="slide"><!-- 第2页 --></div>
  ...
</div>
```

**⚠️ 不要添加任何可见的导航控件（按钮、页码指示器、箭头等）。**
这个页面用于自动录制视频，所有 slide 切换由 SlideController API 驱动。
仅保留键盘事件（左右方向键）用于本地调试，不需要任何可见 UI。

### 3. 动画触发（.anim 系统，不用 Animate.css）
- 每个需要入场动画的元素添加 `.anim` + 方向类 + 延迟类
- 方向类：`.anim-up`（从下上来）、`.anim-down`、`.anim-left`、`.anim-right`、`.anim-scale`
- 延迟类：`.d1`（0.2s）到 `.d12`（2.4s），间隔 0.2s
- Slide 切换时自动依次触发 `.show`
```html
<div class="anim anim-up d1">第一个出现</div>
<div class="anim anim-left d3">第三个出现</div>
```

### 4. Canvas 粒子背景
在 `<body>` 开头放 `<canvas id="particleCanvas"></canvas>`，
JS 中实现 80 个彩色粒子 + 连线效果。粒子颜色使用糖果色（粉、蓝、紫、黄、绿）。

### 5. SVG 噪点纹理
在 CSS 中通过 `body::before` 叠加 SVG feTurbulence 噪点纹理，
opacity: 0.03，mix-blend-mode: overlay。

## 🎨 视觉风格：卡通趣味教育风

### 整体感觉
像儿童教育 app 的动画页面，不是学术 PPT。色彩明快、图形圆润、动画有弹性和趣味性。

### 配色（糖果色系）
- 背景：#fef9f2（暖白色纯色背景），**不要使用渐变背景，使用纯色**
- 主色：#6c5ce7（活力紫）
- 强调色：#fd79a8（粉红）、#00cec9（青绿）
- 辅助色：#fdcb6e（金黄）、#e17055（珊瑚橙）
- 成功色：#00b894（薄荷绿）
- 文字：#2d3436（深炭灰），次要文字 #636e72

### 圆润设计
- 所有卡片、按钮、容器：border-radius: 20px~30px（大圆角）
- 卡片阴影：多层 box-shadow 营造立体感（不要扁平）
- 图标和图形：优先使用圆形、圆角矩形，避免尖锐边角

### 视觉元素
- 适当使用 emoji 作为视觉点缀（🤖🧠💡📊🎯✨🚀⭐🎉🔬）
- 关键概念用**彩色对话气泡**或**贴纸卡片**展示（带锯齿边缘或圆角气泡）
- 标题文字加 text-shadow 多层描边，增加立体卡通感
- 每页至少一个"标志性大图形"：用 CSS/SVG 画的机器人、大脑、火箭、灯泡、放大镜等
- 装饰元素：漂浮的小星星 ✨、圆点、波浪线

### 字体与排版
- 标题：48px+，font-weight: 800，加 text-shadow
- 正文：24px+，行高 1.8
- 字体：Microsoft YaHei / PingFang SC

### 背景
- **纯色背景**（#fef9f2），不要渐变，不要 radial-gradient
- 可在局部元素上用渐变点缀（卡片的渐变边框、按钮渐变等），但 body 背景必须是纯色

## 🎬 动画风格：弹性 + 夸张

### 弹性入场（关键！）
所有 .anim 入场必须使用弹性过冲缓动，不要平滑的 ease-out：
```css
.anim { transition-timing-function: cubic-bezier(0.68, -0.55, 0.265, 1.55); }
```
- 入场缩放：从 scale(0.3) 弹到 scale(1.08) 再回 scale(1)
- 加微小旋转：rotate(-8deg) → rotate(0)，增加活泼感
- 持续时间：0.6s~0.8s（比普通动画稍长，有回弹余韵）

### CSS keyframe 动画（必须全部包含）
- bounceIn：从 0 弹到 120% 再回 100%（标题、图标入场）
- pulseGlow：发光脉冲（重要节点闪烁吸引注意）
- floatUp：轻微上下浮动（装饰元素）
- dashFlow：虚线流动（流程连线）
- drawLine：SVG 路径逐步绘制
- barGrow：柱状图/进度条弹跳增长
- wiggle：左右小幅度摇摆（强调时触发）
- sparkle：闪烁放大缩小（关键数据出现时）
- rubberBand：拉伸变形回弹（错误或惊讶时）

### 动画密度
- 每个slide至少 8-12 个 .anim 元素（密集的动画比稀疏的好看）
- 即使是纯文字也要有入场动画
- 数据图表的增长动画要明显、夸张

## SlideController API
```javascript
window.SlideController = {
    go: function(index) {},   // 跳转到第 index 页（0-based）
    next: function() {},      // 下一页
    prev: function() {},      // 上一页
    current: function() {},   // 返回当前页码
    total: function() {},     // 返回总页数
};
```

## 输出要求
- 完整的单文件 HTML，可直接在浏览器中打开运行
- 代码量 1200-1800 行（内容要丰富）
- 不要省略任何代码，不要用 "..." 占位
- 所有中文内容直接写死在代码中
- 每个页面必须有独特的标志性图形/动画元素，严禁纯文字页
- 代码中的 CSS 注释用中文标注每个区块的作用
```

---

## 使用说明

1. 将 `{topic_title}`、`{topic_description}`、`{scenes_description}` 替换为实际内容
2. `scenes_description` 按页描述，每页包含：标题、要点、需要什么图形/动画
3. 生成后保存到 `output/{topic-slug}.html`，在浏览器中验证
4. 验证清单：
   - [ ] 输出是纯 HTML（无 markdown 标记或说明文字）
   - [ ] 每个页面高度不超过 1080px
   - [ ] 所有 .anim 元素在 slide 切换时依次入场（弹性动画）
   - [ ] 无可见导航按钮/页码指示器（纯内容页面）
   - [ ] body 背景为纯色（非渐变）
   - [ ] Canvas 粒子背景正常显示（糖果色）
   - [ ] SVG 噪点纹理可见（opacity 0.03）
   - [ ] 卡通风格：大圆角、emoji、彩色气泡
   - [ ] 无外部依赖，断网也能运行
