# 组件开发流程说明

> 以 `neural-network` 组件为例，演示组件从设计到代码的完整开发流程

---

## 组件开发 4 步流程

```
步骤1: 定义 Schema     →  组件能接收什么参数
步骤2: 写组件代码       →  HTML + CSS + JS（或让 LLM 生成）
步骤3: 测试验证         →  浏览器打开 demo.html 看效果
步骤4: 集成到渲染器     →  JSON 描述 → 渲染器调用组件 → 输出页面
```

---

## 步骤 1: 定义 Schema

文件：`components/neural-network/schema.json`

告诉系统这个组件叫什么、接受什么参数、每个参数的类型和默认值。

```json
{
  "name": "neural-network",
  "params": {
    "layers": [
      {"neurons": 3, "label": "输入层"},
      {"neurons": 5, "label": "隐藏层"},
      {"neurons": 2, "label": "输出层"}
    ],
    "signalFlow": true,
    "speed": 1
  }
}
```

## 步骤 2: 写组件代码

文件：`components/neural-network/demo.html`

组件代码结构：

```html
<!-- COMPONENT: neural-network START -->
<style>
  /* CSS 变量：颜色、尺寸、动画 */
  :root { --nn-input: #667eea; --nn-hidden: #764ba2; ... }
  
  /* 神经元样式 */
  .neuron { ... }
  
  /* 连线样式 */
  .connection { ... }
  
  /* @keyframes 动画 */
  @keyframes neuronBounceIn { ... }
  @keyframes connectionDraw { ... }
</style>

<div id="neural-network-container">
  <!-- JS 动态生成 SVG -->
</div>

<script>
  // 配置参数（渲染器会替换这部分）
  const CONFIG = {
    layers: [
      { neurons: 3, label: "输入层" },
      { neurons: 5, label: "隐藏层1" },
      { neurons: 4, label: "隐藏层2" },
      { neurons: 2, label: "输出层" }
    ],
    signalFlow: true,
    speed: 1
  };

  // 组件类
  class NeuralNetworkViz {
    constructor(container, config) { ... }
    buildStructure() { ... }    // 生成神经元和连线
    playBuildAnimation() { ... } // 逐层出现动画
    startSignalFlow() { ... }   // 信号传递动画（循环）
  }
</script>
<!-- COMPONENT: neural-network END -->
```

## 步骤 3: 测试验证

直接在浏览器打开 `demo.html`，检查：
- ✅ 神经元是否正确排列
- ✅ 连线是否完整
- ✅ 构建动画是否流畅
- ✅ 信号传递是否清晰可见
- ✅ 颜色和样式是否美观

## 步骤 4: 集成到渲染器（未来）

当组件库和渲染器建成后，流程是：

```
LLM 输出:
{
  "scene": 2,
  "components": [
    {
      "id": "neural-network",
      "params": {
        "layers": [
          {"neurons": 3, "label": "输入层"},
          {"neurons": 5, "label": "隐藏层"},
          {"neurons": 2, "label": "输出层"}
        ]
      }
    }
  ]
}

        ↓ 渲染器自动处理 ↓

1. 读取 neural-network 组件的 template.html + style.css
2. 用 params 替换 CONFIG 占位符
3. 嵌入到页面框架中
4. 输出完整 HTML → 浏览器录制 → 视频
```

---

## 组件文件结构

```
components/
└── neural-network/
    ├── schema.json      ← 参数定义
    ├── demo.html        ← 可运行的完整演示
    ├── template.html    ← 纯组件模板（无外框，供渲染器调用）
    ├── style.css        ← 组件样式（可单独提取）
    ├── preview.gif      ← 效果预览（可选）
    └── readme.md        ← 本文件
```

---

## 如何开发下一个组件

1. 在 `components/` 下创建新目录（如 `data-flow-pipeline/`）
2. 先写 `schema.json`（参数定义）
3. 让 LLM 根据组件清单的描述 + schema 生成 `demo.html`
4. 浏览器测试，手动调整不满意的地方
5. 提取 `template.html` 和 `style.css`
6. 完成

### Prompt 模板（给 LLM 生成组件时使用）

```
请生成一个 [组件名] CSS 动画组件，用于中小学 AI 教育。

组件功能：[从组件清单复制描述]

参数 Schema：
[粘贴 schema.json 内容]

要求：
- 纯 HTML + CSS + JS，无外部依赖
- 暗色背景，配色使用 CSS 变量
- 所有动画自动播放，适合录制视频
- 代码用注释标记 COMPONENT START / END
- 生成 demo.html，包含完整可运行的演示
```
