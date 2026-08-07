# 元素变体库扩展计划

> 状态：**已决策，实施中**（基于 2026-06-08 讨论）
> 创建日期：2026-06-08
> 范围：把 `template_variants.py` 从 27 个 variant 扩到 ~50+，让主题之间真正"长得不一样"

## 决策记录（2026-06-08）

| 议题 | 决策 |
|---|---|
| 整体方向 | ✅ 全做，6 个 Phase 完成 |
| 文件拆分时机 | ✅ Phase 1 立即拆 |
| 每元素 variant 数 | ✅ 高频 6 / 中低频 5（统一 5-6 套） |
| `preferred_variants` 形式 | ✅ 数组（空数组 = 不限） |
| 优先级 | ✅ icon_group / comparison_panel / heading / flow_step 第一波 |
| image variant | ✅ 单独 Phase 4 处理 QA |
| 风格标签元数据 | ✅ 第一版省，契约里留位置 |

---

## 1. 背景与动机

### 1.1 现状

当前 `template_variants.py` 有 27 个 variant 覆盖 12 种元素，每元素 2–3 套版式，按 `hash(seg_id) % N` 稳定轮换。

但跨主题的差异主要来自 `theme.json` 的**配色 / 字体 / easing / stagger**——这些是"皮肤层"差异，外行用户很难第一眼看出。

### 1.2 问题

实测 3 个主题（bright/academic/3b1b）肉眼对比，差异感主要来自：
- ✅ 配色（强信号）
- ⚠️ 字体（中等）
- ❌ Easing 曲线（几乎看不出）
- ❌ Stagger 步长（除非并排对比）
- ❌ 关键帧形状（gentle/manim 实测差异微妙）

**根因**：所有主题用的是同一套元素 variant（badge_grid / pill_row / VS-centered / 等等）。元素长得一样，主题就只是"换衣服的同一个人"。

### 1.3 目标

让**主题选择不同的 variant 组合**，做到：
- 学术主题 → 极简数字列表 + 细线对比 + 衬线大字号
- 童趣主题 → 圆胖卡片 + 大徽章 + 圆角厚阴影
- 杂志主题 → 拍立得图 + 大引号 + 双栏排版
- 赛博朋克 → 霓虹胶囊 + 电路连线 + 锐角元素
- 数学课本 → 极简数字 + 无装饰 + 大留白

每个主题 = **配色 + 字体 + variant 组合**。变体库越丰富，主题差异化空间越大。

---

## 2. 目标 / 非目标

### 目标

- **总数**：每种元素 5–8 个 variant，全库目标 ≥ 60 个 variant
- **覆盖类型**：12 种 element + 多套 layout 模式（compose_image_text）
- **元素粒度**：单元素 variants + 段落组 variants + 图文构图 variants 三层
- **可组合**：主题通过 `preferred_variants` 字段挑选 ID 组合（为后续 LLM 策展铺路）
- **可独立打磨**：每个 variant 是独立函数，可随时优化不互相影响

### 非目标

- ❌ 不重写现有 27 个 variant（保留向后兼容）
- ❌ 不为每个 variant 单独写 keyframes（动画风格走主题层）
- ❌ 不引入 JS 交互（仍是纯 CSS + HTML）
- ❌ 暂不做"主题继承"（每个主题独立指定 variant ID）

---

## 3. 目标变体清单

下表为初步规划。最终设计可调整，但总数和覆盖范围应保持。

> 🟢 = 已实现 ⚪ = 待新增

### 3.1 单元素 variants

| 元素 | 现 | 目标 | 待加版式 | 风格定位 |
|---|---|---|---|---|
| **icon_group** | 3 | **8** | `minimal_squares`（方块卡，极简无渐变） | 学术/极简 |
| | | | `hex_grid`（六边形蜂巢） | 科技/赛博 |
| | | | `circle_badge_side`（圆徽章在左 + 文字右） | 杂志 |
| | | | `dotted_list`（圆点列表，最简无卡） | 童趣文档 |
| | | | `bordered_minimal`（细边框 + 数字 + 无 bg） | 课本印刷 |
| **flow_step** | 3 | **6** | `chevron_strip`（雪佛龙 ▶▶▶ 横条） | 商务/PPT |
| | | | `pipeline`（粗箭头 + 渐变阶段色） | 工程感 |
| | | | `card_chain`（卡片链 + 短连接弧线） | 教学动画 |
| **comparison_panel** | 3 | **6** | `chart_bar`（横条对比柱） | 数据 |
| | | | `top_bottom_compare`（上下两段、强 accent） | 杂志/对话 |
| | | | `v_split_dashed`（中线虚线分隔无 VS） | 学术 |
| **quote/highlight** | 3 | **5** | `left_bar_quote`（左粗 accent 竖条 + 大引号字） | 报刊 |
| | | | `magazine_pullquote`（上下细线 + 居中大字加粗） | 杂志 |
| **text (single)** | 3 | **5** | `accent_box`（浅色 accent 背景框） | 课件 |
| | | | `numbered_para`（前缀 01/02 编号） | 文档 |
| **badge** | 2 | **4** | `chip_outline`（透明 + 边框） | 极简 |
| | | | `gradient_solid`（实心强渐变） | 活泼 |
| **subheading** | 2 | **3** | `accent_underline`（带下划线 accent 强调） | 印刷 |
| **activity_step** | 2 | **3** | `numbered_circles`（大圆圈编号 + 步骤文字） | 教学 |
| **table** | 2 | **4** | `card_rows`（每行独立卡片） | 现代 |
| | | | `highlighted_first_col`（首列突出 + 简表） | 数据对比 |
| **image** | 2 | **4** | `polaroid`（白边 + 阴影 + 微旋转） | 杂志 |
| | | | `frame_caption`（细画框 + 下方居中说明） | 课本 |
| **heading** | 1 | **4** | `gradient_band`（整宽渐变 banner） | 课件 |
| | | | `numbered_chapter`（左侧大数字 + 标题） | 教材 |
| | | | `minimalist_underline`（大字号 + 下方细线） | 学术/3b1b |

**单元素小计：约 30 个新增**。

### 3.2 段落组 variants

| 组 | 现 | 目标 | 待加版式 |
|---|---|---|---|
| **text_group** | 3 | **5** | `drop_cap`（首字下沉） / `two_column`（双栏并排） |
| **badge_row** | 2 | **3** | `chip_cloud`（不规则散布的标签云） |

**段落组小计：约 3 个新增**。

### 3.3 图文构图 variants（layout 层）

| 现 | 目标 | 待加 layout |
|---|---|---|
| classic | **6** layout 模式 | `magazine_split`（30/70 不平衡分栏） |
| span_bottom | | `circular_image`（图圆形 + 文环绕） |
| full_stack | | `offset_overlap`（图文部分重叠，视觉冲击） |

**Layout 小计：约 3 个新增**。

### 3.4 合计

- 单元素新增 **~30 个**
- 段落组新增 **~3 个**
- Layout 新增 **~3 个**
- **总计新增 ≈ 36 个**，加上现有 27 个 → **全库 ~63 个**

---

## 4. 架构演进

### 4.1 文件组织

```
src/textbook2video/
├── template_variants.py          # 现状：所有 variant 在一个文件
│
└── variants/                      # ★建议拆分：按元素类型分文件
    ├── __init__.py                # 统一 VARIANTS 注册表
    ├── icon_group.py              # 8 套
    ├── flow_step.py               # 6 套
    ├── comparison_panel.py        # 6 套
    ├── quote.py                   # 5 套
    ├── text.py                    # 5 套
    ├── badge.py                   # 4 套
    ├── subheading.py              # 3 套
    ├── activity_step.py           # 3 套
    ├── table.py                   # 4 套
    ├── image.py                   # 4 套
    ├── heading.py                 # 4 套
    ├── groups.py                  # text_group + badge_row
    └── layouts.py                 # compose_image_text 多套
```

> 拆分时机：当单元素 variants >= 5 时（icon_group / flow_step / comparison_panel 立即就要拆）。
> 一个文件超过 600 行就拆。

### 4.2 Variant 注册契约

每个 variant 函数严格遵守签名：

```python
def _ig_minimal_squares(
    elem: dict, d: str, seg_id: Any, imgs: set[str],
) -> str:
    """variant 函数：返回完整的 HTML 字符串，绝不抛异常。
    空 items / 缺字段时返回空串 ""，让上游 fallback。
    """
    items = elem.get("items", []) or []
    if not items:
        return ""
    ...
    return f'<div class="anim anim-up {d}" style="...">{cards}</div>'
```

注册：

```python
# variants/icon_group.py
from . import register

@register("icon_group", name="minimal_squares")
def _ig_minimal_squares(elem, d, seg_id, imgs): ...

@register("icon_group", name="badge_grid", default=True)
def _ig_badge_grid(elem, d, seg_id, imgs): ...
```

`name` 是稳定 ID（主题可通过 `preferred_variants` 引用）。
`default=True` 表示主题未指定时的默认 variant（同时被纳入 hash 轮换）。

### 4.3 主题挑选 variants

`theme.json` 新增字段：

```json
"preferred_variants": {
  "icon_group": ["minimal_squares", "bordered_minimal"],
  "flow_step": ["chevron_strip"],
  "comparison_panel": ["v_split_dashed"],
  ...
}
```

- **数组形式**：主题可指定 1 个（强制）或多个（按 hash 轮换，但限定在子集内）
- **未指定**：走全库默认（现在的 hash%N）
- **未识别 ID**：警告并 fallback 到 default

### 4.4 选择优先级

```python
def pick_variant_html(etype, elem, seg_id, ...):
    # 1. 看 theme.preferred_variants[etype]，若有 → 限定在这组里 hash 选
    # 2. 否则从全库 hash 选
    # 3. 渲染失败/空串 → fallback 到 default variant
    # 4. 全部失败 → return None（上游走 LLM）
```

---

## 5. 实施分期

### Phase 1：拆文件 + 现有 variants 迁入（~3h）

- [ ] 建 `variants/` 目录
- [ ] 拆 `template_variants.py` 到按 etype 分文件
- [ ] 引入 `register()` 装饰器替代手工注册表
- [ ] 现有 27 个 variants 迁入对应文件，**功能不变**
- [ ] 测试不破坏现有 233 个 case

### Phase 2：优先元素扩 variant（~12h）

按出现频次和差异化收益排序：

1. **icon_group + 5 个新 variant**（占 storyboard 约 30% 出场，差异化收益最大）
2. **comparison_panel + 3 个新**（多见于 definition / comparison 页）
3. **flow_step + 3 个新**（process / timeline 必用）
4. **quote + 2 个新**（每页 1-2 个引用）
5. **text_group + 2 个新**（段落组）

子合计 15 个新 variant，约 12h（每个 40-60 分钟）。

### Phase 3：补齐剩余元素（~10h）

- [ ] heading × 3
- [ ] image × 2
- [ ] table × 2
- [ ] badge × 2
- [ ] subheading × 1
- [ ] activity_step × 1
- [ ] text × 2
- [ ] badge_row × 1

子合计 14 个新 variant，约 10h。

### Phase 4：Layout 模式扩展（~5h）

- [ ] `compose_image_text` 加 `magazine_split` 30/70 分栏
- [ ] `circular_image`（图圆形 + 文环绕）
- [ ] `offset_overlap`（图文部分重叠）
- [ ] 加 layout 选择契约（theme.preferred_layouts）

### Phase 5：主题挑选机制（~4h）

- [ ] `theme.json` 加 `preferred_variants` 字段
- [ ] `pick_variant_html` 接 theme 参数
- [ ] 3 个现有主题各填一份 `preferred_variants`，肉眼对比效果
- [ ] 跑端到端验证差异

### Phase 6（后续可选）：LLM 策展（~6h）

- [ ] LLM 看 mood + 完整 variant 库元数据 → 输出 `preferred_variants` 组合
- [ ] 加 `t2v theme new` 命令
- [ ] 详见 [auto-theme-generation.md](auto-theme-generation.md)

**Phase 1–5 总计 ~34 小时**，分批落地。Phase 6 与本文档独立。

---

## 6. Variant 质量标准

每个 variant 上线前要满足：

### 6.1 功能
- [ ] 空 input（items=[] / steps=[] 等）返回 `""`，不抛异常
- [ ] 缺字段（无 text / 无 title）有兜底（占位字符或跳过）
- [ ] 极端字数（单字 / 50 字）排版不溢出
- [ ] 元素数（1 / 4 / 8 / 20）都能合理渲染

### 6.2 视觉
- [ ] 1920×1080 跑 QA 不 fail
- [ ] 1366×768 跑 QA 不 fail
- [ ] 用 dark-blue-academic 跑一份样例 HTML
- [ ] 肉眼判断符合该 variant 设计意图

### 6.3 主题适配
- [ ] 所有颜色用 CSS 变量（`var(--primary)` 等），不硬编码
- [ ] 圆角/边框遵循 `var(--card-border)` `var(--card-shadow)`
- [ ] 字体用 `var(--font-heading)` `var(--font-body)` 等

### 6.4 测试
- [ ] `tests/test_template_variants.py` 加该 variant 的渲染测试
- [ ] 全库总测试：每个 variant 都过空 input / 正常 input 两轮

---

## 7. 风险与开放问题

### 7.1 风险

| 风险 | 缓解 |
|---|---|
| variant 数量爆炸难维护 | 严格拆文件（每 etype 独立文件），命名规范 `_<prefix>_<name>` |
| 主题与 variant 不兼容（如赛博 variant 用浅色主题） | preferred_variants 是软约束（hash 选），实测看效果，差就调主题 |
| Variant 间视觉风格不统一 | 给每个 variant 标"风格标签"（极简/活泼/科技/...），主题选同标签的组 |
| Layout variant 改 compose_image_text 太复杂 | 先冻结现有 3 layout，新 layout 走独立分支 |

### 7.2 开放问题

**Q1：是否引入 "风格标签" 元数据？**

```python
@register("icon_group", name="hex_grid", style_tags={"tech", "futuristic"})
def _ig_hex_grid(...): ...
```

主题可声明 `mood_tags: ["tech", "minimal"]`，系统自动过滤匹配的 variant 池。

- 优点：LLM 策展时更靠谱（mood → tag → variant 子集）
- 缺点：增加元数据维护成本
- **倾向**：第一版不做，等 LLM 策展时再加

**Q2：default 怎么定？**

每个 etype 必须有 1 个 default（主题未指定时用）。default 的选择标准：
- 最通用（适配多数 mood）
- 当前已有的 variant 0（现状）

**倾向**：保留现状，旧 default 不变。

**Q3：variant 是否要支持参数化？**

如 `badge_grid(badge_shape="hex")` 让一个 variant 通过参数衍生多种形态。

- 优点：少写代码
- 缺点：契约复杂、调试难
- **倾向**：不做。每个 variant 是独立函数更清晰。

**Q4：是否给 image 也做主题级框选？**

如学术主题用 `frame_caption`、杂志用 `polaroid`。

- ✅ 强烈推荐做。图片的视觉表达力极强，主题区分度最高。

**Q5：Phase 1 拆文件是否必要？**

如果 variants 文件超过 800 行就值得拆。当前 593 行还能撑。
- **倾向**：Phase 1 + Phase 2 一起完成时拆（拆得有意义）。

---

## 8. 与其他 docs 的关系

- **`auto-theme-generation.md`**：本文档完成后，那份文档的 L1 配色 + L2 keyframes 路线可以**重新定位**为"配色层"，加上本文档的"variant 组合层"才是完整的主题方案。
- **`improvements.md`**：本计划属于"#8 theme 携带动画风格"的扩展，比原计划更深入。
- **`research/adaptive-slide-layout.md`**：图文构图 variant 扩展会延续 §4.2 的角色 grid 设计。

---

## 9. 决策需要

讨论后需要明确：

1. ✅/❌ 整个扩展计划方向
2. Phase 1（拆文件）是否一开始就做，还是延后？
3. 目标 variant 数（每 etype 5-8 个）是否合适？是否过于激进？
4. `preferred_variants` 数组形式 vs 单 ID 形式，哪个更好？
5. 第一波重点元素优先级（icon_group / comparison_panel / flow_step）排序认可吗？
6. 是否同步做 image variant 扩充（Q4）？
7. 风格标签元数据（Q1）是否第一版就引入？

---

## 10. 后续延伸

如果变体库扩到 60+，主题 `preferred_variants` 字段稳定，那么：

- **LLM 策展自然顺接**：见 [auto-theme-generation.md](auto-theme-generation.md)
- **主题市场可行**：主题就是一份 JSON（配色 + variant ID 组合 + prompt_hints），自洽可分享
- **A/B 测试主题**：同 storyboard + 两个主题并排展示 variant 选择对比
- **可视化 variant 浏览器**：自动生成一个 HTML 页面展示全库 variant，方便挑选
