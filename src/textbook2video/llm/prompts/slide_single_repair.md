# Single Slide Repair Prompt

> Minimal template for repairing a single failed slide. Much smaller than batch repair.

---

## Prompt 模板

```
你正在修复一个教学 slide 的 HTML 布局问题。浏览器几何自检发现这个页面布局失败。

## 输出要求（强制）
- 只输出 1 个 `<div class="slide">...</div>` 块。
- 不要输出 markdown、解释文字、`<style>`、`<script>`、`<!DOCTYPE>`、`<html>`、`<head>`、`<body>`。
- 保留 `.anim` 入场类，但不要给 SVG 内部元素加 `.anim`。
- 保留已有的 {{IMG_eN}} 占位标记或 <img src="data:image/..." ...> 标签，不要删除或替换为 SVG。
- 尽量保留教学含义和视觉风格，只修复布局问题。

## 修复方法
- 减少 gap、缩小字体/行高/间距/卡片高度，增加 `min-height:0` 或 `max-height`。
- 文字必须留在底部安全区（距底边 64px）之上。
- 不要在 `.slide` 上写 `position`、`height:100vh`、`top`、`left`。
- 子容器不要用 `height:100vh`，用 `height:100%`、`flex:1`、`max-height:calc(100vh - 120px)`。
- 如果 SVG 图表和下方文字间距太小（< 110px），缩小 SVG 高度或加 margin。
- 内容溢出时优先缩小装饰元素/字号/间距，不要删教学内容。

## 课程
{LESSON_TITLE}
{LESSON_DESCRIPTION}

## 页面内容
{SCENE_DESCRIPTION}

## QA 失败详情
{QA_SUMMARY}

## 原 HTML
{SLIDE_HTML}

{THEME_PROMPT}

{LAYOUT_PROMPT}
```
