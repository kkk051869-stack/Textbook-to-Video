# LLM 动画页面生成 Prompt 模板 v2

> 用于让 LLM 生成教学动画 HTML 页面
> 基于自写 SlideController + Canvas 粒子 + SVG 噪点 + .anim 延迟系统
> 零外部依赖，单文件 HTML

---

## Prompt 模板

```
生成一个中小学 AI 教育教学动画页面。

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
JS 中实现 80 个彩色粒子 + 连线效果。

### 5. SVG 噪点纹理
在 CSS 中通过 `body::before` 叠加 SVG feTurbulence 噪点纹理，
opacity: 0.03，mix-blend-mode: overlay。

## 视觉风格（亮色主题，不要暗色/黑色）
- **白底/浅色背景**：主背景 #f0f4ff，渐变到 #f5f3ff
- 文字颜色：#1e293b（深灰），次要文字 #64748b
- 配色方案：
  - 主色 #4361ee（蓝）
  - 强调色 #f97316（橙）
  - 辅助色 #8b5cf6（紫）
  - 成功色 #22c55e（绿）
  - 金色 #f59e0b
- 字体：Microsoft YaHei / PingFang SC，标题 48px+，正文 24px+
- 多层 radial-gradient 背景（至少 2 个渐变叠加）
- 图文并茂，减少纯文字页面，每页有图形化元素
- 适合录制视频（文字大、对比度高、动画流畅）

## 动画要求
1. 每页切换时元素依次出现（通过 .d1~.d12 控制顺序）
2. 使用 CSS keyframe 动画：
   - floatUp：标题和强调元素轻微浮动
   - pulseGlow：重要节点发光脉冲
   - dashFlow：虚线流动效果（stroke-dashoffset 动画）
   - drawLine：SVG 路径逐步绘制
   - barGrow：进度条从 0 增长
3. 数据流动效果使用 CSS 动画（虚线流动、粒子移动等）
4. 关键图形使用 SVG 内联绘制
5. 复杂数据流动使用 Canvas requestAnimationFrame

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
- 代码量 800-1500 行
- 不要省略任何代码，不要用 "..." 占位
- 所有中文内容直接写死在代码中
- 每个页面必须有独特的图形/动画元素，不要纯文字页
```

---

## 使用说明

1. 将 `{topic_title}`、`{topic_description}`、`{scenes_description}` 替换为实际内容
2. `scenes_description` 按页描述，每页包含：标题、要点、需要什么图形/动画
3. 生成后保存到 `output/{topic-slug}.html`，在浏览器中验证
4. 验证清单：
   - [ ] 每个页面高度不超过 1080px
   - [ ] 所有 .anim 元素在 slide 切换时依次入场
   - [ ] Canvas 粒子背景正常显示
   - [ ] SVG 噪点纹理可见（opacity 0.03）
   - [ ] 无外部依赖，断网也能运行
