# Novelty Decision

## 1. 最危险的 10 篇近邻工作

| 排名 | 工作 | 危险点 |
|---|---|---|
| 1 | [PIVOT](https://arxiv.org/html/2609.24083) | 已覆盖 pedagogy→storyboard→rendered verification→iterative repair；直接否定宽泛闭环。 |
| 2 | [EduVideoBench](https://arxiv.org/html/2605.26918) | 已有专家生成视频 benchmark、六条 Mayer rubric 和自动可观测指标；直接否定通用原则 benchmark。 |
| 3 | [PedaCo-Gen](https://arxiv.org/html/2602.19623) | 已把 12 条 Mayer 原则操作化为结构化生成约束；直接否定通用“原则→约束”。 |
| 4 | [When Saying No Makes Better Videos](https://arxiv.org/html/2608.19812) | 已在最终成片上自动评价 coherence、temporal contiguity 等原则；直接否定通用成片 checker。 |
| 5 | [AutoCue](https://arxiv.org/html/2608.04910) | 已实现 timestamp/ROI/narration/manual evidence/confidence/cue-target alignment，并有专家金标和学习者实验。 |
| 6 | [CourseBlueprint](https://arxiv.org/html/2606.20608) | 已有 typed instructional contract、课程语料 grounding、chunk/slide provenance 和 rendered evaluator。 |
| 7 | [LLM2Manim](https://arxiv.org/html/2604.05266) | 已将 Segmenting/Signaling/Temporal Contiguity 用于生成，连接 narration cue 与 visual event，并报告真实学习结果。 |
| 8 | [Code2Video](https://arxiv.org/html/2510.01174) | 已有对象/anchor/code-line 可追踪、局部 ScopeRefine、rendered critic、重渲染和 TeachQuiz。 |
| 9 | [CogniPresent](https://openreview.net/pdf?id=PinJSxPLUD) | 已明确提出 CTML-guided paper-to-presentation contracts、source figures、互补叙述和 pacing；虽未归档，仍是 prior-art 威胁。 |
| 10 | [Teaching Step by Step](https://link.springer.com/chapter/10.1007/978-3-032-29788-4_73) | 已用 Segmenting/Signaling 约束规划，并以 AST lint + Vision Auditor 双循环检查；正文细节待精读。 |

## 2. 能做 / 不能做的 contribution claims

### 不能做

- “将 Mayer 原则用于 AI 教学视频生成。”
- “把教学原则转成 machine-executable contract/schema。”
- “自动评价最终视频是否遵循 Coherence/Temporal Contiguity 等原则。”
- “checker→repair→rerender 构成新闭环。”
- “从教材/文档自动生成有声教学视频。”
- “建立通用 pedagogical video benchmark/compliance score。”
- “建立 narration–visual alignment”而不限定粒度、source condition 和人类金标。

### 仍可做，但必须收窄

- **source-conditioned event-level diagnosis**：教材证据→讲述命题→视觉对象→实测可见区间→违规定位/证据/置信度。
- **event-level violation benchmark**：仅限生成教学视频、1–2 条原则、自然错误+单一受控注错、人工事件金标和 IAA。
- **principle-specific repair safety**：必须同时测目标修复、新错误、source fidelity 和技术回归，并与 generic repair/full regeneration 比较。
- **compliance construct validity**：验证自动原则分数是否预测专家事件金标和真实学习结果；不能用 VLM 当学生。

## 3. 最终 3 个候选创新点

1. **教材证据条件下的事件级教学音画违规诊断**：定位 source-supported narration proposition 所需视觉对象是否在正确时间可见/被指示，并输出证据与校准置信度。Novelty confidence：**MEDIUM-HIGH**；feasibility：**HIGH**。
2. **原则特异的最小局部修复与 repair-safety 评价**：针对已定位违规做受约束局部编辑，并联合评价成功、新错误、source fidelity 和技术回归。Novelty confidence：**MEDIUM**；feasibility：**MEDIUM**。
3. **自动原则合规指标的构念效度与学习结果验证**：检验自动 CTML 分数能否预测专家金标、认知负荷、保持和迁移。Novelty confidence：**MEDIUM**；feasibility：**LOW**。

## 4. 推荐的 1 个方向

**Candidate 1：教材证据条件下的事件级教学音画违规诊断。**

## 5. 推荐理由

- 它避开了已拥挤的 contract、整片 checker 和通用 repair loop。
- 可用明确人工金标、F1/temporal IoU、evidence accuracy 和 calibration 证伪。
- 与现有 source refs、knowledge points、narration、element IDs、timeline 和最终渲染产物匹配。
- 不必先承担大规模学习者实验或完整自动修复的成本。
- 最近邻虽强，但尚无公开证据显示单篇工作已完成相同的 source-conditioned、event-level、human-validated CTML diagnosis。

## 6. Kill Condition

- 发现已有工作同时具备生成教学视频、教材 grounding、命题—对象—时间区间金标、CTML 违规定位和 validated detector。
- pilot 标注在规则澄清后仍无可接受 IAA。
- source-conditioned 方法相对无 source baseline 无稳定增益。
- 通用 VideoLLM/temporal-grounding baseline 已接近人工上限。
- 任务只能依赖本项目内部 metadata，不能从其他系统的最终 MP4 评价。

## 7. 下一步动作

1. 在实现前精读 PIVOT 附录/代码、AutoCue Supplement 3–4、EduVideoBench annotation/rubric、When Saying No 指标、CourseBlueprint schema/evaluator、CogniPresent 最新版和 Teaching Step OSF。
2. 用一句精确任务定义再次做题名/摘要/全文检索；重点查 `source-conditioned event-level pedagogical violation localization` 及同义词。
3. 先做 20–30 个片段的双人标注 pilot，验证 violation definition、temporal boundary 与 evidence chain 的 IAA。
4. 只在 IAA 与 source-ablation 均通过后冻结 research scope；否则按 Kill Condition 换题。
5. 当前只冻结问题边界：最终渲染视频、Temporal Contiguity + Signaling、事件级诊断；暂不冻结方法，不把 repair 列为第一篇小论文的必要贡献。
