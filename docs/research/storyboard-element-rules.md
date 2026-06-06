# Storyboard 元素组合规则分析

> ⚠️ **方法论已被 `adaptive-slide-layout.md` 取代**。本文 §7 对 `space-evenly` 致空旷的洞察很关键，已被新文档吸收；
> 但本文用"元素**个数**"做约束的思路有误（§6.1 与 §9 自相矛盾）——正确旋钮是"空间**权重** + 单主元素语法"。请以新文档为准。

## 1. Prompt 当前指令逻辑

`storyboard.md` 对元素数量的指令（L133-154）：

```
每个 segment 设计 6-9 个 elements
组织成清晰层次：主标题 → 核心内容（主元素）→ 支撑要点 → 强调/总结
```

对元素类型组合的指令（L145-154 "各页型推荐元素组合"）：

| 页型 | 推荐组合 |
|------|---------|
| 标题页 | heading + subheading + icon_group + quote + stat_card |
| 概念页 | heading + subheading + quote + icon_group + text + stat_card 或 image |
| 对比页 | heading + comparison_panel + table + stat_card + icon_group |
| 流程页 | heading + flow_step + icon_group + stat_card + quote 或 text |
| 时间线 | heading + flow_step + table + image + text + stat_card |
| 数据页 | heading + table + stat_card + text + icon_group |
| 活动 | heading + activity_step + icon_group + text + quote |
| 网络 | heading + node + connection + label |

**问题**：推荐组合本身就包含 4-5 种 body 类型（如对比页 = comparison_panel + table + stat_card + icon_group），而 renderer 的 viewport budget（约 800px 高度）很难在单页内容纳 5+ 个不重叠的 body 元素。

## 2. Renderer 的硬约束

来自 `template_renderer.py`：

**不支持的 visual_type**（整页 fallback 到 LLM）：
- `network`、`tree` → UNSUPPORTED_VISUAL_TYPES

**不支持的 element type**（含任一则整页 fallback）：
- `node`、`connection`、`bar`、`chart_line`、`code`

**Viewport budget**：
- 内容区可用高度约 800px（1080 - outer padding - title bar - card padding - safety）
- 宽元素（comparison_panel / table / flow_step / activity_step）强制跨栏底部
- 模板 B（左图右文）在有 image 占位时自动启用
- 超标时启用压缩模式（gap 20→12px，padding 缩减）

**Renderer 渲染能力上限**（实测经验值）：

| 元素类型 | 估算高度 (px) | 说明 |
|----------|-------------|------|
| subheading | 48 | 固定 |
| text (35字) | ~62 | 1行 |
| text (70字) | ~100 | 2行 |
| quote | ~84 | 1行文本 + padding |
| icon_group (3项) | 170 | 横排卡片 |
| icon_group (4项) | 340 | 两排 |
| stat_card | 90 | 固定 |
| image (无注入) | 0 | 跳过或降为文字描述 |
| image (有注入) | 300-587 | **不可控**，AI 生成图可能很高 |
| comparison_panel | 200 | 固定 |
| table (3行) | ~216 | 含表头 |
| flow_step (4步) | 90 | 单排 |
| flow_step (5步) | 180 | 两排 |

800px 预算下，`comparison_panel(200) + icon_group(170) + text(62) + image(300)` = 732px 勉强装下，但加上 gap 就超标。这就是为什么 seg1/seg5/seg6 在 ch3-v3 会溢出。

## 3. 两版 Storyboard 逐段分析

### ch3-v3（6 segments，原始 prompt）

| Seg | visual_type | body 元素 (excl heading/subheading) | body types 数 | QA 结果 | 问题 |
|-----|-------------|-------------------------------------|---------------|---------|------|
| 1 | definition | quote + icon_group + image + text | **4** | overflow | image 587px 太高；4种类型堆砌 |
| 2 | comparison | comparison_panel + icon_group + stat_card | 3 | PASS | 无 |
| 3 | timeline | flow_step + image + quote + image | 3 | PASS | **2 个 image**（类型重复） |
| 4 | **network** | node x4 + connection x3 + text | - | **fallback LLM** | **UNSUPPORTED**，LLM 自由写 HTML |
| 5 | comparison | comparison_panel + stat_card + text + image | **4** | overflow | image + comparison_panel 双宽元素 |
| 6 | illustration | quote + icon_group + image + text | **4** | overflow | 同 seg1，4种类型 |

### ch3-v4（8 segments，改过 prompt 后 — 已回退）

| Seg | visual_type | body 元素 | body types 数 | QA 结果 | 问题 |
|-----|-------------|-----------|---------------|---------|------|
| 1 | title | quote + icon_group | 2 | PASS | - |
| 2 | comparison | comparison_panel + quote + stat_card | 3 | PASS | - |
| 3 | illustration | image + text + quote | 3 | PASS | - |
| 4 | illustration | image + quote + text | 3 | PASS | - |
| 5 | comparison | comparison_panel + stat_card + text | 3 | PASS | - |
| 6 | illustration | image + icon_group + quote | 3 | PASS | - |
| 7 | illustration | image + icon_group + text + quote | **4** | PASS | 4种，但刚好不溢出 |
| 8 | illustration | quote + icon_group + image | 3 | PASS | - |

**关键发现**：
- 3 种 body types 几乎都能 PASS（7/8）
- 4 种 body types 在 ch3-v3 全部溢出，在 ch3-v4 勉强 PASS（seg7）
- network 类型必然 fallback LLM，结果不可控

## 4. 不应该出现的组合

基于以上数据，以下组合模式有高概率导致布局溢出或视觉杂乱：

### 4.1 绝对禁止

| 组合 | 原因 |
|------|------|
| visual_type = network / tree | Renderer 不支持，整页 fallback LLM |
| 同一类型出现 ≥ 2 次（如 2 个 image） | 违反"每种类型最多 1 次"，且占双倍空间 |
| comparison_panel + table | 都是数据展示，选其一；两者并列高度超 400px |
| flow_step + icon_group | 都是列举（步骤 vs 要点），功能重叠 |
| flow_step + activity_step | 都是步骤，功能完全重叠 |

### 4.2 高风险（需谨慎）

| 组合 | 风险 |
|------|------|
| comparison_panel + image | comparison_panel 是宽元素（跨栏），image 也需要空间；双宽元素竞争 |
| flow_step (5+步) + text | flow_step 两排 180px + text 62px，已达 242px |
| icon_group (4项) + 任何其他卡片 | icon_group 4项 = 340px（两排），只剩 460px 给其余元素 |

### 4.3 安全组合

| 组合 | 估算高度 | 余量 |
|------|---------|------|
| comparison_panel + stat_card + text | 200+90+62 = 352px | 充裕 |
| quote + icon_group(3) + text | 84+170+62 = 316px | 充裕 |
| image + text + quote | 300+62+84 = 446px | 足够（模板 B 左图右文） |
| flow_step(4步) + text + stat_card | 90+62+90 = 242px | 充裕 |
| table(3行) + stat_card + quote | 216+90+84 = 390px | 足够 |

## 5. 元素类型分组规则

将所有 body 元素按功能分为 4 组。每页从**恰好 1 个主元素组**选 1 个主元素，再从辅助组选 1-2 个辅助元素。heading/subheading 不计入。

### 分组定义

```
主元素（选且仅选 1 个）：
  数据型：comparison_panel | table
  概念型：quote | text（长文本）
  列举型：icon_group | flow_step | activity_step
  图示型：image（有 src 或 AI 生成）

辅助元素（选 1-2 个）：
  轻量型：text | quote | label | badge | stat_card
```

### 页型 → 组合映射

| 页型 | visual_type | 主元素 | 辅助元素（≤2） | body types 上限 |
|------|-------------|--------|---------------|----------------|
| 数据/对比页 | comparison / data-chart / data-bar | comparison_panel 或 table | stat_card + (text 或 quote) | 3 |
| 概念页 | definition / illustration | quote 或 text（长） | icon_group + (stat_card 或 image) | 3 |
| 流程页 | process / timeline | flow_step | text + (stat_card 或 quote) | 3 |
| 图文页 | illustration（有教材图） | image | text + (quote 或 label) | 3 |
| 标题页 | title | icon_group 或 quote | subheading + (stat_card 或 text) | 2 |
| 活动页 | activity | activity_step | text 或 quote | 2 |
| 网络页 | network | **回避** | 改用 icon_group + connection 语义模拟 | 2 |

### 核心约束

1. **每页 body types ≤ 3**（含主 + 辅助）
2. **每种类型最多 1 次**（无重复 image、无重复 icon_group）
3. **主元素选 1 个**：数据型/概念型/列举型/图示型，只从一类中选
4. **互斥**：comparison_panel ↔ table，flow_step ↔ icon_group，flow_step ↔ activity_step
5. **避免 network/tree**：建议 LLM 改用 `icon_group` + 文字描述表达节点关系，避免 renderer fallback

## 6. Prompt 修改建议

当前 prompt 的问题集中在两点：

### 6.1 "6-9 elements" 过多

Renderer budget 800px，6 个 body elements（不含 heading/subheading）几乎必然超标。应改为 **3-5 个 body elements**。

### 6.2 "各页型推荐元素组合" 自相矛盾

推荐组合写的是 `comparison_panel + table + stat_card + icon_group`（4 body types），这本身就违反了 renderer 的实际承载能力。应改为**每页主元素 1 个 + 辅助 1-2 个**的结构。

### 6.3 缺少互斥规则

Prompt 没有明确禁止 comparison_panel 与 table 同时出现、flow_step 与 icon_group 同时出现。LLM 自然倾向于"多放几个不同类型丰富画面"，导致类型堆砌。

### 6.4 network/tree 没有回避建议

Prompt 把 network/tree 列为合法 visual_type，但 renderer 不支持。LLM 选择 network 后整页 fallback，等于让弱模型自由发挥。建议要么在 prompt 中引导 LLM 用 icon_group 替代 network，要么在 renderer 中增加 icon_group-based 网络模拟。

## 7. ch3-v4 视觉效果分析（为什么"元素少了但仍然差"）

ch3-v4 的 QA 虽然全过（8/8 PASS），但视觉效果是所有版本中最差的。根本原因不在元素数量，而在 **renderer 的布局逻辑**。

### 7.1 核心问题：`justify-content: space-evenly`

`template_renderer.py` L144-148，content-box 容器的关键样式：

```css
.t2v-content-box {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: space-evenly;  /* ← 这是罪魁祸首 */
    gap: 20px;
    padding: 38px 54px;
}
```

`space-evenly` 的工作方式：把剩余空间**均匀分配**到每个元素之间（包括首尾），元素本身不会变大。当只有 2-3 个 body elements 时：

- content-box 高度 ≈ 840px
- 元素总高度（如 comparison_panel 200px + stat_card 90px + quote 60px）= 350px
- **剩余 490px 全部变成空白间距**

这不是"元素太小"，而是"元素数量不足以填满 space-evenly 撑开的空间"。元素本身尺寸没变（comparison_panel 还是 200px 高），但它们被分散到巨大的间距中，视觉上显得空旷、单薄。

### 7.2 逐 slide 验证

| Slide | body 元素 | 元素总高 | content-box 高 | 空白间距 | 效果 |
|-------|----------|---------|---------------|---------|------|
| 2 | comparison_panel + quote + stat_card | ~350px | ~840px | **~490px** | 三个小块散在巨大白空间里 |
| 3 | image + text + quote (模板B) | ~360+100+60 | ~840px | ~320px | 图片被 max-height:45vh 限制，右侧文字少 |
| 5 | comparison_panel + stat_card + text | ~352px | ~840px | **~488px** | 同 slide 2 |
| 6 | image + icon_group + quote (模板B) | ~300+170+60 | ~840px | ~310px | 左图太小，右卡片少 |
| 7 | image + icon_group + text + quote (模板B) | ~360+170+62+60 | ~840px | ~188px | 唯一看起来不那么空的页 |

**Slide 2 具体分析**：
```html
<div class="t2v-content-box" style="...justify-content:space-evenly...">
    <div class="highlight-box">向科技创新要答案</div>         <!-- ~60px -->
    <div class="stat_card">1 / 核心变量：科技创新</div>       <!-- ~90px -->
    <div class="comparison_panel">战略机遇 VS 外部压力</div>   <!-- ~200px -->
</div>
```
350px 的内容被 space-evenly 拉散到 840px 空间里。comparison_panel 是一个很扁的横条（全宽但只有 200px 高），上下各约 245px 空白。

### 7.3 根因总结

问题有两层：

1. **Prompt 层**：砍元素数量（6-9→3-5）确实减少了溢出，但没考虑到 renderer 会用 space-evenly 把少量元素分散到全屏
2. **Renderer 层**：`justify-content: space-evenly` 是为 6-9 个元素设计的（元素多了，间距均匀，视觉均衡）；但当元素少到 3-4 个时，间距变成巨量空白

正确的修复方向不是继续调 prompt 的元素数量，而是 **renderer 的布局策略需要根据元素数量自适应**：
- 元素多（≥5）：space-evenly 均衡分布
- 元素少（≤4）：justify-content: center 或 flex-start，用更紧凑的 grouping

### 7.4 v4 另一个问题：同质化

8 页中 5 页是 `illustration` 类型（seg3/4/6/7/8），全是"左图右文"的模板 B 布局。没有 visual variety——没有流程图、没有数据表、没有时间线。这是因为 prompt 改版时过度限制了 visual_type 的选择空间，LLM 倾向于选最安全的 illustration 类型。

v3 虽然有些页溢出，但至少有 title / definition / comparison / timeline / network / illustration 等多种类型，视觉节奏更丰富。

## 8. 实验数据汇总

| 版本 | prompt 版本 | segments | body types ≤3 | QA PASS | network fallback | 视觉效果 |
|------|------------|----------|---------------|---------|-----------------|---------|
| ch3-v3 | 原始（6-9 elements） | 6 | 2/6 (33%) | ~3/6 | 1 页 | 元素丰富但溢出；有 visual variety |
| ch3-v4 | 改版（3-5 elements + 3 types limit） | 8 | 7/8 (88%) | 8/8 | 0 页 | QA 全过但空旷；同质化严重 |

**结论**：
- 砍元素数量 = QA PASS，但牺牲了视觉效果
- 真正的问题不在元素数量，而在 **renderer 如何根据元素数量自适应布局**
- prompt 改动的正确方向是约束**类型组合**（互斥规则、避免 network fallback），而不是约束**元素数量**

## 9. 下一步方向

### 优先级 1：Renderer 布局自适应

`_layout_content_area` 返回的 style_overrides 应包含 `justify-content` 策略：
- blocks ≤ 4 → `justify-content: center; gap: 24px`（紧凑居中，元素聚成一组）
- blocks ≥ 5 → `justify-content: space-evenly; gap: 20px`（均衡分布）

同时，元素少的页面可以让元素本身更大（如 comparison_panel 不限 max-width、icon_group 卡片更大）。

### 优先级 2：Prompt 约束类型组合（而非数量）

保留 "6-9 elements" 的元素数量指令，但加入：
- 互斥规则（comparison_panel ↔ table，flow_step ↔ icon_group）
- 避免 network/tree（用 icon_group + text 替代）
- 每种类型最多 1 次

### 优先级 3：Image 高度控制

image 元素的 `max-height:45vh`（486px）在模板 B 中会导致图片和文字比例失衡。应改为根据 light_blocks 数量动态计算（有文字侧时 max-height 更小，纯图片页可以更大）。
