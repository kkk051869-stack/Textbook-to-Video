# A Visual Decision 人工审查指南

审查对象是：

```text
datasets/research_generation_v2/annotation/20261006-3cm-human-review-packet-A/human_review_packet.md
```

不要判断“答案是否和模型一样”，而是按下面的固定顺序判断每一条 proposition。

## 1. 命题边界

先问：这句话是否表达了一个可以单独判断的知识命题？

- 可以判断：`proposition_boundary=accept`。
- 句子残缺、多个命题无法拆开、上下文不足：`uncertain`。

## 2. 是否真的需要视觉

做反事实测试：如果只保留这句话和旁白，学习者能不能核查命题中的对象、关系、步骤、
比较或结论？

- 能：`visual_support_need=none`，`retrieval_need=no`，`visual_function=null`。
- 不能，而且视觉必须承载结构、轨迹、字段、空间关系或证据链：继续第 3 步。

“有图更直观”“图片更好看”“教材旁边刚好有照片”都不算需要视觉的理由。

## 3. 教材源图是否足够

只看 packet 中列出的教材源图，不使用旧 A4 外部候选图。

- 源图直接展示命题的核心关系：`source-sufficient`。
- 源图没有，或只展示相关背景/文字，不能核查核心关系：`extra-support-needed`。

不要因为图片里出现了相同关键词，就判定为 `source-sufficient`；必须能看到命题要求
学习者理解的核心关系。

## 4. 额外视觉是检索还是生成

只有在第 3 步为 `extra-support-needed` 时才判断：

- 有通用、静态、可审计的外部图，能展示同一关系，且不需要添加命题之外的事实：`retrieve`。
- 需要为本命题组合“实体—轨迹—记录—后果”等定制链条，通用外部图会丢失关键关系：`generation-candidate`。

当前 v4.2 的正例 `lesson-011-kprop-005`：骑行轨迹 → 不可篡改记录 → 行为佐证 →
信用/规则后果。普通区块链结构图只说明链式结构，不足以展示整条骑行治理链，因此应为
`extra-support-needed + generation-candidate + explain`。

## 5. visual_function 怎么选

- `explain`：视觉让对象、结构、轨迹、因果或证据链变得可核查。
- `organize`：视觉主要整理类别、层级或步骤。
- `signal`：视觉主要突出某个重点或变化。
- `example`：视觉提供命题中的具体例子。
- `decorative`：只能装饰；单独不能让命题从 `none` 变成需要视觉。
- `uncertain`：确实无法判断。

若 `visual_support_need=none`，`visual_function` 必须是 `null`。

## 6. source_evidence_ids 怎么审

只保留支持当前命题和视觉判断的最小 packet-listed 证据集合：

- 不要为了保险列整段邻近页；
- 如果多个证据共同组成不可拆分的核心链条，可以全部保留；
- 只要 ID 不在 packet 的可用证据列表里，就一定是错误。

## 7. 审查完成条件

逐条看完 30 条后：

- 没有需要修改的条目：回复 `我已审查全部 30 条，确认无误，冻结为 human-reviewed gold`；
- 有问题：列出 proposition ID、字段名、建议值，例如 `lesson-011-kprop-005 / retrieval_need / generation-candidate`。

只有收到明确确认后，才会生成 human-reviewed gold 冻结文件；当前审查包本身仍不是 gold。
