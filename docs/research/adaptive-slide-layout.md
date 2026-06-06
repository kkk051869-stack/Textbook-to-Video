# 自适应 Slide 版面设计

> 2026-06-06 | 教学 slide 确定性渲染的版面方案——让单页既不溢出（内容多）也不空旷（内容少）。
>
> 本文是该问题的**唯一权威设计**，整合并取代了早前两版分析草稿（viewport-budget / element-rules，已删除）。
> 那两版对 `space-evenly` 致空旷的洞察有价值（已吸收进本文），但其**解法**——Python 用字数估高度 → 套固定模板 →
> 盲目压缩——方向有误。本文基于**实证 + 参考版式 + 成熟工具调研**给出更优方案。L1 的具体元素组合规则见**附录 A**。

---

## 0. 一句话结论

**不要在 Python 里算布局。** 把"自适应填充"交给浏览器的布局引擎（Flex/Grid/clamp 本就是干这个的）；Python 只做两件**内容级**决策——生成时给"空间预算"，渲染后真不够才"拆页/裁剪"。**测量用浏览器，不用字数猜。** 而且——**溢出和空旷是两个不同的问题，必须用两套不同机制**，不能指望同一个旋钮同时解决。

---

## 1. 重新定义问题

旧文档把问题框成"给定元素，把它们塞进视口"。这个框法导致它去**估算+套模板**。正确的框法是把它拆成**两个独立子问题**，并认清它们的解法相反：

| 子问题 | 现象 | 正确机制 | 错误机制（旧方案） |
|--------|------|---------|------------------|
| **溢出** | 内容多，越过 1080 安全区 | 真实布局 → 测量 → 整页缩放 → 仍不够则**拆页** | 字数估高 + 盲目压字号/删元素 |
| **空旷** | 内容少，被均匀间距拉散 | 让主元素**长大填充** / 成组居中 / 切稀疏档 | `justify-content:space-evenly` |

**关键认知（来自 reveal.js/Beamer 调研）**：整页等比缩放**只能治溢出，反而加剧空旷**（留白一起缩小）。所以两个子问题不能共用一套逻辑——这是旧文档最大的方法论盲点（它用一套"预算+压缩"想通吃两头）。

---

## 2. 旧方案的根本缺陷（含实证）

### 2.1 在 Python 里重造了一个布局引擎，且造得不准

旧方案用 `chars // 35` 估文字行数、给每类元素一个固定 px。**我从真实布局实测报告（`output/**/*.layout.json`，1920×1080）提取了渲染高度**：

| 元素（按选择器归类） | 实测中位 | 实测范围 | 极差 |
|---------------------|---------|---------|------|
| div（通用容器） | 42px | 17–180 | **163** |
| svg | 200px | 24–600 | **576** |
| img | 300px | 300–404 | 104 |
| highlight/quote | 82px | 62–82 | 20 |
| heading | 52px | 42–67 | 25 |

**同一类元素高度方差极大**（svg 差 24 倍、div 差 10 倍）。任何"按类型给固定高度"的估算**从数学上注定失真**——这正是旧文档 slide 6 那个"9px 溢出"无法消除的根因：估算精度已经见底。**结论：估算路线不可救，必须改为实测。**

> 浏览器的 Flex/Grid/clamp/container-query 本来就是为"消化不确定内容量"而生。绕过它、在 Python 里用字数硬猜，是用错了工具。

### 2.2 生成层与渲染层互不通气（治症状不治病）

`storyboard.md` 让 LLM 产出"6-9 个元素"，却毫不知道 `table(6行)+comparison_panel+5 个轻元素`物理上放不下。约束应在**生成时**给，而不是渲染时硬塞。旧文档自己都前后矛盾：§6.1 说砍到 3-5 个，§9 又说保留 6-9——因为**元素"个数"根本不是正确的旋钮**（9 个小标签能装下，3 个大表格装不下）。

### 2.3 固定 4 模板（A/B/C/D）太脆

按"总高阈值"在 4 个模板间选，既覆盖不了元素组合的组合爆炸，又把脆弱估算重新引入了模板选择逻辑。

### 2.4 实测现状：旧渲染器真实产物仍在溢出

当前 master 的产物在 1920×1080 实测 **PASS 31/36 页**（5 页溢出）。即"分批生成 + 图片外置"落地后，**版面溢出/空旷问题依然存在**——因为那些改动解决的是 token 截断和 HTML 体积，没碰版面排布。

---

## 3. 实证依据三件套

旧文档没做这三件事，本文补上：

### 3.1 实测真实高度 → §2.1（证明估算不可行）

### 3.2 参考 PPT 的版式 DNA（学术深蓝主题，`reference/数学素养/`）

逐页观察提炼出**好版面的共性**：

1. **左右非对称构图**：左侧文字列 + 右侧大图/图表，几乎从不"垂直堆叠居中"。
2. **巨型锚点元素（hero）**：如整页一个大"变/局"字、或一张大图——给页面视觉重心。
3. **靠内容尺寸填空间**：文字块够大、图够大、锚点够大；**留白是四周的对称边距（设计），不是元素之间的均匀大缝（空旷）**。
4. **持久标题角标**：左上角一个小标题 chip 贯穿全章。
5. **文字↔配图行对齐**：左侧每段说明，对齐右侧对应的图。

旧渲染器的"垂直堆叠 + space-evenly"与这套 DNA 完全相反——这从设计层面解释了"为什么 QA 全过但还是难看"。

### 3.3 成熟工具怎么做（调研结论）

| 系统 | 核心机制 | 可借鉴 |
|------|---------|--------|
| **PowerPoint Designer** | 内容**分类**→检索 ~200 个**角色占位模板**，不算坐标；占位符自带 autofit | 角色→`grid-template-areas` 模板库 |
| **Gamma / Tome** | 块(block)→卡片(card)映射，**一张装不下就拆到下一张** | "溢出即拆页" |
| **reveal.js** | 标称尺寸自然布局 → **测量 → 整页 `transform:scale`**；`r-stretch` 让元素吃掉剩余高度；`r-fit-text` 二分填字 | 测量+缩放兜底；grow 填充；fit-text |
| **Beamer** | **先真实排版、量出高度、算 shrink factor**；`allowframebreaks` 自动拆帧 | 两段式（排版后缩放）；缩到下限就拆页 |
| **Marp** | 仅水平 auto-scale，**纵向溢出官方建议分页**，字号别太小 | 缩放有底线，宁可拆页 |
| **CSS 现代能力** | `grid auto-fit/minmax`、`flex-grow`、`clamp()`、container queries | 让 CSS 消化内容量波动 |
| **GRIDS (CHI'20, MILP)** | 把**填满度(rectangularity/packing)** 显式当优化目标 | "避免空旷"= 把"填满"当显式目标，而非被动接受 |

**共识**：没有任何成熟系统靠"字数估高度"。它们都是"**让真实布局发生 → 测量 → 缩放/拆页**"，并用现代 CSS 让容器自适应。

---

## 4. 更优方案：三层闭环架构

```
生成(权重预算+角色语法)  →  渲染(角色Grid+长大填充)  →  测量(浏览器真实几何)
         ▲                                                      │
         └──────────── 反馈：溢出→缩放/拆页  空旷→长大/换档 ◄────┘
```

### 4.1 L1 生成层：用"空间权重 + 单主元素语法"取代"元素个数"

**(a) 空间权重预算**（粗粒度、语义化，LLM 推理得动）：

| 元素 | 权重 | 说明 |
|------|------|------|
| image / comparison_panel | 3 | 重，占主区 |
| table | 1 + 0.5×行数 | 随行数增长 |
| flow_step / activity_step | 2 | 横向流程 |
| icon_group | 1.5 | 卡片墙 |
| quote / stat_card / text | 1 | 轻量 |
| heading / subheading / label / badge | 0 | chrome，不计 |

**一页目标总权重 5–8**：够满、不溢。权重比 px 稳，因为粗且语义化。

**(b) 角色语法**：每页 = **恰好 1 个主元素**（image / comparison_panel / table / flow_step 选一）+ **2–4 个轻元素**。一举解决"重元素堆砌"（主元素封顶 1）和"太空"（轻元素保底）。

**(c) 互斥与去重**（理由是权重，不是拍脑袋）：comparison_panel↔table、flow_step↔icon_group、flow_step↔activity_step 互斥；每种类型 ≤1 次（无重复 image / icon_group）。

**(d) network/tree**：不止"回避"——**给渲染器补一个简单节点图渲染器**，从根上别让 prompt 和 LLM 打架（比旧文档"引导 LLM 用 icon_group 替代"更彻底）。短期回避可作为过渡。

### 4.2 L2 渲染层：角色 Grid + 长大填充（删掉 space-evenly）

**核心：让 CSS 消化内容量波动，多数页根本不需要 Python 干预。**

**(a) 角色驱动 `grid-template-areas`**（学 Designer + 参考 PPT 的左右构图）。按"主元素类型"选少量语义模板，例：

```css
/* 概念页：左 hero + 右文字列；wide 元素跨底 */
.slide[data-compose="hero-aside"] .t2v-content-box{
  display:grid;
  grid-template-columns: 1.15fr 1fr;
  grid-template-areas: "hero aside" "wide wide";
  gap: clamp(16px, 2vh, 28px);
}
```

**(b) 长大填充（借 reveal.js `r-stretch`）—— 治空旷的关键**：
- 主元素（hero 区）`min-height:0` + 让图/面板 `flex:1` 或 grid 区 `1fr` **长大吃掉剩余纵向空间**；
- **禁用 `justify-content: space-between/space-evenly`**（这是旧渲染器空旷的元凶），改用"块自身长大"吸收空间。

**(c) 同类多元素用 `grid auto-fit + minmax`**（图标组/数据卡片/流程步骤）：

```css
.icon-group{ display:grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:16px; }
```

数量变化时自动决定每行几个并填满宽度，**无需 Python 算换行**。

**(d) 流式字号/间距 `clamp()` + 容器单位**：

```css
.t2v-content-box{ container-type:size; }
.lead-text{ font-size: clamp(20px, 3.2cqh, 30px); }
```

字号随**所在内容容器**缩放且有上下限，溢出多在 CSS 层自愈。

**(e) 大数字/短标题用 fit-text**（二分填字，借 `r-fit-text`/textFit）：stat_card 的数字、标题字 fill 满各自格子。

**(f) 稀疏档（治空旷的第二招）**：当 L1 权重总和偏低（如 ≤4），切到**稀疏档模板**——更大字号上限、更大图占比、单栏成组**居中**（reveal.js `center:true` 思路）+ 四周对称大留白。**留白是设计，不是 bug。**

### 4.3 L3 校正层：测量（不估算）→ 分情况处置

系统**已经**用 Playwright 跑布局 QA。把它当"真值预算源"：

**溢出**（measured bottom > safe area）按顺序：
1. **确定性 CSS 微调**（css_hotfix：收 gap/padding、`clamp` 下探）——targeted，0 token。
2. **整页 `transform: scale(s)`**，s = 安全高度 / 实测内容高度，设下限 `s_min`（如 0.85）。借 reveal.js/Beamer。
3. **s < s_min（内容确实太多）→ 拆页**：按角色边界把后半元素切到新 slide；**音频先行模型可在句子边界切分旁白**，得到两张更短的页。借 Gamma/Beamer `allowframebreaks`。**这是旧文档从未考虑的解法**，对"table(6行)+comparison+5轻元素"这种本就装不下的页，拆页远胜硬塞。

**空旷**（measured content height ≪ available）：
- 走 L2 的长大/居中/稀疏档已从结构上基本消除；作为兜底，测量到大面积空白则**放大 hero 或把一个轻元素提升为更大的呈现**。
- **绝不默认"自动补内容"**（加占位文字/图标）——它引入不确定性、与确定性渲染冲突，仅作最后手段。

> 性能：L2 的 CSS 自适应让 ~80% 的页无需校正；L3 的浏览器测量只对少数页触发，且复用已有 QA 渲染，增量成本可控。

---

## 5. 与旧方案对照

| 维度 | 旧文档方案 | 本方案 |
|------|-----------|--------|
| 高度来源 | Python `chars//35` 估算 | 浏览器实测 |
| 谁排版 | Python 选固定模板 | 浏览器 Flex/Grid/clamp |
| 填充方式 | space-evenly 撑间距 | 主元素 grow 填内容 |
| 生成约束 | 元素**个数**（自相矛盾） | 空间**权重** + 角色语法 |
| 溢出处置 | 盲目压缩/删元素 | 测量→缩放→**拆页** |
| 空旷处置 | 无（space-evenly 就是病因） | grow / 居中 / 稀疏档（**独立机制**） |
| 模板 | 固定 A/B/C/D | 角色驱动 `grid-template-areas`（可泛化） |
| network/tree | 让 LLM 回避 | 补渲染器 + 短期回避 |

---

## 6. 落地路线（增量、低风险优先）

| 步 | 内容 | 文件 | 价值/成本 | 风险 |
|----|------|------|----------|------|
| **1** | **删 space-evenly，按元素数切 grow/center** | `template_renderer.py`（几行） | 立竿见影治空旷 | 极低 |
| 2 | 同类多元素改 `auto-fit/minmax`，字号改 `clamp+cq` | `template_renderer.py` + `base.css` | CSS 自适应吃掉多数波动 | 低 |
| 3 | 角色 `grid-template-areas` 模板（hero-aside / data / process） | `template_renderer.py` | 对齐参考版式 | 中 |
| 4 | L1 prompt：权重预算 + 角色语法 + 互斥 | `storyboard.md` + `validate` 加权重校验 | 从源头控密度 | 中 |
| 5 | L3：整页 `transform:scale` 兜底 + 拆页 | `animation_gen.py` + recorder 配合 | 根治"装不下" | 中高 |
| 6 | network/tree 简单渲染器 | `template_renderer.py` | 去掉 LLM fallback 黑盒 | 中 |

**先做第 1 步**（删 space-evenly）——最小改动、直接治"元素少了仍然差"。第 5 步（缩放+拆页）是治溢出的根治手段，但牵涉录制时长与旁白切分，单独评估。

## 7. 验证方式（可证伪，区别于旧文档的"实测 7/8"无代码佐证）

- 每步用真实 storyboard（`output/**/*storyboard.json`）跑 `animate`，对比**前后的 `*.layout.json` 实测几何**（PASS 率 + 实测内容高度 vs 视口）。
- 指标：① 1920×1080 PASS 率；② 内容高度 / 视口 的填充比（治空旷，目标 0.7–0.95）；③ 拆页触发率。
- **所有结论以实测报告为准，不以估算为准**——这是本方案与旧文档方法论的根本分野。

## 8. 风险与边界

- CSS 自适应能"消化波动"但不保证恰好填到 1080 不溢出（`clamp` 有上限、`auto-fit` 会换行）——所以 L3 测量+缩放兜底不可省。
- `flex-grow` 把空间灌进**文字块**会变成块内大空白（文字不会自己变大）——可拉伸角色应优先选图/面板/留白容器，纯文字靠 `clamp` 放大字号 + 居中。
- 整页缩放会一并缩小字号、可能弱化层级；用**统一缩放因子**而非逐元素 fit，保持层级比例。
- 拆页改变页数 → 影响 `audio_duration_sec` 与 segment↔slide 对应；需在拆页时同步切分旁白与时长（与 `validate` 的段数一致性校验联动）。

## 附录 A：L1 元素组合快查（实现 prompt 用）

落实 §4.1 的"单主元素语法"时，按页型选 1 个主元素 + 2–4 个轻元素，控制总权重在 5–8。

| 页型 (visual_type) | 主元素（选 1） | 推荐轻元素（2–4） | 备注 |
|--------------------|---------------|------------------|------|
| 标题 title | quote 或 icon_group | subheading + stat_card | 权重低→走稀疏档，hero 放大 |
| 概念 definition / illustration | image 或 quote(长定义) | icon_group + text + stat_card | 有教材图优先 image（左图右文） |
| 对比 comparison | comparison_panel **或** table | stat_card + text | 二者互斥，选其一 |
| 流程 process / timeline | flow_step | text + stat_card | flow ≥5 步会换行，注意权重 |
| 数据 data-chart / data-bar | table | stat_card×2 + text | table 行数计入权重 |
| 图文 illustration(有图) | image | text + quote/label | 行对齐右图 |
| 活动 activity | activity_step | text 或 quote | |
| 网络 network / tree | （渲染器补节点图；未补前回避，用 icon_group + 文字模拟关系） | label | 见 §4.1(d) |

**硬规则**（写进 prompt + `validate` 校验）：

1. **每页恰好 1 个主元素**（image / comparison_panel / table / flow_step / activity_step 选一）。
2. **每种类型 ≤ 1 次**（无重复 image、无重复 icon_group）。
3. **互斥**：comparison_panel ↔ table；flow_step ↔ icon_group；flow_step ↔ activity_step。
4. **总权重 5–8**（权重见 §4.1(a)）；< 5 走稀疏档，> 8 拆页。
5. **绝对禁止**：visual_type=network/tree（渲染器未支持前）、双宽元素同页（comparison_panel + table / + 大 image）。

## 9. 参考来源

- PowerPoint Designer 版式逻辑；Gamma 卡片/分页模型
- reveal.js Presentation Size / Layout（scale、r-stretch、r-fit-text）；Beamer shrink / allowframebreaks；Marp fitting/autoscale
- CSS：clamp / container queries / grid auto-fit+minmax / flex grow-shrink
- 约束布局：Cassowary；GRIDS: Interactive Layout Design with Integer Programming (CHI 2020, arXiv:2001.02921)
- 二分填字：textFit
