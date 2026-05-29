# Layout Repair Prompt

> Dedicated compact template for repairing generated slide batches after layout QA failures.

---

## Prompt 模板

```
你正在修复已经生成的教学 slide HTML。浏览器几何自检发现部分页面布局失败。

## 输出要求（强制）
- 只输出本 batch 的 {SLIDE_COUNT} 个 `<div class="slide">...</div>` 块。
- 不要输出 markdown、解释文字、`<!DOCTYPE>`、`<html>`、`<head>`、`<body>`、`<script>`。
- 不要增删 slide；顺序必须与原 batch 一致。
- 非失败页面尽量保持原样，只修复失败页。
- 保留 `.anim` 入场类，但不要给 SVG 内部元素加 `.anim`。

## 修复优先级
- 先通过减少 gap、改 flex/grid 分配、缩小字体/SVG/卡片高度、增加 `min-height:0` 或 `max-height` 修复越界。
- 不要在 `.slide` 上写 `position`、`height:100vh`、`top`、`left` 等覆盖框架的 inline style。
- 子容器不要使用 `height:100vh`；需要全屏感时用 `height:100%`、`flex:1`、`max-height`。
- 尽量保留教学含义和视觉风格，不要用删除关键内容来解决布局。

## 课程
{LESSON_TITLE}
{LESSON_DESCRIPTION}

## 本 batch 页面内容
{SCENES_DESCRIPTION}

## QA 失败摘要
{QA_SUMMARY}

## 失败页原 HTML
{FAILED_HTML}

## 本 batch 原完整 HTML（用于保持非失败页一致）
{PREVIOUS_BATCH_HTML}

{THEME_PROMPT}

{LAYOUT_PROMPT}
```
