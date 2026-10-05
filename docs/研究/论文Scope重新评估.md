# 论文 Scope 重新评估

> 日期：2026-10-04  
> 目的：在不推翻教学原则框架、代码审计与 novelty audit 的前提下，补全生成侧，并把第一篇论文收敛为可验证的连续问题。

# 1. 老师四个讨论点如何进入同一研究链

老师讨论的“动态出现、语义对齐、需要 RAG 的关键部分、没有视觉时 AI 生成、布局优化 loop”不是五个平行模块，而是同一生成决策链中的不同位置：

```text
Textbook / Knowledge Source
        ↓
Knowledge Proposition Analysis
        ↓
Visual Necessity
        ↓
Retrieval Triggering / Acquisition Decision
   ├─ no additional visual
   ├─ reuse source visual
   ├─ retrieve external visual
   └─ generate visual（optional）
        ↓
Semantic Proposition–Visual Binding
        ↓
Dynamic Presentation
   ├─ temporal scheduling
   └─ signaling
        ↓
Layout / Rendering
        ↓
Event-level Post-render Evaluation
        ↓
Bounded Iterative Repair（P1）
```

对应关系如下：

| 老师讨论点 | 研究化后的概念 | 链中位置 | 优先级 |
|---|---|---|---|
| 动态出现 | Dynamic Event Planning / Temporal Alignment | binding 之后、render 之前 | P0 核心 |
| 语义对齐 | Proposition–Visual Semantic Binding | acquisition 之后、timing 之前 | P0 核心 |
| 找到需要 RAG 的关键部分 | Visual Necessity + Retrieval Triggering | proposition analysis 之后 | P0 核心 |
| 没有内容时 AI 生成 | Visual Completion Action | retrieve 不适合之后 | P1 optional |
| 布局优化是否 loop | Repair Convergence Control | post-render repair | P1 |

# 2. 当前旧方案哪些保留

保留以下理论与研究基础：

1. Coherence、Multimedia、Personalization、Image 的四原则起点；
2. Temporal Contiguity 与 Signaling 作为动态视频原则；
3. `source evidence → knowledge point → proposition → visual element → visual event → observed evidence` 的研究关系；
4. plan / runtime / rendered-video 三层证据不可互换；
5. event-level human gold、abstention、calibration 与错误定位；
6. technical QA 与 pedagogical compliance 严格分开；
7. P0 / P1 / P2 与 claim retention gates；
8. Doc2Present 正式数据、PresentAgent 实际运行后才可比较、human paired video 只作 ceiling；
9. 双人独立标注、document-level split、cluster-aware statistics；
10. Textbook-to-Video 的版本冻结、feature flag、消融和可复现要求。

# 3. 当前旧方案哪些降级

| 旧定位 | 新定位 | 原因 |
|---|---|---|
| Source-conditioned event-level diagnosis 是最高层技术中心 | event-level evaluation 是生成方法的验证、定位与反馈机制 | 老师关注的生成决策在旧方案中被过度收缩 |
| Source 是 diagnosis 的额外上下文 | Source 支持 proposition、visual need、retrieval、binding、correctness 与 attribution | 更符合生成因果链；source 不是 novelty 装饰 |
| Coherence/Multimedia 主要提供 diagnosis applicability | 先驱动 Visual Necessity / Retrieval Triggering | 连接教学原则与“何时 RAG” |
| Temporal Contiguity 主要检测 EARLY/LATE | 同时约束 generation-time event schedule 与 post-render evaluation | 动态出现必须是生成方法 |
| Signaling 主要检测 WRONG_TARGET | 先决定 need/target/time/duration/competition，再评价 missing/wrong/overload/mistimed | 补回生成侧 |
| P0 尽量不改生产 pipeline | 允许在 feature flag 和 schema version 下修改正式代码 | proposition、binding、event semantics 无法仅靠旁路长期支撑 |
| AI generation 可能是完整流水线的一部分 | P1 optional visual completion | 生成模型本身无足够 novelty，成本高 |
| Repair 是自然的闭环下一步 | P1 bounded repair，重点是 safety/convergence | 通用闭环已拥挤，且依赖可靠 P0 |
| T2V 作为 Baseline A | T2V 是 research platform / ours；旧 commit 只作内部消融 | 避免与“原始 T2V”做伪系统比较 |

# 4. 第一篇论文最终 P0

第一篇论文最多保留两个核心研究问题和一个统一评价层。

## P0-1：Visual Necessity + Retrieval Triggering

对每个 knowledge/narration proposition 判断：

- 无需额外视觉；
- 复用教材视觉；
- 检索外部视觉；
- 仅标为 generation candidate / uncertain。

研究重点是选择性触发，而不是实现普通 RAG pipeline。

## P0-2：Semantic-Temporal Dynamic Alignment

显式建立 proposition→visual object binding，再生成 show/reveal/highlight/focus/transition/remove/dim schedule。Temporal Contiguity 约束 timing；Signaling 约束 cue applicability、target、time 与 duration。

## P0 Evaluation：Event-level Post-render Validation

以 human gold 验证 visual decision、binding、timing、signaling 与最终执行，区分 plan、runtime 和 rendered evidence。该层服务 P0-1/P0-2，不重新成为独立大系统。

# 5. P1 / P2

## P1

- AI visual completion：只在 need visual、source insufficient、retrieval unsuitable、generation applicable 时触发；
- principle-specific targeted repair；
- layout / semantic / temporal regression detection；
- multi-objective acceptance；
- max iterations、history、state hash、rollback；
- repeated-state / A↔B oscillation detection；
- no-improvement stopping。

## P2

- 完整 production provenance；
- broader principles 与跨领域泛化；
- retrieval/generation 的版权和安全；
- presenter 模式下的 Image Principle；
- learner retention、transfer、cognitive load；
- compliance metric 的 construct validity。

# 6. 为什么没有把所有功能都放 P0

1. **Novelty 边界。** PedaCo-Gen、PIVOT、LLM2Manim、When Saying No、CourseBlueprint、AutoCue 等已覆盖通用原则约束、动态规划、成片评价或 repair loop。把所有模块串起来更像 integration。
2. **代码起点。** 当前缺 proposition representation、完整 provenance 和 rendered visibility；先完成必要表示与两个核心决策已经有显著工作量。
3. **实验可证伪性。** Visual Need、Retrieval Triggering 与 semantic binding 可以有明确 human gold 和 baseline；AI 生成质量与 layout loop 会引入模型、美学、资产和多轮优化混杂。
4. **两人团队。** 同时完成生成、检索、图像生成、动态对齐、成片识别、repair 和学习者实验不现实。
5. **因果顺序。** Visual Need 和 semantic binding 不可靠时，后续 timing、signaling 与 repair 都没有稳定目标。

# 7. 新 Research Questions

### RQ1

> How can Coherence and Multimedia be operationalized into proposition-level visual-support and retrieval-triggering decisions for automatically generated instructional videos?

### RQ2

> Can proposition-aware semantic visual binding and dynamic event planning improve visual timing and attention guidance over current sentence-level, lexical, and rule-based methods?

### RQ3

> To what extent can event-level post-render evidence validate visual-support, semantic-binding, temporal, and signaling decisions beyond aggregate scores and direct VLM judging?

若范围继续缩小，RQ3 作为评价协议并入 RQ1/RQ2，不单独声称方法创新。

# 8. 新 Contributions

## Contribution 1：Pedagogically Grounded Visual-Support Decision Formulation

将 Coherence/Multimedia 操作化为 proposition-level visual need 与 reuse/retrieve decision，并用人工 gold 和强 baseline 验证。仅有字段或 Prompt 不构成贡献。

## Contribution 2：Proposition-aware Retrieval Triggering and Semantic Visual Binding

预测何时需要外部视觉，并把候选视觉绑定到 source-supported proposition。只有相对 always/never/direct-LLM/lexical/embedding 有稳定增益才保留。

## Contribution 3：Semantic-Temporal Dynamic Presentation

以 binding 为前提生成 event schedule 与 signaling，而不是用句子位置直接安排动画。必须相对 current semantic timing 证明对象与时间层增益。

## Enabling Contribution：Event-level Post-render Evaluation

以 proposition/object/time gold 验证生成决策。若不优于 aggregate/VLM 的定位或归因，则降为评价协议。

# 9. 真正 Baselines

| 子任务 | Baselines |
|---|---|
| Visual Necessity / Retrieval | Never Retrieve、Always Retrieve、keyword heuristic、Direct LLM、no-source、human oracle ceiling |
| Semantic Binding | lexical/Jaccard、embedding similarity、Direct LLM/VLM、current sentence/element matching |
| Temporal Alignment | legacy timing、current semantic timing、sentence/rule timing、proposition-aware timing |
| Signaling | no explicit policy、rule cue policy、Direct LLM cue policy、proposed binding-aware policy |
| Evaluation | aggregate score、Direct VLM judge、no-source event evaluator、full event evaluator |

Textbook-to-Video 是 testbed，不是 competing baseline。PresentAgent 是实际冻结运行后的外部参照和跨系统泛化对象；Doc2Present human video 是 ceiling。

# 10. 最重要的三个实验

## Experiment 1：Visual Support / Retrieval Triggering

在人工 gold proposition 上比较 always/never/heuristic/Direct LLM/no-source/proposed，测 macro-F1、per-class recall、calibration、abstention、candidate appropriateness 和 retrieval cost。

## Experiment 2：Semantic-Temporal Dynamic Alignment

固定候选视觉，比较 lexical、embedding、Direct VLM、current semantic timing 与 proposed，测 binding accuracy、target accuracy、onset error、window overlap、early/late/missing/wrong-target。

## Experiment 3：End-to-end Ablation and Transfer

在同一 T2V platform 上比较 frozen v1、+visual decision、+semantic binding、+dynamic planning；用 event gold、source fidelity 和 technical QA 评价。若 PresentAgent 可复现，再做跨生成器 evaluator transfer。

# 11. 最危险的三个风险

## Risk 1：Visual Need / Retrieval Need 缺乏稳定 gold

不同标注者可能把“有帮助”与“必要”混淆，或不同学科标准不同。若 pilot 经规则澄清仍低一致性，删除 Retrieval Triggering，退回 Visual Necessity analysis。

## Risk 2：Novelty 被视为 RAG + temporal grounding 的集成

需要证明选择性 triggering、source-conditioned semantic binding 和 event-level human gold带来现有 aggregate/VLM/grounding baseline 没有的能力。单纯 schema、Prompt 或接搜索接口不足。

## Risk 3：范围与数据不足

Doc2Present 只有 30 个 document-level units，两人还要完成生成、标注和实验。必须使用 document-level statistics、最小 gold 和阶段 kill gate；AI generation 与 bounded repair 不得回流 P0。

# 12. 是否需要改论文标题

**建议修改，但在结构化产物 dry run 与正式双人 pilot 通过后正式改。**

旧标题“面向教材教学视频生成的教学原则操作化与事件级诊断”过度强调 diagnosis，不能准确表达新的生成侧中心。候选：

1. **教学原则驱动的教材视频视觉支持决策与语义时序对齐**；
2. **面向教材教学视频的选择性视觉获取与动态语义对齐**；
3. **从知识命题到动态视觉：教材教学视频中的视觉支持决策与事件级验证**。

优先建议第 1 个。它覆盖 Visual Necessity/Retrieval Triggering 与 Semantic-Temporal Alignment，也没有把 AI generation 或 repair 夸大为核心成果。

## Scope Final Decision

**调整后继续。**

第一篇论文的准确一句话定义为：

> **研究教学原则如何驱动教材视频中的视觉支持与检索决策，以及获得的视觉如何与讲述命题进行语义时序动态对齐；事件级成片诊断用于验证这些生成决策。**

G0 字段、ID、目录和 mock 已按 `research-generation-v2-v0.1` 冻结。下一步按以下顺序执行：先用 **5–10 个 proposition 做非正式标签与接口 sanity check**；再完成最小结构化产物、证据导出链，并在 3–5 份文档上 dry run；若存在不兼容问题则发布新版本和 migration，随后冻结正式标注协议；最后开展 **20–30 个 proposition 的正式双人 Visual Support / Retrieval Triggering pilot**。正式标注仍是论文主张的 Gate，但不再阻塞最小代码和数据导出基础；RAG、图像生成与 repair loop 仍不进入这一阶段。
