## network 组件参考
- 用 SVG 表达输入、隐藏、输出等层级节点，x 轴分层、y 轴均匀排布，节点用圆形半透明填充和 CSS 变量描边。
- 层间连接线使用 `<line>`，低透明度、细线宽，可用 `stroke-dasharray` 或轻微动画表达数据流。
- 节点标签用 SVG `<text>` 居中；整图放在 HTML 容器上加 `.anim`，不要给 SVG 内部元素加 `.anim`。
