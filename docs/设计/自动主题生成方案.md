# 自动主题生成（LLM 辅助 Theme 创建）

> 状态：**草案，待讨论**
> 创建日期：2026-06-08
> 范围：让 LLM 根据一句 mood 描述自动产出可用的 theme，省去手工调色配字的活

---

## 1. 背景

当前 3 个主题（`bright` / `dark-blue-academic` / `3b1b-math`）都是手写。每加一个新主题要：

- 选 20+ 个颜色（含 glow/border/卡片渐变多套阴影）
- 选 4 种字体（标题/正文/数字/标签）
- 调 easing 曲线 4 条 + duration_scale + stagger 步长 + 粒子密度
- 写 13 条 `prompt_hints`（给 LLM 描述视觉风格）
- 可选：自定义 keyframes 映射

熟手做也要 1–2 天，且配色全靠经验。配色和风格描述恰恰是 LLM 强项——一句"复古蒸汽波" → 全套参数能瞬间出。

## 2. 目标 / 非目标

### 目标
- **L1（必须）**：一条 CLI 命令 + 一句 mood 描述 → 生成一份合规的 `themes/<id>.json`
- **L2（可选）**：让 LLM 同时生成几个主题级 `@keyframes`，让该主题有自己的动画语言
- **闭环验证**：自动跑一份样例 storyboard 出 HTML 截图，肉眼可直接看到效果

### 非目标
- ❌ **L3**：不让 LLM 写 `template_variants.py` 的元素变体（contract 太严，出错整页崩）
- ❌ 不替代设计师做精细打磨——LLM 出"能用且符合 mood 的初稿"，不是终稿
- ❌ 不做主题市场 / 浏览 / 投票之类的产品功能

---

## 3. 用户故事

```bash
# 最简形式：一句 mood
t2v theme new cyberpunk --mood "霓虹紫粉、未来感、玻璃质感卡片、活泼但克制"

# 输出：
✅ themes/cyberpunk.json 生成
✅ Schema 校验通过
✅ 对比度校验通过（最低 4.8:1）
✅ Smoke test: output/_theme_preview/cyberpunk-smoke.html

open output/_theme_preview/cyberpunk-smoke.html  # 看 3 页样例

# 立即可用
t2v produce textbook.docx --chapter 3 --section 0 --theme cyberpunk -o output/test
```

### 可选参数

| 参数 | 作用 |
|---|---|
| `--mood "<text>"` | 风格描述（必填） |
| `--ref <theme_id>` | 参考主题（继承字体类、layout_mode、未指定值） |
| `--model <id>` | LLM 模型，默认 ecnu-plus |
| `--with-keyframes` | 启用 L2，让 LLM 生成主题专属 keyframes |
| `--no-smoke-test` | 跳过样例渲染（快 30 秒） |
| `--dry-run` | 只生成 JSON 打印到终端，不写文件 |

---

## 4. 架构

### 4.1 模块分工

```
src/textbook2video/
├── theme_scaffolder.py            # ★新增：编排 LLM 调用 + 校验 + 写入
├── theme_validator.py             # ★新增：schema/对比度/CSS 语法校验
├── themes/__init__.py             # 注册表 _REGISTRY 自动追加新条目
├── llm/prompts/
│   ├── theme_design.md            # ★新增：mood → 完整 theme.json 的提示词
│   └── theme_keyframes.md         # ★新增：mood → @keyframes 集合（L2）
└── cli.py                         # 加 `theme new` 子命令
```

### 4.2 数据流

```
mood 描述
   │
   ▼
┌──────────────────────────────────────────────┐
│ Step 1: 设计参数（LLM 调用 #1）              │
│  ─────────────────────────                  │
│  prompt: mood + JSON schema + 参考主题示例   │
│  output: 结构化 JSON（visual/effects/anim..）│
│  + 兜底：缺字段用 ref 主题补全                │
└──────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────┐
│ Step 2: 校验                                 │
│  · JSON Schema (Pydantic) 必填/类型           │
│  · 颜色合法 hex / rgba                       │
│  · 对比度（WCAG 2.1）：text ↔ bg ≥ 4.5      │
│  · easing 是合法 cubic-bezier 曲线           │
│  · duration_scale ∈ [0.5, 2.0]               │
│  · particle_density_scale ∈ [0, 3]           │
│  失败：把具体问题塞回 LLM 让它修正（重试 ≤2 轮）│
└──────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────┐
│ Step 3（可选 L2）：自定义关键帧               │
│  ─────────────────────────                  │
│  LLM 调用 #2：mood + 现有 keyframes 风格示例  │
│  output: 一组 @keyframes 块（追加到 base.css）│
│  + 主题 keyframes 映射（哪个 anim 类用哪个 kf）│
│  校验：CSS 语法、transform 值不越界           │
└──────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────┐
│ Step 4: 落盘 + 注册                           │
│  · 写 themes/<id>.json                       │
│  · 写 templates/base.css 追加 keyframes（L2） │
│  · themes/__init__.py 的 _REGISTRY 加一行     │
└──────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────┐
│ Step 5: Smoke test                            │
│  ─────────────                              │
│  用一份内置的 3 页 mini-storyboard 跑 animate │
│  输出 output/_theme_preview/<id>-smoke.html   │
│  （covers 标题/对比/数据 3 种 visual_type）   │
└──────────────────────────────────────────────┘
```

---

## 5. LLM Prompt 设计

### 5.1 `theme_design.md` 关键段落

```
你是一位 UI 主题设计师，根据用户的一句 mood 描述，输出符合以下 schema 的完整 theme JSON。

【任务约束】
- 配色：≥6 种主色（primary/accent/secondary/success/warning/orange/gold）、3 种背景色
- 所有 text-on-bg 对比度 ≥ 4.5（WCAG AA）
- easing 4 条 cubic-bezier 曲线（smooth/bounce/anticipate/arc），y 不超过 ±2
- duration_scale ∈ [0.7, 1.4]
- 字体：从给定白名单挑（避免引入新字体文件）

【mood: {USER_MOOD}】

【可参考的已有主题】
- bright（活泼/课件）: ...
- dark-blue-academic（沉稳/学术）: ...
- 3b1b-math（数学课本/极简）: ...

【输出 schema（截断版）】
{
  "theme_id": "{TARGET_ID}",
  "name": "<中文短名>",
  "description": "<一句风格定位>",
  "engine": "css-html",
  "layout": { "mode": "fullscreen" },
  "visual": { ... 22 字段 },
  "effects": { "particles": bool, ... },
  "animation": { duration_scale, easing, transition_style, particle_density_scale, stagger_step_ms },
  "page_styles": { ... },
  "color_palette": { ... },
  "prompt_hints": [ "≤13 句视觉风格描述" ]
}

只输出 JSON，不要 markdown 围栏。
```

### 5.2 `theme_keyframes.md`（L2）

```
你是一位 CSS 动画师。根据 mood 描述，生成 3-5 个主题专属 @keyframes，
并给出它们对应替换哪些通用 anim 类。

【mood: {USER_MOOD}】

【现有的 @keyframes 风格示例】
- gentleSlideUp：from translateY(20px) opacity 0 → to 0/1（无弹）
- manimSlideUp: from translateY(60px) scale(0.98) blur(2px) → 焦距感
- bounceIn: 弹跳过冲 0%→50%（1.12）→70%（0.95）→100%（1）

【规则】
- 每个 keyframe 名以 <theme_id> 开头（如 cyberpunkGlitchIn）
- transform 仅用 translate/scale/rotate/skew + filter blur/hue-rotate
- 任何 scale 值 ∈ [0.5, 1.5]
- 不要用 outline / background 变化（破坏布局）
- 输出 JSON：
{
  "keyframes_css": "@keyframes cyberpunkGlitchIn { ... }\n@keyframes ...",
  "mapping": {
    "kf-up": "cyberpunkGlitchIn",
    "kf-card": "cyberpunkSlide",
    ...
  }
}
```

---

## 6. 校验策略

### 6.1 Schema 校验（Pydantic）

```python
class ThemeAnimation(BaseModel):
    duration_scale: float = Field(ge=0.5, le=2.0)
    easing: dict[str, CubicBezier]  # 4 条
    transition_style: Literal["push-left","push-right","zoom","dissolve"]
    particle_density_scale: float = Field(ge=0, le=3)
    stagger_step_ms: int = Field(ge=40, le=400)
    keyframes: dict[str, str] | None = None  # L2 时填

class ThemeJSON(BaseModel):
    theme_id: str
    name: str
    description: str
    visual: ThemeVisual
    effects: ThemeEffects
    animation: ThemeAnimation
    color_palette: dict
    prompt_hints: list[str] = Field(max_length=15)
```

### 6.2 对比度校验

```python
def assert_contrast(fg: str, bg: str, name: str, min_ratio=4.5):
    ratio = wcag_contrast(fg, bg)
    if ratio < min_ratio:
        raise ValidationError(
            f"{name}: 前景 {fg} vs 背景 {bg} 对比度 {ratio:.2f} < {min_ratio}"
        )

# 校验对：
# text_color vs background, text_dim vs background,
# accent vs background, primary vs card_bg
```

### 6.3 CSS keyframes 校验（L2）

```python
def validate_keyframes(css: str):
    # 1. 解析：每个 @keyframes 块结构完整
    blocks = parse_keyframes(css)
    for kf in blocks:
        # 2. 命名以 theme_id 开头
        assert kf.name.startswith(theme_id)
        # 3. 所有 transform 值 in safe range
        for frame in kf.frames:
            check_transform_bounds(frame.transform)
```

---

## 7. CLI 实现要点

```python
@cli.command("theme")
@cli.subcommand("new")
def cmd_theme_new(args):
    """t2v theme new <id> --mood "<text>" [--ref <ref>] [--with-keyframes]"""
    # 1. 检查 id 不冲突
    if args.id in list_themes():
        raise CLIError(f"主题 {args.id} 已存在；--force 覆盖")
    
    # 2. 调 scaffolder
    theme = scaffold_theme(
        theme_id=args.id,
        mood=args.mood,
        reference_theme=args.ref or "bright",
        with_keyframes=args.with_keyframes,
        model=args.model,
    )
    
    # 3. 落盘
    write_theme(theme)
    register_theme(args.id)  # 改 __init__.py
    
    # 4. Smoke test
    if not args.no_smoke_test:
        run_smoke_test(args.id)
```

---

## 8. 实施分期

### Phase 1（L1 最小可用）— 约 8 小时
- [ ] `theme_design.md` prompt（参考 3 主题示例）
- [ ] `theme_validator.py`（schema + 对比度）
- [ ] `theme_scaffolder.py`（编排 LLM → 校验 → 重试 → 写入）
- [ ] `cli.py` 加 `theme new`
- [ ] 注册表自动追加（编辑 `__init__.py`）
- [ ] 测试：mock LLM 出 3 种不同 mood，校验通过
- [ ] 跑 1 个真实主题（如 `--mood "暖色调儿童课件"`）验证

### Phase 2（L2 自定义 keyframes）— 约 4 小时
- [ ] `theme_keyframes.md` prompt
- [ ] CSS keyframes 解析 + 安全范围校验
- [ ] 追加 `base.css` 时加注释包围（方便回滚）
- [ ] 测试

### Phase 3（Smoke test 闭环）— 约 3 小时
- [ ] 内置 mini-storyboard（3 页：title / comparison / illustration）
- [ ] `theme new` 末尾跑 animate → 输出 preview HTML
- [ ] Playwright 截图 + 让 LLM "自评估"（可选）
- [ ] 失败时打印诊断信息（哪个对比度低、哪个字段缺）

### Phase 4（迭代闭环，可选）— 约 4 小时
- [ ] `t2v theme refine <id> --tweak "<反馈>"` 命令
- [ ] 给 LLM 当前 theme + 用户反馈，让它产出 diff
- [ ] 应用 patch 并重跑 smoke

**总工作量**：L1 = 8h；L1+L2 = 12h；全套 = 19h。

---

## 9. 风险与缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| LLM 出的配色对比度不够 | 中 | WCAG 校验 + 重试 2 轮，失败 abort 而非降级 |
| LLM 不熟悉 cubic-bezier 边界 | 高 | Prompt 给 5+ 安全示例 + 解析校验 |
| 新 keyframes 与 base.css 命名冲突 | 低 | 强制以 `<theme_id>` 前缀命名 |
| 自动改 `__init__.py` 破坏代码 | 中 | 不改 Python，改用 themes/<id>.json + 启动时自动扫目录注册 |
| Mood 太抽象 LLM 抓不住 | 中 | 加 `--ref` 参数让用户指定基线主题继承 |
| 写文件失败留下半成品 | 低 | 先写临时 → 全校验过 → atomic move |
| Smoke test 渲染失败 | 中 | 容错，至少把 JSON 保留下来不删 |
| L2 keyframes 视觉效果"古怪" | 高 | 默认 L2 关闭，需 `--with-keyframes` 显式打开 |

---

## 10. 开放问题（讨论项）

### Q1：注册机制是改 `__init__.py` 还是自动扫目录？

**改 `__init__.py`**：
- ✅ 显式，代码可读
- ❌ 写代码风险（语法错误）

**自动扫 `themes/*.json`**：
- ✅ 零代码改动
- ❌ 调试不直观
- 推荐这个 — 改启动逻辑一次受益

### Q2：keyframes 该写哪里？

- A：追加到 `templates/base.css`（共享）
- B：每个主题单独 `themes/<id>.css`（隔离）
- C：写进 `theme.json` 的 `keyframes_css` 字段，注入时拼到 `<style>`

**推荐 C**：主题完全自含，删主题时一并删动画，最干净。改动小（`theme_to_css_vars` 多输出一段 keyframes_css）。

### Q3：要不要做"质量评分"？

让 LLM 看 smoke test 截图，给主题打分（美感 / 可读性 / mood 契合度）。失败重生。

- ✅ 闭环更稳
- ❌ 多花 1-2 次 LLM 调用 + 视觉评估精度有限
- 推荐留到 Phase 4，先不做

### Q4：要不要支持继承 / patch？

`t2v theme new dark-bright --base bright --override "background:#000"` 这种。

- ✅ 微调成本极低
- ❌ 增加复杂度，跟 `--ref` 重叠
- 推荐：先不做，看用户反馈

### Q5：Smoke test 用哪份 storyboard？

候选：
- A：硬编码一个 3 页 storyboard（title + comparison + illustration）
- B：用 `t2v doctor` 一样自带，纯静态文本
- C：让用户传 `--smoke-storyboard <path>`

**推荐 A**：内置 3 页覆盖最常见 visual_type，足够看出主题视觉。

---

## 11. 决策需要

讨论后需要明确：

1. ✅/❌ 整个计划方向
2. Phase 1 / Phase 2 / 全做 — 实施范围
3. 注册机制选 自动扫目录 还是 改 `__init__.py`
4. keyframes 位置选 base.css 还是 主题自含
5. 优先级：先做这个，还是先做 [improvements.md](improvements.md) 里别的项

---

## 12. 后续延伸

如果 L1+L2 跑顺，后续可考虑：
- **主题市场**：UGC 主题分享（暂不做，但 JSON 自含 + 自动扫目录的设计已为此铺路）
- **主题混合**：`t2v theme blend bright cyberpunk` 取两个主题的中间态
- **主题 A/B 测试**：同一份 storyboard 用两个主题各跑一遍并排展示
