## chart-line 组件参考
- 用 `.chart-container` 承载标题和 SVG 折线图，SVG 含坐标轴、网格线、渐变面积、主曲线和数据点。
- 曲线使用 `path d` 表达趋势，可用 `drawLine`、`stroke-dasharray`、数据点延迟出现强化动态。
- 保持 viewBox 比例，图表高度不要撑破页面；轴标签和标注文字使用 `var(--text-dim)` 与主题变量。
