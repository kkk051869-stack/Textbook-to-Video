# Storyboard Enhancer 改造任务书

## 1. 背景与结论

当前 `enhance_storyboard_quality` 位于 `src/textbook2video/pipeline/storyboard.py`。它最初用于为低质量 storyboard 自动补齐页面内容，解决“页面只有标题”“没有正文”“缺少视觉主体”等问题。

实际生成教学视频后发现，这种“补齐”会向已经平衡的页面新增 `hero`、`quote`、正文 text 等元素，使一页出现过多元素种类，破坏原本简洁的版式。它尤其容易与 lesson plan、模板渲染器和 agent review 叠加，导致同一信息被重复呈现。

本任务的结论是：**不直接删除 enhancer，而是拆分为默认的减法型规范化器和显式启用的增量型增强器。** 主生产流程只使用前者。

## 2. 改造目标

1. 默认生成流程不再自动添加任何新的教学信息或视觉元素。
2. 保留并强化对重复、冲突、超量元素的确定性修复。
3. 将“内容不足时补内容”变成显式、可配置、可审计的可选能力。
4. 让 agent review 修复后的 storyboard 仍满足简洁页面规则，不能因后处理重新变拥挤。
5. 保持旧环境变量和调用方在过渡期可用，避免批量脚本突然失效。
6. 通过单元测试和真实章节 HTML 审阅，证明改造后的页面元素种类、数量和音画链路稳定。

## 3. 非目标

- 本任务不重写 lesson plan、scriptwriter 或 storyboard LLM 提示词。
- 本任务不改变 `dark-blue-academic` 的配色、字体和动画主题。
- 本任务不改变“音频先行”的 timed storyboard、录制和 mux 链路。
- 本任务不要求模型自动判断所有视觉布局；常见布局仍由模板和 variants 确定性处理。
- 本任务不删除历史产物，也不重新生成全部视频；先以第二章 HTML 作为回归样本。

## 4. 现状梳理

当前 enhancer 的主要行为可概括为：

| 行为 | 当前价值 | 当前风险 | 改造去向 |
| --- | --- | --- | --- |
| 移除标题回声/重复标题 | 防止信息重复 | 风险低 | 保留在规范化器 |
| 移除冗余 comparison panel | 防止相同信息重复 | 风险低 | 保留在规范化器 |
| 补正文 text | 防止空页 | 可能与现有 text 重复 | 改为只做空页诊断，不默认新增 |
| 补 hero 元素 | 保证视觉主体 | 增加元素种类，造成拥挤 | 移至显式增量增强器 |
| 补 explanatory quote | 增加解释性信息 | 常与正文重复，形成多条 text | 移至显式增量增强器 |
| 刷新 timeline/动画引用 | 保证结构完整 | 风险低 | 保留在规范化器 |

现在它默认关闭，只有 `T2V_ENABLE_STORYBOARD_ENHANCER=1` 才触发；旧的 `T2V_DISABLE_STORYBOARD_ENHANCER=1` 仍被兼容。需要注意，agent review 的修复循环中仍会直接调用 enhancer，因此默认生产流若开启 agent review，仍可能发生元素回填。

## 5. 目标设计

### 5.1 拆分职责

新增两个明确的函数，并让旧函数只作为兼容包装器：

```python
def normalize_storyboard(storyboard, lesson_plan=None, *, policy=None) -> dict:
    """只做减法、去重、限额和结构修复；不得新增教学语义。"""

def enrich_storyboard(storyboard, lesson_plan=None, *, policy=None) -> dict:
    """可选的增量增强；允许补充内容，但必须记录原因。"""

def enhance_storyboard_quality(storyboard, lesson_plan=None) -> dict:
    """过渡期兼容入口，映射到 enrich_storyboard。"""
```

`normalize_storyboard` 必须是幂等的：同一份 storyboard 连续运行两次，第二次不应再改变结果。

### 5.2 默认策略

正常生成和 agent review 完成后，调用：

```python
normalize_storyboard(storyboard, lesson_plan, policy=DEFAULT_PRODUCTION_POLICY)
```

默认策略应满足：

- 一页元素种类不超过 4 种，标题计入种类。
- 非标题页面最多 3 种内容元素类型。
- 每个页面最多一个主要 widget：例如 `comparison_panel`、`table`、`flow_step`、`activity_step`、`icon_group`、`image` 中至多保留一个作为主体；复杂对比页可由明确的例外策略允许一个图片加一个主体 widget。
- text 不能并列；页面有多条 text 时必须上下排列，且使用一致的 text 变体。
- 黄色竖线只允许在上下相邻的同类 text 组合中出现；不能用于并列 text；同一页不能出现多个互不关联的竖线样式。
- 不使用“首字母超大”的 drop-cap 版式。
- 若信息量不足，不自动添加新 widget；保留现有 text 或让上游 LLM/人工重做内容。
- 保留教材原图引用，不用自动生成的 hero 覆盖已有教材图。

这些规则中的视觉细节应落在 `template_renderer.py`、`variants/` 和 CSS 中；规范化器负责输出结构能否使用某个 variant，而不是拼接 CSS。

### 5.3 增量增强器

`enrich_storyboard` 只在明确需要时启用，例如实验对比、人工审核标记“该页信息缺失”，或单独的开发模式。它必须：

- 通过单独环境变量或 CLI 参数启用，默认关闭。
- 不得静默运行在 `produce`、批量脚本或 agent review 中。
- 对每一项新增 element 在 metadata 中记录页码、元素类型、原因和来源规则。
- 每次新增后立即调用 `normalize_storyboard`，因此也无法突破默认元素限额。

建议开关：

```text
T2V_STORYBOARD_ENRICHMENT=1       # 仅开发/实验环境
T2V_STORYBOARD_POLICY=production  # 默认；可预留 experimental
```

现有 `T2V_ENABLE_STORYBOARD_ENHANCER=1` 在过渡期映射到 `T2V_STORYBOARD_ENRICHMENT=1`，并输出一次弃用提示。`T2V_DISABLE_STORYBOARD_ENHANCER=1` 保持兼容，但不再影响默认的规范化器。

## 6. 实施步骤

### 阶段 0：冻结样本与基线

1. 保存当前满意的第二章 HTML、timed storyboard 和 manifest 作为只读回归样本。
2. 统计每一页的 element 类型、数量、text variant、主体 widget 数量和标题类型。
3. 记录应当保留的好页面和需要修正的反例，包括：元素过多、多个竖线、并列 text、drop-cap、重复 quote、无必要 hero。
4. 不修改样本目录；测试使用复制件或 fixture。

### 阶段 1：引入策略与规范化器

1. 在 `storyboard.py` 附近新增 `StoryboardPolicy` 数据结构，包含元素种类上限、主体 widget 上限、text 排列规则和各类例外。
2. 将现有“去重复标题”“去冗余 comparison panel”“刷新动画引用”迁入 `normalize_storyboard`。
3. 实现元素统计、主要 widget 识别和稳定的删减优先级。
4. 对超出限额的元素，只能删除重复或次要元素；不能创造新元素补位。
5. 更新 metadata，例如：

```json
{
  "storyboard_normalization": {
    "policy": "production",
    "changed_segments": [2, 5],
    "removed": [{"segment": 2, "type": "quote", "reason": "duplicate_text"}]
  }
}
```

### 阶段 2：隔离增量增强器

1. 将 `_ensure_body_text`、`_ensure_hero_element`、`_ensure_explanatory_quote` 迁到 `enrich_storyboard`。
2. 改写旧 `enhance_storyboard_quality` 为兼容包装器，并标注废弃计划。
3. 在 CLI 和生产编排中默认只调用 `normalize_storyboard`。
4. 不允许 `enrich_storyboard` 在 agent review 循环中被隐式调用。
5. 如保留 CLI 开关，应在生成日志和 manifest 中明确写出 enrichment 是否启用。

### 阶段 3：与渲染器协同

1. 让 `template_renderer.py` 根据结构标记选择合法的 text variant，而不是由每个页面自由选择。
2. 检查 `variants/text.py`、`layouts.py` 和 CSS，删除或禁用 drop-cap 变体。
3. 固化 text 垂直堆叠规则；不允许并列 text 布局。
4. 将黄色竖线的使用条件定义为 CSS class/variant contract，不能通过临时内联样式绕开。
5. 保证 normalization 后的 elements 在渲染器中不会重新扩张成更多视觉组件。

### 阶段 4：agent review 和批处理接入

1. agent review 每轮修复后仅运行 `normalize_storyboard`。
2. 对 agent repair 返回的异常 element 类型、缺失字段和超量元素先规范化，再做结构校验。
3. 批量章节脚本记录每章的 normalization 报告，但不启用 enrichment。
4. 生成 timed storyboard 后仍运行 `verify_render_bundle`；本任务不修改音画校验标准。

### 阶段 5：回归与逐步启用

1. 先只生成第二章 HTML，不生成视频；人工审阅首页、正文、活动、测验、小结、结束页。
2. 通过后只为第二章生成 TTS、HTML、manifest 并校验，确认优化没有破坏时序。
3. 再生成第二章完整 MP4 并检查音画同步。
4. 第二章稳定后，按章节批量生成 HTML，人工抽查每章首页与特殊教学页。
5. 全部 HTML 通过后，遵循 vLLM 与 MegaTTS3 互斥队列完成云端视频生成。

## 7. 测试计划

### 单元测试

在 `tests/test_storyboard.py` 或单独的 `tests/test_storyboard_normalization.py` 中覆盖：

1. 默认生成不调用 `enrich_storyboard`。
2. `normalize_storyboard` 幂等。
3. 重复标题、重复 quote、冗余 comparison panel 被移除。
4. 超出元素种类/主要 widget 上限时，删减结果稳定且可预测。
5. text 并列结构被转为纵向或被删减为单一 text，不新增内容。
6. drop-cap 标记被移除或转为普通 text variant。
7. 教材图片不会被删除或被自动 hero 覆盖。
8. agent review 修复后只发生规范化，不发生 enrichment。
9. 旧环境变量映射正确，并产生弃用提示。
10. `storyboard_normalization` metadata 的页码、原因和计数正确。

### 集成测试

1. 以固定 mock LLM 输出跑 storyboard -> animate，确认模板渲染可完成。
2. 对第二章 fixture 运行后，检查每页元素种类不超过 4、主体 widget 数符合策略。
3. 执行布局 QA，确认没有新重叠或超出画布。
4. 使用短音频 fixture 跑 timed storyboard -> HTML -> `verify_render_bundle`，确认此次改动不改变时间同步。

### 人工视觉验收

人工审阅时逐页检查：

- 首页只保留标题、章节信息和一个有意义的主题视觉，不出现每章都相同的无关圆环或 CORE 标签。
- 正文页有明确层级，但不堆叠同义 text、quote 和 hero。
- 同一页没有并列 text；上下相邻 text 的样式一致。
- 没有黄色竖线，除非它是上下相邻同类 text 的统一样式。
- 没有首字母异常放大的版式。
- 活动、测验和小结只在 lesson plan 要求的位置出现。
- 字体、中文显示、裁切、入场动画和页间切换正常。

## 8. 验收标准

满足以下条件才算完成：

1. 常规 `generate`、`generate-docx`、`produce` 和章节批量脚本中，enrichment 默认均为关闭。
2. 所有默认生成页遵守“标题计入在内最多 4 种元素类型、非标题内容最多 3 种”的规则；例外必须在 metadata 中说明。
3. agent review 后不再自动新增 hero、quote 或 body text。
4. 第二章回归样本的页面信息完整，且不存在新增的元素拥挤、并列 text、drop-cap 或不必要竖线。
5. 新增和修改的单元测试全部通过。
6. 第二章完整音画链路通过 `verify_render_bundle` 和 final MP4 时长检查。
7. 使用旧 `T2V_ENABLE_STORYBOARD_ENHANCER=1` 的任务不会崩溃，并能得到明确迁移提示。
8. 文档更新：项目原理文档和云端全流程手册中的 enhancer 描述与实际行为一致。

## 9. 风险与缓解

| 风险 | 缓解方式 |
| --- | --- |
| 只做减法后个别页面过空 | 在质量报告中标记“内容不足”，交由上游 storyboard 或人工改写；不要由后处理静默塞元素 |
| 限额误删重要信息 | 设置稳定优先级：标题、教材原图、lesson plan 强制教学页、主体 widget、正文 text，最后才删 quote/装饰性元素 |
| 旧脚本依赖 enhancer 行为 | 兼容旧环境变量一个发布周期，并在日志中提示迁移 |
| agent repair 输出不规范 | 先运行结构校验和 normalize，再决定是否接受修复结果 |
| HTML 渲染器重新制造复杂视觉 | 用 DOM/布局 QA 和 HTML 集成测试覆盖 variant contract |
| 改造影响视频同步 | 不触碰 timing/compose；每次 HTML 变更后仍强制 manifest 校验 |

## 10. 推荐执行顺序

1. 阶段 0 和阶段 1：先实现只减不增的 `normalize_storyboard` 及测试。
2. 阶段 2：隔离现有自动补齐逻辑并处理兼容开关。
3. 阶段 3：收紧 text、竖线和 drop-cap 的渲染 contract。
4. 阶段 4：接入 agent review 和批量脚本。
5. 阶段 5：以第二章 HTML 为唯一试验场，确认满意后再扩展到全章与视频。

完成后，enhancer 不再是一个会在后台改变教学页面的黑盒，而是两项边界清晰、可配置、可审计的能力：默认的规范化器负责让页面收敛，显式的增量增强器只服务于受控实验。
