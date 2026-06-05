# Slide 图片尺寸问题调研

> 2026-06-05 | 讨论文档 → 已确定实施方案

## 1. 问题：图片长宽在 slide 上是否合适？

当前 pipeline 中**没有任何环节判定图片的渲染尺寸是否合适**。具体缺失：

### 1.1 注入时不看分辨率

`inject_generated_images()`（`animation_gen.py:760`）注入 `<img>` 标签时，只设了 CSS 约束：

```html
<img src="..." style="max-width:100%;max-height:100%;object-fit:contain;border-radius:12px;">
```

不管是 200x100 的小图标还是 4000x3000 的大图，都原样注入。`max-width/height:100%` 保证图片不超出父容器，但如果父容器本身没有明确的宽高约束，图片会按原始尺寸渲染。

### 1.2 AI 生成的图固定 1024x1024

`config.py:64` 写死 `IMAGE_SIZE = "1024x1024"`。对于 slide 实际显示区域（通常最大约 800x600），这个分辨率偏高，base64 后约 1-2MB。

### 1.3 教材原图不限尺寸

`load_textbook_images()`（`animation_gen.py:806`）从 `images/` 目录读取教材原图，直接 `read_bytes()` → `base64.b64encode()`，不做任何缩放或压缩。教材插图可能从 200x100 到 3000x2000 不等。

### 1.4 QA 不检查 `<img>`

`check_layout.py` 的布局 QA 只检查 SVG 和 canvas 的尺寸（`large_visual_too_tall` 检查 `item.rect.height > viewport.height * 0.65`），**完全不检查 `<img>` 标签的渲染尺寸**。

这意味着：
- 一张图占了 slide 90% 高度、只剩 10% 给文字 → 不会被发现
- 图片宽高比严重不匹配显示区域、留大面积白 → 不会被发现
- 教材原图分辨率过大导致 base64 撑爆 HTML → 不会被发现（直到 LLM 修复时 ContextWindowExceededError）


## 2. 哪些场景会出问题

| 场景 | 后果 | 当前是否被捕获 |
|------|------|--------------|
| 教材原图 3000x2000 内嵌 base64 | slide HTML 达 3MB+，修复时爆 LLM context | 否 |
| 图片占 slide 高度 80%，文字只剩 10% | 布局失调、文字被挤到安全区外 | 可能（如果文字溢出会被 `text_out_of_bottom_safe_area` 捕获，但根因是图片太大而非文字太多） |
| 1:1 正方形图放在 16:9 区域 | 上下大面积留白，视觉不协调 | 否 |
| 多张图片并列 | `image_gen.py` 的 `_segment_has_parallel_images` 会降级为 SVG，但教材原图（有 src）不在检查范围 | 部分捕获（AI 图降级，教材原图不管） |


## 3. 已确定的实施方案：C + D + A

经过讨论，确定**以方向 C 为核心**，配合 D（容器约束）和 A（QA 验收）。方向 B（缩放）暂不需要——C 已经把图片从 HTML 中剥离，不再有体积问题；将来如果有网页分发场景再加。

### 为什么选 C 为核心

| C 解决的问题 | 说明 |
|-------------|------|
| slide HTML 体积 | 从 3MB 回归 20-80KB，图片数据不再内嵌 |
| LLM 修复 prompt 爆 context | `_build_single_slide_repair_prompt` 不再包含 base64 数据 |
| 不需要 prompt 截断 | slide HTML 正常大小（几十 KB），远低于模型 context window |

### 为什么 C 必须配合 D

C 只是把 `<img src="data:...">` 改成 `<img src="images/fig1.png">`，**图片的显示尺寸完全取决于容器 CSS**。当前注入的 `<img>` 只有 `max-width:100%;max-height:100%`——这是相对于父容器的。如果父容器没有明确宽高，3000x2000 的图就真的占 3000x2000 像素，直接溢出 slide。

所以 D（给图片容器加明确尺寸约束）必须和 C 一起做。

### 为什么加 A

A（QA 加 `<img>` 检查）作为验收手段——C+D 改完后跑一次 QA，确认图片不再溢出。5 行代码的事。


## 4. 具体实施计划

### 4.1 方向 C：图片改用外部文件引用

**目标**：`<img src="data:image/png;base64,...">` → `<img src="images/fig1.png">`

**涉及文件和改动**：

#### `animation_gen.py` — `inject_generated_images()`

当前逻辑：从 `generated_images` dict 取 base64 data URI，直接拼进 `<img src="...">`。

改为：
1. `generated_images` dict 的值改为图片文件名（如 `"images/fig1-1_xxx.png"`），不再存 base64
2. AI 生成的图片保存为文件到输出目录的 `images/` 下，而非存 base64 字符串
3. `<img>` 的 `src` 直接用相对路径

```python
# 改前
img_tag = f'<img src="{data_uri}" alt="{desc}" style="...">'
# 改后
img_tag = f'<img src="{image_path}" alt="{desc}" style="...">'
```

#### `animation_gen.py` — `load_textbook_images()`

当前逻辑：读取图片文件 → base64 编码 → 返回 data URI。

改为：图片文件已经在 `images/` 目录下，直接返回相对路径。

```python
# 改前
b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
result[key] = f"data:{mime};base64,{b64}"
# 改后
result[key] = f"images/{src}"  # src 是 storyboard 里的文件名
```

#### `llm/image_gen.py` — `generate_images_for_storyboard()`

当前逻辑：生成图片 → 返回 base64 data URI dict。

改为：生成图片 → 保存为 `images/ai_{seg_id}_{elem_id}.png` → 返回相对路径 dict。

#### `llm/image_gen.py` — `generate_svgs_for_storyboard()`

当前逻辑：SVG → base64 data URI。

改为：SVG 保存为 `images/svg_{seg_id}_{elem_id}.svg` → 返回相对路径。

#### 录制器兼容性

`recorder.py` 用 `file:///` 打开 HTML，浏览器能正常加载同目录下的 `images/` 文件，**无需改动**。

### 4.2 方向 D：模板渲染加图片容器约束

**目标**：不管原图多大，图片容器不超过 slide 高度的 45%。

**涉及文件**：`template_renderer.py`

在 `_render_element()` 的 image 分支中，给外层容器加 `max-height`：

```html
<!-- 改前 -->
<div style="...justify-content:center;">{{IMG_eN}}</div>

<!-- 改后 -->
<div style="...justify-content:center;max-height:45vh;overflow:hidden;">
  {{IMG_eN}}
</div>
```

同时在 `animation_gen.py` 的 `inject_generated_images()` 中，注入的 `<img>` 标签保持 `max-width:100%;max-height:100%;object-fit:contain` 不变——配合容器的 `max-height:45vh`，图片会在容器内等比缩放。

### 4.3 方向 A：QA 加 `<img>` 尺寸检查

**涉及文件**：`scripts/check_layout.py`

在 JS checker 的 `large_visual_too_tall` 检查处，把 `<img>` 加入检查范围：

```javascript
// 改前
if (['svg', 'canvas'].includes(item.tag) && item.rect.height > viewport.height * 0.65) {
    add('warn', 'large_visual_too_tall', item);
}

// 改后
if (['svg', 'canvas', 'img'].includes(item.tag) && item.rect.height > viewport.height * 0.65) {
    add('warn', 'large_visual_too_tall', item);
}
```


## 5. 改动量和优先级

| 步骤 | 方向 | 文件 | 改动量 | 说明 |
|------|------|------|--------|------|
| 1 | D（容器约束） | `template_renderer.py` | ~10 行 | 先做防御性兜底，改完立即验证布局 |
| 2 | C（外部引用） | `animation_gen.py` + `image_gen.py` | ~40 行 | 核心改动，彻底解决体积问题 |
| 3 | A（QA 检查） | `check_layout.py` | ~5 行 | 验收手段，确认 C+D 生效 |

**不需要做的**：
- B（注入前缩放）——C 已经剥离图片数据，体积不再是问题
- prompt 截断逻辑——slide HTML 回归正常大小后不再需要
- 单文件 HTML 合并——录制器用 `file://` 协议，外部引用正常工作


## 6. 风险和注意事项

1. **LLM 生成的 HTML 中的图片**：LLM fallback 生成 slide 时可能手写 `<img>` 标签，需要确保它不直接内嵌 base64。当前 prompt 已经指示 LLM 用 `{{IMG_eN}}` 占位符，风险低。

2. **图片路径一致性**：C 改动后，`images/` 目录必须和 HTML 文件在同一父目录。当前 pipeline 已经把图片提取到 `output/xxx/images/`，HTML 保存在 `output/xxx/`，路径天然一致。

3. **`css_hotfix.py` 和布局修复**：这些模块操作的是 HTML 字符串中的 DOM，`<img src="images/fig1.png">` 和 `<img src="data:...">` 对它们没有区别，不受影响。
