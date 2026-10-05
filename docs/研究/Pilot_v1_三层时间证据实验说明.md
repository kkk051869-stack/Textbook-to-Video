# Pilot v1 三层时间证据实验说明

## 1. 目的

本实验检验三类时间证据是否会导致不同的人工判断：

1. **Panel A — plan only**：只看 planned/compiled event；
2. **Panel B — plan + runtime**：增加浏览器 runtime trace；
3. **Panel C — rendered**：再增加 final MP4 与邻域帧。

它用于验证“planned time、runtime event、rendered visibility 不可混写”的可观察性假设，不把 runtime start 自动当成最终可见时间。

## 2. 样本

共 25 个 event，每个 case 5 个。抽样优先覆盖非 show action、target missing 等不同执行形态，再在各 case 中补足代表性事件。该选择用于 coverage，不预设事件必然存在 Temporal Contiguity 违规。

每名标注者对同一 25 个事件依次完成三块面板，共 75 个判断。A、B 文件物理隔离。

## 3. 三层证据

### Panel A：计划层

三个面板都共享 case/segment ID、segment narration、subtitle-derived proposition candidates、event ID、target 与 target element；这些是建立教学语义参照所需的固定上下文，不属于新增时间证据。Panel A 另显示 trigger/effect、compiled start、duration、easing 与候选全局时间。这里的时间表示计划/编译结果，不是实际视觉对象的出现区间。

### Panel B：运行层

在 Panel A 基础上增加 runtime trace，包括事件是否被触发、实际记录的 runtime start/end、target lookup 状态等。trace 证明脚本侧执行事实，但仍不能证明对象在成片中可见、无遮挡或保持到合理时长。

### Panel C：成片层

增加 final MP4 以及围绕候选全局时间抽取的邻域帧。每个事件默认提供 `t-2s、t-1s、t、t+1s、t+2s` 五帧；帧用于定位，最终判断必须回到连续 MP4。

## 4. 执行顺序

1. 完成并冻结 `A_plan_only.json`；
2. 再打开并完成 `B_plan_runtime.json`，不得修改 Panel A；
3. 最后完成 `C_rendered.json`，不得修改 Panel A/B；
4. 三份都完成后，记录 label 是否因新增证据改变及理由；
5. A、B 首轮结束前不得查看对方目录。

文件位置：`datasets/research_event_alignment/pilot_v1/tasks/three_layer/<annotator>/`。

## 5. 判断标签

按面板 schema 提供的字段填写，使用以下共同语义：

- `CORRECT`：现有证据支持事件与相关讲解处于可接受时间窗口；
- `EARLY`：证据支持事件早于合理窗口；
- `LATE`：证据支持事件晚于合理窗口；
- `MISSING_VISUAL`：需要的视觉在当前证据层没有出现；
- `SEMANTIC_MISMATCH`：target/visual 与讲解语义不对应，无法把问题归为纯 timing；
- `NOT_APPLICABLE`：该 event 不承担可评价的教学时序关系；
- `UNCERTAIN`：当前证据层不足以稳定判断。

Panel A/B 缺少 narration proposition gold 与最终可见证据时，允许且应当使用 UNCERTAIN。不得为了提高完成率强行判断。

## 6. 关键区分

| 证据 | 可以支持 | 不能单独证明 |
|---|---|---|
| compiled/planned start | 系统计划何时发出 event | 浏览器按时执行、对象实际可见 |
| runtime trace | 脚本执行与 target lookup 结果 | 成片中对象清晰可见、教学时机正确 |
| frame | 某采样时刻的画面状态 | 两帧之间的精确出现时刻、连续动画完整性 |
| MP4 | 学习者最终看到的连续呈现 | source attribution 本身正确 |

`target_missing` 是技术证据，不自动等于 MISSING_VISUAL；只有它确实导致教学所需对象在 MP4 中缺失时，才支持该教学标签。

## 7. 分析输出

三层都冻结后，计算：

- A→B、B→C 的 label change rate；
- 从确定变 UNCERTAIN、从 UNCERTAIN 变确定的方向；
- runtime 与 rendered evidence 冲突的事件数；
- target missing 是否在 MP4 中形成可见后果；
- A、B 标注者在各证据层的一致性。

若 Panel C 仍无法稳定给出 observed visibility，结论应是当前证据或定义不足，而不是把 planned/runtime time 当作 rendered interval。
