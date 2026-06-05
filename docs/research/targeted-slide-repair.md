# 精准修复调研：Slide HTML 布局修复 vs Coding Agent 编辑策略

> 2026-06-05 | 讨论文档，不改代码

## 1. 当前问题

### 1.1 错误现象

`animate` 阶段生成 slide HTML 后，Playwright 几何自检（`check_layout.py`）发现部分页面布局失败。修复流程有三层：

| 层级 | 文件 | 机制 | 粒度 | Token 成本 |
|------|------|------|------|-----------|
| Layer 0 | `css_hotfix.py` | 确定性 CSS 修复（Playwright DOM 操作） | 元素级（CSS selector） | 0 tokens |
| Layer 1 | `animation_gen.py` → `repair_single_slides` | 单页 HTML 整页送 LLM 重写 | 整页级 | 高（单页可达 MB） |
| Layer 2 | `animation_gen.py` → `replace_failed_batches` | 整批 HTML 送 LLM 重写 | 批次级（4页） | 极高 |

**直接错误**：slide 7 的 HTML 有 3,081,807 字符（约 3MB），Layer 1 的 `repair_single_slides` 把整个 3MB HTML 塞入 prompt，超过 `deepseek-v4-flash` 的上下文窗口，触发 `ContextWindowExceededError`。LLM 连看都看不到这个 slide，更别提修复它。

### 1.2 为什么 slide 7 有 3MB？

正常 slide 应该是 20-80 KB。3MB 大概率是 LLM 生成时：
- 产出了大量重复/嵌套内容
- 或嵌入了超大 base64 内联图片
- 或 SVG 过度复杂

这种 case 的正确修复不是"微调某一行 CSS"，而是"检测到异常大小后整页重生成"。

### 1.3 QA 报告已经提供了什么

`check_layout.py` 的 QA 报告**已经非常精确**。每个 failure 都带：

```json
{
  "type": "text_out_of_bottom_safe_area",
  "selector": "div.content-card",
  "tag": "div",
  "text": "这是一段文字...",
  "rect": {"top": 950, "bottom": 1020, "left": 100, "right": 800},
  "limit": 1016
}
```

- **CSS selector**（`selector` 字段）
- **元素标签和文本内容**
- **精确像素坐标**（`rect: {top, bottom, left, right}`）
- **失败原因和阈值**

这意味着我们**已经知道**是哪个元素出了什么问题、它在哪里。问题在于怎么把修复指令精确地"送达"那个元素，而不是把整个 3MB HTML 都送进去。

### 1.4 当前修复为什么是"整页"的

HTML/CSS 布局的特殊性：
1. **CSS 是级联的** —— 一个元素的 `overflow: hidden` 可能是因为三层父容器的 flex 布局约束
2. **盒模型是全局的** —— 改一个 `margin` 可能引起整个页面的连锁反应
3. **渲染依赖浏览器** —— 最终效果只能由浏览器渲染后验证，纯文本分析不够

所以当前方案把整个 slide HTML 给 LLM，让它看到完整的 CSS 层级关系后做修复。这在 HTML < 100KB 时工作良好，但遇到 3MB 就彻底崩溃。


## 2. Coding Agent 的编辑策略调研

### 2.1 Claude Code（Anthropic）

**核心机制：`FileEditTool` — 精确字符串替换**

```
Edit(file_path, old_string, new_string, replace_all?)
```

工作原理：
1. 在文件中**精确搜索** `old_string`（逐字符匹配，包括空格/换行）
2. 要求 `old_string` 在文件中**恰好出现一次**（除非 `replace_all=true`）
3. 替换为 `new_string`
4. 如果不唯一，返回错误要求提供更多上下文

关键设计决策：
- **Read-before-edit 强制执行**：必须先 Read 文件才能 Edit，防止基于过时记忆编辑
- **不使用行号**：避免 LLM 数错行的问题
- **不使用正则**：精确匹配，无歧义
- **原子操作**：要么全部成功，要么文件不变
- **失败后回退**：多次 Edit 失败后，LLM 可以回退到 Write（全文件重写）

还有一个 `apply_patch` 工具（实验性），使用自定义 patch 格式：
- 支持 `*** Add File` / `*** Delete File` / `*** Update File`
- Update 使用 `old_lines` / `new_lines` 描述替换
- **四级渐进模糊匹配**：精确 → 尾部空白 → 全空白 → Unicode 归一化
- 替换按从后往前顺序应用，避免索引偏移

### 2.2 Aider

**核心机制：SEARCH/REPLACE 块 + 多格式支持**

Aider 支持多种编辑格式，根据模型自动选择最优：

| 格式 | 描述 | 适用场景 |
|------|------|---------|
| `whole` | LLM 返回整个文件 | 简单但低效 |
| `diff` | SEARCH/REPLACE 块（`<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE`） | 主力格式 |
| `udiff` | 类似 unified diff，带 `+`/`-`/空格 前缀 | 适合 GPT-4 Turbo（减少"懒惰编码"） |
| `diff-fenced` | 文件名在 fence 内 | Gemini 系列 |

**Aider 的灵活匹配策略**（这是它最强大的地方）：

1. **精确匹配**：直接字符串比较
2. **空白容错**：`replace_part_with_missing_leading_whitespace()` —— 处理缩进不一致
3. **省略号处理**：`try_dotdotdots()` —— LLM 用 `...` 省略不变代码时，只替换非省略部分
4. **模糊匹配**（已禁用）：基于 `SequenceMatcher` 的 0.8 相似度阈值
5. **跨文件回退**：指定文件匹配失败时，尝试所有其他已打开文件
6. **Hunk 拆分**：大的 diff 块拆成多个小 hunk，逐个尝试应用

**大文件处理**：
- 使用 tree-sitter 解析代码结构，提取定义和引用
- 用 PageRank 算法排名代码相关性
- 生成"repo map"（紧凑的代码结构摘要）给 LLM，不需要发送完整文件
- Token 预算控制（默认 1024 tokens 给 repo map）

### 2.3 OpenHands / SWE-Agent

**核心机制：行号定位 + 字符串替换**

OpenHands 提供两种编辑工具：
1. `str_replace_editor`：精确字符串替换（类似 Claude Code 的 Edit）
2. `edit_file`（LLM-based）：指定行范围，提取该段落，发给 LLM 重写，缝合回去

`edit_file` 的工作流：
```
1. 主 LLM 指定目标行范围
2. 提取该段代码
3. 发给专门的"draft editor" LLM 重写
4. 把修改后的段落缝合回原文件
```

**关键发现**：OpenHands 在实践中发现**行号定位对 LLM 来说很困难**——模型经常数错行。他们后来也转向了类似 Aider 的 SEARCH/REPLACE diff 格式。

### 2.4 共性总结

| 共性 | 说明 |
|------|------|
| **精确字符串匹配为主** | 所有工具都优先使用 `old_string → new_string` 的精确替换 |
| **不用行号** | 几乎所有工具都发现 LLM 数行号不可靠 |
| **多级容错** | 精确匹配失败后，逐级放宽（空白 → 模糊 → 全文重写） |
| **Read-before-edit** | 强制先读后写，防止过时记忆 |
| **大文件策略** | 结构化摘要（repo map）+ 按需读取，不全量灌入 |


## 3. 对比分析：Coding Agent vs Slide 修复

### 3.1 核心差异

| 维度 | Coding Agent 编辑代码 | Slide 修复 HTML/CSS |
|------|----------------------|---------------------|
| **文本结构** | 代码有明确的 AST、行号、变量作用域 | HTML 有 DOM 树，但 CSS 布局效果是全局的 |
| **"行"的含义** | 一行代码 = 一个语句，语义清晰 | 一行 HTML 可能是任何东西（样式/内容/SVG/脚本） |
| **匹配方式** | `old_string` 精确匹配源文本 | HTML 中 inline style 顺序可变、空白不敏感，精确匹配困难 |
| **修复验证** | 编译/测试/运行即可验证 | 需要**浏览器渲染**才能验证布局 |
| **连锁影响** | 通常局部（改一个函数不影响其他） | CSS 是级联的，改一处可能影响整个页面 |
| **上下文需求** | 函数签名 + 类型 + 几行上下文就够了 | 需要完整的 CSS 层级关系才能判断布局问题 |
| **"正确"的标准** | 测试通过/编译通过 | 像素级几何约束（元素不出安全区、不重叠等） |

### 3.2 Coding Agent 的做法能否迁移？

**可以直接借鉴的**：

1. **Prompt 截断**（最紧急）
   - Claude Code 的 Edit 在匹配失败后不会把整个文件塞进去重试，而是报错让 LLM 提供更多上下文
   - 我们的 `repair_single_slides` 应该在 slide HTML 超过阈值时截断，只保留结构和问题元素附近的内容

2. **多级容错策略**
   - Aider 的"精确 → 空白容错 → 模糊 → 全文重写"四级策略可以启发我们的修复层级：
     - Level 0: CSS hotfix（确定性，0 tokens）—— 已有
     - Level 1: 元素级 LLM 修复（只发问题元素的 HTML 片段）—— 新增
     - Level 2: 整页 LLM 修复（截断后发送）—— 现有，加截断
     - Level 3: 整页重生成 —— 现有的最终回退

3. **结构化摘要**（Aider 的 repo map 思路）
   - 不发完整 HTML，而是发送 DOM 树的"骨架"（标签嵌套关系 + 关键 CSS 属性值），让 LLM 理解布局结构
   - QA 报告已经有 selector 和 rect，可以在此基础上构建"问题区域的结构摘要"

**不能直接照搬的**：

1. **精确字符串匹配替换**
   - 代码的 `old_string` 是唯一的（函数签名、变量声明等），HTML 中 `<div style="...">` 可能重复出现几十次
   - CSS 属性的顺序不影响语义（`margin: 10px; padding: 5px` 和 `padding: 5px; margin: 10px` 等价），但字符串匹配会认为它们不同

2. **"行级"定位**
   - 代码有明确的行语义（一行 = 一个语句），HTML 的一行可能是任何东西
   - 一个 CSS 布局问题的"修复行"可能散布在 HTML 的多个 inline style 中

3. **缝合逻辑**
   - 代码缝合是 `string.replace(old, new)` —— 直接、可靠
   - HTML 片段缝合需要处理：未闭合标签、属性顺序变化、空白差异、DOM 结构完整性


## 4. 可行方案讨论

### 方案 A：Prompt 截断（最小改动，立即收益）

在 `_build_single_slide_repair_prompt` 中：
- 检测 `slide_html` 长度，超过阈值（如 50K 字符）时截断
- 保留：slide 开头结构 + QA 失败元素附近 N 行 + slide 结尾闭合标签
- 截断中间部分用 `<!-- ...truncated... -->` 替代

**优点**：改动小（约 20 行），直接解决 3MB slide 爆 context 的问题
**缺点**：截断可能丢失修复所需的关键上下文

### 方案 B：元素级修复（中等改动，类似 coding agent 的 Edit）

利用 QA 报告的 `selector` 和 `rect`，从 DOM 中提取问题元素：
1. 用 Playwright 在浏览器中定位问题元素（selector 匹配）
2. 提取该元素 + 其父容器 + 兄弟元素的 HTML（几百字符而非 MB）
3. 发给 LLM：只修复这个片段
4. 用 Playwright 把修复后的 HTML 替换回去
5. 重新验证布局

**优点**：精准、token 高效
**缺点**：缝合逻辑复杂，CSS 级联效果可能导致局部修复不够
**类比**：这就是 Claude Code 的 Edit —— 但 HTML 不像代码那样有明确的唯一匹配

### 方案 C：结构化摘要 + LLM 修复（较大改动，类似 Aider 的 repo map）

1. 从 slide HTML 中提取"DOM 骨架"：标签嵌套层级 + 关键 CSS 属性 + 元素尺寸
2. 结合 QA 报告的 rect 数据，生成一个紧凑的"布局问题描述"
3. 发给 LLM 让它输出修复指令（如"把 `.card-list` 的 `gap` 从 `24px` 改为 `16px`"）
4. 用确定性规则应用修复，或用 css_hotfix 机制应用

**优点**：token 极低（骨架可能只有 2-3K 字符），LLM 只做决策不做 HTML 生成
**缺点**：需要 LLM 输出结构化的修复指令而非 HTML，prompt 设计需要迭代

### 方案 D：异常检测 + 重生成（解决根因）

slide 生成后，在进入 QA 之前加一个"大小检查"：
- 单页 HTML > 200K → 标记为异常
- 异常 slide 直接重新生成（而非尝试修复）
- 重新生成时在 prompt 中加入"不要生成超过 100K 的 HTML"的约束

**优点**：从源头解决问题
**缺点**：需要额外一次 LLM 调用，但比在 3MB 上反复失败重试便宜得多


## 5. 建议优先级

1. **A + D 组合**（推荐先做）—— 解决当前的 crash 和根因
2. **增强 css_hotfix**（低成本高收益）—— 覆盖更多 failure type，更智能的修复规则
3. **C（结构化摘要）** —— 如果 css_hotfix 覆盖率到瓶颈，作为下一阶段
4. **B（元素级修复）** —— 最后手段，复杂度高、边界情况多


## 6. 关键参考来源

- Claude Code FileEditTool 源码分析：https://github.com/liuup/claude-code-analysis
- OpenCode Patch 系统：https://www.opencodebook.xyz/en/chapter_10_snapshot_and_file_system/10.3_patch_system
- Aider 编辑格式：https://aider.chat/docs/more/edit-formats.html
- Aider Unified Diff 策略：https://aider.chat/docs/unified-diffs.html
- Aider 搜索替换逻辑：https://deepwiki.com/Aider-AI/aider/3.2-search-and-replace-logic
- OpenHands 编辑机制：https://fabianhertwig.com/blog/coding-assistants-file-edits/
- OpenHands diff-based 编辑 PR：https://github.com/OpenDevin/OpenDevin/pull/2685
