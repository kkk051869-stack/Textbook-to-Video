# 视口预算排版方案

## 1. 问题分析

### 1.1 现状

`template_renderer.py` 的 content 版式布局结构：

```
slide (absolute, inset:0)
├── title_bar (flex-shrink:0, ~80px)
│   ├── heading 徽章 (~56px高)
│   └── 分隔线 (2px + 8px margin)
└── content-card (flex:1, 占满剩余空间)
    └── 所有 body elements 纵向堆叠 (gap:20px, padding:38px 54px)
```

可用内容高度预算：1080 - 36*2(padding) - 80(title) - 38*2(card-padding) - 14(gap) ≈ **856px**

### 1.2 实际 overflow 案例分析

从 `ch3_s0_storyboard.json` 的 8 个 segment 实测：

| Segment | 元素数 | 元素构成 | 估算高度 | 1920 QA |
|---------|--------|---------|---------|---------|
| seg1 | 8 | heading + sub + comparison + table(2行) + stat + text + icon_group(3) + quote | ~850px | PASS |
| seg2 | 8 | heading + sub + quote + icon_group(4) + text + flow_step(3) + stat + image | ~880px | PASS |
| seg3 | 8 | heading + sub + flow_step(3) + icon_group(3) + quote + stat + text + table(3行) | ~950px | PASS(但1366 FAIL) |
| seg4 | 10 | heading + sub + image + 4×text + quote + stat + label | ~800px | PASS |
| seg5 | 9 | heading + sub + image + quote + icon_group(3) + text + stat + quote + label | ~820px | PASS |
| seg6 | 8 | heading + sub + comparison + table(**6行**) + stat + icon_group(2) + quote + text | **~1150px** | FAIL |
| seg7 | 9 | heading + sub + 2×stat + comparison + image + icon_group(3) + icon_group(4) + text | **~1050px** | FAIL |
| seg8 | 9 | heading + sub + text + quote + icon_group(3) + activity_step + image + stat + text | ~880px | PASS |

### 1.3 溢出根因

1. **元素数量无上限**：segment 最多的有 10 个 elements，每个至少 60px + 20px gap
2. **大表格/多步骤不可压缩**：table(6行) ~300px、flow_step(3步) ~200px，这些元素高度由内容决定
3. **线性堆叠**：所有元素从上到下排，横向空间浪费严重（尤其是 icon_group/stat_card 这种小卡片）
4. **现有分栏逻辑有限**：`_layout_content_area` 只在"有 image + 无 wide 元素"时做左右分栏，其他情况全部纵排

## 2. 元素分类与尺寸模型

### 2.1 元素分类

按视觉角色分为四类：

| 角色 | 元素类型 | 特征 | 典型尺寸 |
|------|---------|------|---------|
| **标题** | heading, subheading | 必须跨栏置顶 | 80px + 40px |
| **数据块(wide)** | comparison_panel, table, flow_step, activity_step | 需要整宽展示 | 150-350px |
| **视觉重心(visual)** | image | 可以独占一栏 | 200-400px |
| **轻量元素(light)** | text, quote, highlight_box, stat_card, icon_group, badge, label | 小块，可成组排列 | 40-120px |

### 2.2 各元素高度估算

基于当前 CSS 样式的实际渲染高度：

```
heading:        56px (徽章)
subheading:      40px
text:            50-80px (取决于文字长度，中文约 30 字/行)
quote:           60-90px (highlight-box)
stat_card:       80px
icon_group(N):   120-150px (N个卡片横排，高度由最高的卡决定)
icon_group卡片:  ~150px 每个
flow_step(N):    60px * N (横排时为一行高，但 N>3 会 wrap)
comparison:      180px (两个面板 + VS 分隔)
table(N行):      40px * (N+1) (含 header)
image:           200-400px (max-height:45vh ≈ 486px)
label:           40px
badge:           30px
```

### 2.3 布局区域的实际可用空间

```
视口:              1080px (1920×1080 录制)
外层 padding:      -72px (36px × 2)
title_bar:         -80px
外层 gap:          -14px
card padding:      -76px (38px × 2)
内容区 gap 均摊:   -20px * (N-1)
─────────────────────────
可用内容高度:       ≈ 818px (不含元素间 gap)
```

## 3. 排版优化规则

### 3.1 核心策略：两阶段排布

**阶段 1 — 元素分组**：将 body elements 按角色分成三组

```
wide组:   comparison_panel, table, flow_step, activity_step
visual组: image
light组:  text, quote, highlight_box, stat_card, icon_group, badge, label
```

**阶段 2 — 区域分配**：根据分组结果选择布局模板

### 3.2 布局模板

#### 模板 A：标准单栏（当前默认）

```
┌──────────────────────────┐
│ heading 徽章              │
│──────────────────────────│
│ light 元素纵向排列        │
│ ...                       │
│ wide 元素（如果有）        │
│ ...                       │
└──────────────────────────┘
```

适用条件：light + wide 总估算高度 ≤ 818px

#### 模板 B：图文双栏（当前已部分实现）

```
┌──────────────────────────┐
│ heading 徽章              │
│─────────────┬────────────│
│ image       │ light 元素  │
│ (视觉重心)   │ 纵向排列    │
│             │             │
│─────────────┴────────────│
│ wide 元素（如果有）        │
└──────────────────────────┘
```

适用条件：有 image + 无 wide 元素时（当前逻辑）
扩展条件：有 image + 有 wide 元素也适用，wide 元素放底部跨栏

#### 模板 C：双栏密集（新增）

```
┌──────────────────────────┐
│ heading 徽章              │
│─────────────┬────────────│
│ 左栏         │ 右栏        │
│ light 元素   │ light 元素  │
│ 纵向排列     │ 纵向排列    │
│             │             │
│─────────────┴────────────│
│ wide 元素（如果有）        │
└──────────────────────────┘
```

适用条件：无 image，但 light 元素总高 + wide 元素总高 > 818px

分配规则：light 元素按"交替分配"或"按高度平衡"分到左右栏

#### 模板 D：三区域布局（新增，处理元素极多的情况）

```
┌──────────────────────────┐
│ heading 徽章              │
│─────────────┬────────────│
│ image 或    │ stat_card   │
│ comparison  │ icon_group  │
│ (大视觉块)   │ badge       │
│             │ label       │
│─────────────┴────────────│
│ text + quote              │
│ wide 元素（如果有）        │
└──────────────────────────┘
```

适用条件：同时有大视觉块 + 多个装饰性元素 + 文本

### 3.3 模板选择算法

```
输入: body_elements[]
输出: 布局模板 + 元素到区域的映射

1. 分组
   wide  = [e for e in body if e.type in WIDE_TYPES]
   visual = [e for e in body if e.type == "image" and has_image_source]
   light = [e for e in body if e not in wide and e not in visual]

2. 估算高度
   h_light = sum(estimate_height(e) for e in light) + gap * (len(light) - 1)
   h_wide  = sum(estimate_height(e) for e in wide) + gap * len(wide)
   h_visual = estimate_height(visual[0]) if visual else 0
   h_total = h_light + h_wide + h_visual

3. 选择模板
   if h_total ≤ 818:
       if visual and not wide:
           return 模板B  // 图文双栏，即使不超标也用（更好看）
       else:
           return 模板A  // 标准单栏

   else:  // 超标
       if visual:
           return 模板B  // 图文双栏分流
       elif h_wide > 0:
           // wide 元素独占底部，light 需要双栏塞进剩余空间
           return 模板C
       else:
           return 模板C  // 纯 light 双栏
```

### 3.4 双栏时 light 元素的分配算法

目标：左右两栏高度尽量平衡。

```
left_items = []
right_items = []
h_left = 0
h_right = 0

for item in sorted(light, key=estimate_height, reverse=True):
    if h_left <= h_right:
        left_items.append(item)
        h_left += estimate_height(item) + gap
    else:
        right_items.append(item)
        h_right += estimate_height(item) + gap
```

贪心策略：从最重的元素开始，每次放到当前较矮的那一栏。

### 3.5 高度估算函数

```python
def estimate_height(elem) -> int:
    """估算单个元素在 content-card 内的渲染高度（px）。"""
    t = elem.get("type", "")

    if t == "subheading":     return 40
    if t in ("text", "label"):
        text = elem.get("text", "")
        # 粗略估算：中文每行 ~30 字，英文 ~60 字，行高 38px
        chars = len(text)
        lines = max(1, chars // 35)
        return 24 + lines * 38  # 24px font-size * line-height 1.6 ≈ 38px/行
    if t in ("quote", "highlight_box"):
        text = elem.get("text", "")
        lines = max(1, len(text) // 30)
        return 20 + lines * 36 + 24  # padding + text + margin
    if t == "stat_card":      return 80
    if t == "badge":          return 30
    if t == "label":          return 40
    if t == "image":          return 300  # avg, max=45vh=486px
    if t == "comparison_panel": return 180
    if t == "table":
        rows = len(elem.get("rows", []))
        headers = 1 if elem.get("headers") else 0
        return 28 + (rows + headers) * 40 + 28  # padding + cells + padding
    if t in ("flow_step", "activity_step"):
        steps = len(elem.get("steps", []))
        if steps <= 3: return 80   # 一行横排
        return 80 * ((steps + 2) // 3)  # 粗略换行估算
    if t == "icon_group":
        items = len(elem.get("items", []))
        if items <= 3: return 150  # 一行
        return 150 * ((items + 2) // 3)  # 换行
    return 80  # 默认
```

## 4. 压缩策略（模板选完后仍超标时）

如果选择了最优模板后仍然溢出，按以下优先级逐级压缩：

| 优先级 | 策略 | 节省空间 | 实现方式 |
|--------|------|---------|---------|
| 1 | 减小 gap（20px → 12px） | ~(N-1)×8px | 内容区 gap 样式 |
| 2 | 减小 card padding（38px → 24px） | ~28px | t2v-content-box padding |
| 3 | 缩小字号（-2px） | 视元素数而定 | 根元素 font-size |
| 4 | 缩小 stat_card（80px → 60px） | 每个 20px | stat_card padding/字号 |
| 5 | 缩小 icon_group 卡片（150px → 120px） | 30px/组 | 卡片 padding/图标尺寸 |
| 6 | 隐藏 quote（最低优先级元素） | ~70px | 不渲染 |

### 压缩触发条件

```
压缩后估算 = 估算高度
for 策略 in [减小gap, 减padding, 减字号, ...]:
    if 压缩后估算 ≤ 818:
        应用已选策略，停止
    压缩后估算 -= 该策略节省量
```

## 5. 实现计划

### 5.1 修改范围

只改 `template_renderer.py`，不动 `animation_gen.py` 或 `base.css`：

1. 新增 `estimate_height(elem)` 函数
2. 新增 `_choose_layout(elements)` 函数
3. 重写 `_layout_content_area(blocks)` 使用模板选择
4. 修改 `render_slide` 的 content 版式部分，根据选择的模板调整外层容器样式

### 5.2 不改动的部分

- storyboard JSON 结构不变
- segment ↔ slide 一一对应不变
- durations/audio/转场数据不受影响
- `base.css` 框架类不变
- `_render_element()` 单个元素渲染不变

### 5.3 验证方式

1. 跑现有 183 个测试（不依赖真实布局）
2. 用 `ch3_s0_storyboard.json` 重新 animate，对比 QA 结果
3. 浏览器手动检查各模板的视觉效果

### 5.4 实测结果（2026-06-05）

**1920×1080（录制视口）：**

| 迭代 | PASS | FAIL | 说明 |
|------|------|------|------|
| 实现前（旧代码） | 多页 FAIL | seg6/7 严重溢出 | 纯单栏堆叠 |
| budget=838, `>` 比较 | 6/8 | slide 6, 7 | 压缩未触发（估算恰等于预算） |
| budget=800, `>=` 比较 | **7/8** | slide 6 (9px溢出) | 压缩触发，slide 7 修复 |

**剩余问题：**
- Slide 6 (seg6) 有 comparison_panel + table(6行) 两个 wide 元素合计 ~556px，
  加上 5 个 light 元素即使双栏也无法完全容纳（溢出 9px）
- 这是内容密度上限问题，需要从 storyboard 层面控制元素数量或拆分表格

**1366×768（QA 辅助视口）：**
- 小视口下更多页面溢出（预期行为），布局优化主要面向 1920×1080 录制
- 密集页在小视口下需要更激进的压缩（可后续迭代）
