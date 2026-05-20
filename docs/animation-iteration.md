# 动画生成迭代记录

> 记录 animation pipeline 的每次质量迭代：问题、修复、效果对比。
> 所有改动（prompt / CSS / JS / pipeline 逻辑）都必须在此留痕。

---

## 目录

- [迭代总览](#迭代总览)
- [v0.5 — Pipeline 初版](#v05--pipeline-初版)
- [v0.6 — SVG 强制 + 防漂移](#v06--svg-强制--防漂移)
- [v0.7 — 七项质量修复](#v07--七项质量修复)
- [待修复问题清单](#待修复问题清单)

---

## 迭代总览

| 版本 | 日期 | 主要改动 | 输出文件 | 体积 | SVGs | 效果评价 |
|------|------|----------|----------|------|------|----------|
| v0.5 | 2025-05 | Pipeline 分批生成 + 合并 | lesson4-pipeline.html | 80K | 17 | 有严重问题（见下） |
| v0.6 | 2025-05 | CSS overflow 约束 + prompt 防漂移 | 未单独生成 | - | - | 仅改 CSS/prompt |
| v0.7 | 2025-05 | 7 项质量修复（见下） | lesson4-pipeline-20260520_095414.html | 72K | 15 | 渐变清除、幽灵slide修复 |
| v0.7.1 | 2025-05 | 渐变正则修正 + 时间戳输出 | lesson4-pipeline-20260520_100759.html | 81K | 16 | 🎉 全部校验通过 |
| v0.7.2 | 2025-05 | SVG .anim 冲突修复 | lesson4-pipeline-20260520_101838.html | 81K | 15 | 反向传播流程图不再叠合 |
| 标杆 | 2025-05 | LLM 一次性自由生成 | lesson4-full-11pages.html | 50K | 8 | 视觉最佳（参考） |

---

## v0.5 — Pipeline 初版

### 生成配置

- 模型：`ecnu-plus`
- 批次大小：4（3 批生成 11 页）
- Prompt：`slide_content.md` v3（未加强制 SVG / 防漂移约束）
- CSS 框架：`base.css`（无 overflow 约束）

### 生成结果数据

| 指标 | 值 | 状态 |
|------|-----|------|
| 实际 slide 数 | 15（含 3 个幽灵 slide） | ❌ |
| SVG 总数 | 17 | ✅ |
| SVG 子标签 | ~200 | ✅ |
| `.anim` 元素 | 66 | ⚠️ 分布不均 |
| Keyframes | 12 | ✅ |
| 硬编码颜色 | 71 处 | ⚠️ 偏多 |
| Emoji | 23 个 | ✅ |
| 外部 URL | 仅 SVG namespace | ✅ |

### 发现的问题

#### 🔴 P0：JS 注释导致幽灵 Slide

**现象**：DOM 中检测到 15 个 `.slide` 元素，实际只有 12 页内容。

**原因**：`slide-controller.js` 顶部注释中包含 HTML 示例代码：

```javascript
 *   <div class="slide-container">
 *     <div class="slide active">...</div>
 *     <div class="slide">...</div>
```

`querySelectorAll(".slide")` 在整个 document 范围搜索，把注释文本中的 `class="slide"` 也匹配了。

**影响**：SlideController 的 `total` 返回错误值，最后一页无法正确导航；`go()` 函数可能操作到不存在的 slide。

**修复方案**：`merge_html()` 注入 JS 前清除多行注释中的 HTML 片段，或将 JS 注释中的 HTML 示例改为转义写法。

**状态**：待修复

---

#### 🔴 P0：所有 Slide 使用渐变背景（违反用户要求）

**现象**：11 个 slide 全部使用 `linear-gradient` 或 `radial-gradient`。

**用户要求**（原文）："背景全都使用纯色"、"纯色背景 #fef9f2"。

**原因**：Prompt 中未明确禁止渐变背景，LLM 默认倾向用渐变增加视觉效果。

**示例**：
```html
<!-- 实际输出 -->
<div class="slide active" style="background: linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%);">
<!-- 期望输出 -->
<div class="slide active" style="background: #fef9f2;">
```

**修复方案**：在 `slide_content.md` 约束部分加 "禁止使用 gradient 渐变背景，所有 slide 背景必须是纯色 #fef9f2"。

**状态**：待修复

---

#### 🔴 P1：2 页完全没有 SVG 图形

**现象**：Slide 4（小实验：猫狗识别）和 Slide 7（算力大比拼）没有任何 `<svg>` 元素。

**原因**：Prompt 要求"每页至少 1 个 SVG"，但 pipeline 校验只检查全局 SVG 总数 ≥ 8，未逐 slide 检查。LLM 对内容较少的页面跳过了 SVG。

**影响**：这两页视觉效果明显弱于其他页面，缺少卡通趣味感。

**修复方案**：`merge_html()` 中增加逐 slide 的 SVG 检查，0 SVG 的 slide 标记为质量不达标。

**状态**：待修复

---

#### 🟡 P1：固定像素高度容器导致漂移风险

**现象**：存在 3 处大型固定高度容器（380px、350px、400px）。

| Slide | 固定高度 | 内容 |
|-------|----------|------|
| 1 | `height: 380px` | SVG 插图容器 |
| 4 | `height: 350px` | 实验区域 |
| 6 | `height: 400px` | 对比面板 |
| 11 | `height: 400px` | 总结页卡片 |

**原因**：尽管 v0.6 prompt 已加入"禁止固定像素高度"约束，但 v0.5 生成时该约束尚未存在。

**修复方案**：`merge_html()` 中用正则自动将 `height: Npx`（N > 200）替换为 `max-height: Npx`，作为兜底。

**状态**：v0.6 prompt 层已修复，pipeline 代码层待加固

---

#### 🟡 P2：动画密度不均匀

**现象**：每页 `.anim` 元素数量从 3 到 13 不等。

| 范围 | Slide |
|------|-------|
| 3 个（不足） | 1, 5, 7, 8 |
| 4-7 个（一般） | 2, 3, 4, 6 |
| 9-13 个（良好） | 9, 10, 11 |

**目标**：每页 8-12 个。

**修复方案**：Prompt 中明确"每页至少 8 个 .anim 元素"，pipeline 校验新增逐 slide 检查。

**状态**：待修复

---

#### 🟡 P2：硬编码颜色过多

**现象**：71 处硬编码 hex 颜色 vs 151 处 CSS `var()` 引用，硬编码占比 32%。

**常见硬编码值**：`#6c5ce7`、`#fd79a8`、`#00cec9`、`#fdcb6e`、`#e17055`（糖果色系）。

**影响**：不一致的配色管理，后期改主题困难。

**修复方案**：在 base.css 的 CSS 变量中补充糖果色变量，prompt 中要求优先使用 CSS 变量。

**状态**：低优先级，暂不修复

---

#### 🟡 P2：Slide 11 缺少 content-card

**现象**：最后一页没有 `.content-card` 容器包裹，内容直接放在 `.slide` 内。

**影响**：布局风格不一致。

**修复方案**：Prompt 中强调"每个 slide 的内容必须放在 .content-card 内"。

**状态**：待修复

---

## v0.6 — SVG 强制 + 防漂移

### 改动内容

#### 1. CSS 层：overflow 硬约束（`base.css`）

**文件**：`src/textbook2video/templates/base.css`

**改动**：
- `.slide` 新增 `overflow: hidden`
- `.content-card` 新增 `max-height: calc(100vh - 120px)` + `max-width: calc(100vw - 160px)` + `overflow: hidden` + `box-sizing: border-box`

**目的**：无论 LLM 生成什么内容，CSS 层面兜底防溢出。

#### 2. Prompt 层：布局防漂移约束（`slide_content.md`）

**文件**：`src/textbook2video/llm/prompts/slide_content.md`

**改动**：新增"布局防漂移"章节：
- 每页内容总高度 ≤ 850px
- 禁止固定像素高度容器，改用 `max-height` / 百分比
- SVG 高度 ≤ 280px
- 优先 flex 布局控制间距
- 告知 `.content-card` 已有 overflow: hidden

**目的**：从源头引导 LLM 控制内容量。

### 效果

**状态**：待重新生成验证

---

## v0.7 — 七项质量修复

### 改动内容

#### 1. JS 注释幽灵 slide 修复（P0）

**文件**：`src/textbook2video/templates/slide-controller.js`

**改动**：将注释中的 HTML 示例代码从尖括号写法改为 CSS 选择器写法：

```diff
- *   <div class="slide-container">
- *     <div class="slide active">...</div>
- *     <div class="slide">...</div>
+ *   div.slide-container > div.slide.active + div.slide * N
```

**原因**：`querySelectorAll(".slide")` 会扫描整个 document 文本，包括 `<script>` 标签内的注释。注释中的 `class="slide"` 被误匹配为真实 DOM 节点。

#### 2. Prompt 强化纯色背景（P0）

**文件**：`src/textbook2video/llm/prompts/slide_content.md`

**改动**：新增"背景色要求（强制！）"章节：
- 所有 slide 背景必须使用纯色 `#fef9f2`
- 绝对禁止 `linear-gradient`、`radial-gradient`
- 不要在 slide 上设置 `style="background: ..."`
- 通过 `.content-card` 边框颜色或装饰元素区分页面

#### 3. Pipeline 兜底清理渐变背景（P0 防线 2）

**文件**：`src/textbook2video/animation_gen.py` → `merge_html()`

**改动**：新增正则兜底清理：
```python
slides_html = re.sub(r'style="background:\s*[^"]*linear-gradient[^"]*"', 'style=""', slides_html)
slides_html = re.sub(r'style="background:\s*[^"]*radial-gradient[^"]*"', 'style=""', slides_html)
```

**逻辑**：即使 prompt 说了 LLM 也可能不听，pipeline 层面兜底移除。

#### 4. Pipeline 兜底替换固定高度（P1）

**文件**：`src/textbook2video/animation_gen.py` → `merge_html()`

**改动**：
```python
slides_html = re.sub(r'height:\s*(\d{3,})px', r'max-height: \1px', slides_html)
```

**逻辑**：将所有 ≥100px 的固定 `height` 替换为 `max-height`，防止内容溢出但保留尺寸提示。

#### 5. Prompt 强调 content-card + anim 密度（P2）

**文件**：`src/textbook2video/llm/prompts/slide_content.md`

**改动**：约束部分新增：
- 每个 slide 的所有内容必须包裹在 `.content-card` 内
- 每页至少 8 个 `.anim` 元素

#### 6. 校验增强：逐 slide 质量检查（P1）

**文件**：`src/textbook2video/animation_gen.py` → `validate_output()`

**改动**：
- 新增"无渐变背景"全局检查
- 新增逐 slide 检查：SVG 数量、`.anim` 数量、是否有渐变背景
- 输出每页质量状态（✅ / ❌无SVG / ⚠️仅N个anim / ⚠️渐变背景）

### 效果

**状态**：待重新生成验证

---

## 待修复问题清单

按优先级排序，每次修复后在此更新状态。

| # | 优先级 | 问题 | 修复位置 | 状态 |
|---|--------|------|----------|------|
| 1 | P0 | JS 注释中的幽灵 slide | `slide-controller.js` 注释改写 | ✅ v0.7 已修复 |
| 2 | P0 | 渐变背景违反纯色要求 | `slide_content.md` + `merge_html()` 双重兜底 | ✅ v0.7 已修复 |
| 3 | P1 | 2 页无 SVG | `slide_content.md` prompt + `validate_output()` 逐页检查 | ✅ v0.7 已修复 |
| 4 | P1 | 固定高度容器 | `merge_html()` 正则兜底替换 | ✅ v0.7 已修复 |
| 5 | P2 | 动画密度不均 | `slide_content.md` prompt | ✅ v0.7 已修复 |
| 6 | P2 | 硬编码颜色过多 | `base.css` + `slide_content.md` | ❌ 低优先级 |
| 7 | P2 | Slide 缺少 content-card | `slide_content.md` prompt | ✅ v0.7 已修复 |

---

## 修改日志

| 日期 | 改动 | 涉及文件 | 备注 |
|------|------|----------|------|
| 2025-05 | CSS overflow 硬约束 | `base.css` | v0.6 |
| 2025-05 | Prompt 防漂移章节 | `slide_content.md` | v0.6 |
| 2025-05 | JS 注释幽灵 slide 修复 | `slide-controller.js` | v0.7 |
| 2025-05 | Prompt 纯色背景 + content-card + anim 密度 | `slide_content.md` | v0.7 |
| 2025-05 | merge_html() 兜底清理渐变 + 固定高度 | `animation_gen.py` | v0.7 |
| 2025-05 | validate_output() 逐 slide 质量检查 | `animation_gen.py` | v0.7 |
| 2025-05 | 渐变正则改为宽泛匹配 | `animation_gen.py` | v0.7.1 |
| 2025-05 | validate_output slides 区域提取修正 | `animation_gen.py` | v0.7.1 |
| 2025-05 | 输出文件名加时间戳，不覆盖旧版本 | `animation_gen.py` | v0.7.1 |
| 2025-05 | Prompt 禁止 SVG 内部元素加 .anim 类 | `slide_content.md` | v0.7.2 |
| 2025-05 | merge_html() 兜底剥离 SVG 内 .anim 类 | `animation_gen.py` | v0.7.2 |
