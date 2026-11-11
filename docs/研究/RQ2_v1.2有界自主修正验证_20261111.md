# RQ2 v1.2：联合关注选择与有界自主修正

日期：2026-11-11。分支 `codex/visual-acquisition-handoff-20261030`，起点 `14f3113`，开发性验证。

本轮实现了可运行的自主修正流程，但没有证明绑定语义已可靠：三个旧失败案例中，两个获得来源相容的选择，另一个仅通过程序校验，仍存在损失与预测量的语义混淆。不能据此宣称方法优势或全部恢复。

## 1. 失败机制与修改范围

旧入口的一次模型回复若引文或结构非法，会直接抛出异常，没有将错误交回模型的修正流程。旧联合规则要求 `joint_focus.candidate_ids` 等于全部经过校验的 SUPPORTED 对象，混淆了“可用替代对象”与“本次需要共同关注的成员”。完整图与局部模块均有依据时，也会因此拒绝合理子集。

新增独立方法版本 `source-context-teaching-focus-v1.2`，继续使用 `context-evidence-v1.1.1`，没有覆盖 v1.1 默认行为、历史 Prompt 或六项原实验结果。生产修改仅在 `src/textbook2video/research/binding_methods.py`；增加定向测试 `tests/test_context_binding_repair.py`。Direct、Lexical、素材、布局、时序与视频模块未修改。

在原响应上增量明确选择集合和关系自审，没有新增绑定框架：

| 概念 | v1.2 规则 |
| --- | --- |
| SUPPORTED | 候选有模型声称的语义支持且引文通过定位，可作为替代对象；不要求入选 |
| SELECTED | `selected_candidate_ids` 明确指定本次关注集合，必须属于校验有效的 SUPPORTED 集合 |
| JOINT_REQUIRED | 多对象选择须以原 `joint_focus` 解释共同关系，成员恰好匹配选择集合；返回 `joint_required_candidate_ids` |
| 充分性与必要性 | `selection_review` 说明关系覆盖、每名成员作用和集合最小性，附可定位引文；不充分或不确定时允许空选并说明 |

最小性和关系充分性目前仍是模型自审，不是程序完成的独立语义证明。程序不会自动把错误关系改成正确关系。正常支持但未选择的候选不强制入组；未选择候选的局部证据错误会保留为警告/被拒行，不当作有效证据。选中候选证据非法、未知 ID、未知角色、联合集合冲突仍严格拒绝。

## 2. 修正流程、边界与兼容性

首次生成或保存回复 → 校验 → 反馈 JSON 路径、错误码、候选 ID、来源位置和前次原回复 → 模型完整重答 → 再校验。结构校验可一次列出独立错误，来源定位继续保留原文、原始 span 和 hash。反馈始终保留同一命题、所有原候选及来源，不给出预设正确对象。

- 默认最多 **3 轮修正**，因此全新生成最多4次请求；复用历史回复作为第0轮时，最多3次新增请求。
- 相同字段/错误码再次出现或原回复重复时提前停止；有调用上限、案例总时限及调用异常终止状态。实际模型传输复用既有账本、请求前预留和 SDK 零自动重试。
- 案例总时限默认480秒；同步回调须在既有模型入口设置单次网络超时，本次为120秒。总时限在回调前后检查，不能强行中断不遵守超时的任意外部回调。
- 输入 hash/位置损坏不交给模型“修来源”，在调用前终止。没有充分对象时可合理拒绑。
- 完整保留各轮 Prompt、原回复、错误、选择和调用次数。修正耗尽或失败时，若保留此前局部证据有效的选择，会以 `selected_from_round` 和警告标明其出处；不会将最后一次无效回复伪装成有效回复。
- 单对象继续返回 `selected_candidate_id`；多对象该字段为 null，集合另存，标记 `MULTI_TARGET_ADAPTER_REQUIRED`。本轮没有改下游为多对象视频呈现。
- 所有结果标记 `MODEL_SELF_REVIEWED_NOT_INDEPENDENTLY_PROVEN`，`visual_explanation_status` 仍为 `NOT_EVALUATED`。程序校验通过不等于关系成立或画面解释充分。

显式使用新版本：

```python
result = bind_source_conditioned(
    proposition, candidates,
    context_model_fn=existing_model_callable,  # 调用方使用既有超时和账本
    context_method_version=CONTEXT_REVISABLE_VERSION,
    source_evidence=existing_source_evidence,
    max_repair_rounds=3,
    repair_deadline_sec=480,
    # 可选 initial_context_response=saved_raw_response
)
```

## 3. 六份原始回复的离线回放

证据根目录：`.local/rq2-v12-repair-20261111-01/`。未向旧回复补写选择集合或“正确答案”。旧回复缺少 v1.2 的显式选择/自审字段，因此新契约回放只产生诊断，不声称离线自动恢复成功。

| 案例 | 保留的 v1.1.1 结果 | 离线诊断的实质问题（另有新字段缺失） | 本轮真实修正 |
| --- | --- | --- | --- |
| scene-decoder-outputs | INVALID | 输出区域两处引文不可定位 | 2次请求后程序通过；选择解码器＋输出 |
| scene-flow-warping | INVALID | 旧联合规则混淆完整图替代项；action 在新契约明确允许 | 1次请求后程序通过；选择投影＋变形 |
| scene-loss-components | INVALID | 输出对象 focus 引文不在该行证据内；另有损失/输出混淆 | 1次后程序通过，教学关系核查仍失败 |
| rank-gradient-algorithm | INVALID | 旧联合规则要求纳入完整算法替代项 | 未发新请求 |
| rank-pronoun-implication | BOUND_MULTIPLE，部分证据 | 未选数学对象的两处引文不可定位 | 未发新请求 |
| rank-forward-for-backward | INVALID | forward 行的 action_quote 不在其所交引文内 | 未发新请求 |

旧 v1.1.1 的5失败＋1部分可用与原回放一致；原 v1.1 的0/6研究结果没有修改。全部历史父输入、模型回复和图像 hash 核对未变。工程夹具验证了子集选择、角色、改选、拒绑、重复失败、超时及旧接口兼容，不作为真实模型能力证据。

## 4. 一轮真实修正与语义核查

调用前固定三个已有问题案例、原始来源和全部候选图像，分别覆盖引文失败、联合替代项、语义混淆。复用 v1.1 的无效回复作第0轮，属于协议演进下的开发性修正验证，不是 v1.2 新输入首答成功率，更不是独立泛化实验。

本次 Coding Agent 已实际查看 `inputs/scene-complete-region.png` 完整原图，结合原文及此前冻结的教学要求核查；这是非盲的来源审阅，无独立人工 Gold，也没有另调用 Judge。

| 案例 | 实际修正与结果 | 来源核查与剩余缺失 |
| --- | --- | --- |
| 解码器输出 | 第1轮仍有拼接/定位及角色证据错误；反馈后第2轮修正引文，选择 `scene-decoder`＋`scene-outputs`；完整图仍 SUPPORTED 但未强制入选 | 原文明确同时输出残差场景流和非残差视差；完整图显示对应解码器与输出，选择有依据。输出裁图也包含最终 Scene Flow，尚未检验最终呈现是否清楚区别这些量 |
| 光流引导变形 | 第1轮选择 `scene-projection`＋`scene-warping`，没有强制加入仍 SUPPORTED 的 `scene-figure` | 原文与完整图支持“投影成光流→引导特征变形”路径；对象集合合理。没有验证后续关系箭头、特征图关注或视频可读性 |
| 加权损失 | 第1轮选择 `scene-decoder`＋`scene-outputs`，自称 SUFFICIENT；引文确实可定位，程序返回 BOUND_MULTIPLE | **语义不通过。** 命题是视差损失与场景流损失的加权和，所引文本和 Figure3 只证明预测输出，不能证明损失项及权重关系；“产生预测量”不等于“表达损失分解”。原预测和错误自审均保留，没有手工改绑或投入下游 |

因此，观察到自主修正能恢复两例来源相容的关注选择；同时仍观察到一次“可定位引用＋错误关系推断”被程序接受。**本轮没有解决自动语义误接受，不能把三例 BOUND 当作三例教学成功。** 这项限制也不能靠放宽格式校验解决。

成本：4次实际模型请求（预算最多9次，余量不补发），58,778 tokens（输入53,262／输出5,516），请求耗时合计172.811秒，费用接口未提供。自动重试、健康请求、图片生成、TTS、录制均为0。

## 5. 验证记录及证据入口

- 相关5个测试文件：**105 passed**，其中新修正测试28项；旧相关回归77项保留通过。
- development `-AllowDirty -RequireLLM` 预检：**33 passed**，凭据仅存在性检查；ffmpeg/ffprobe 未在 PATH，本轮不做媒体，未要求 rendering。
- 修改文件 Ruff 检查、格式检查及 `git diff --check` 通过；未跑全量测试。
- 与本轮开始前代码快照比较，已有函数仅 `_bind_context_relations` 和 `bind_source_conditioned` 改变，Direct、Lexical、Embedding 与证据规范化函数未改。
- `offline/summary.json`：六份历史回复回放；`run-01/results/`：三例逐轮输入、回答、错误与最终结果；`run-01/calls.json`：真实调用账本；`run-01/source-review.json`：独立于程序返回值保存的本轮来源核查；`run-01/evidence-integrity.json`：父输入 hash 和选中引文原文定位核验；`run-01/cost-summary.json`：调用统计。
- `freeze.json`、`code_snapshot/` 为真实调用时快照。调用结束后仅纠正两处审计文案（未选择行拒绝标签、最终 rationale），没有改决策、校验或 Prompt；`final-implementation.json` 和 `final_code_snapshot/` 保存最终实现及元数据差异核验。

当前改动保留在工作树，未提交、未推送，未覆盖原有无关修改。下一阶段是否继续优化或做比较，需另行决定；本轮到此停止。它对研究问题的意义是消除了“所有可用对象都必须联选”的程序性混淆，并提供可审计的纠错机会；尚未证明语义绑定质量、独立泛化或最终教学表达效果提升。
