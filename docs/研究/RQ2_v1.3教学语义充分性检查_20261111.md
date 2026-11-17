# RQ2 v1.3：教学语义充分性检查与有界修正

2026-11-11，开发性验证；分支 `codex/visual-acquisition-handoff-20261030`，HEAD `14f3113`，保留已有工作树修改。本轮不生成图片、音频或视频，不运行 RQ1、Baseline 对比或正式实验。

**结论：新增检查成功拦住了 S3 的“真实引用＋错误关系”绑定，并把错误反馈给原修正循环；绑定模型未能纠正，系统停止且不输出绑定。检查模型仍有区域证据归属错误及借完整图补足选区关系的风险，尚不能保证教学语义可靠。**

## 实现与证据边界

原 `selection_review` 是绑定模型自己的解释。现有 `run_rq2_binding_dev.py` Judge 主要判断来源支持的关注对象，其 `BOUND_SUPPORTED` 明确不证明完整视觉解释，不能直接当本轮的充分性门禁。复用其既有模型传输、图片读取、调用账本和零自动重试机制，增加一个隔离调用。

新方法显式版本：`source-context-teaching-focus-v1.3`；附加检查版本：`context-semantic-sufficiency-v1`。旧 v1.1、v1.1.1、v1.2、旧默认入口与历史结果均保留。

检查者实际获得：

- 完整旁白命题、相关教材来源文本及 source_refs；来源仍通过既有 raw hash、位置和 v1.1.1 定位机制核验。
- 完整原图、全部候选区域的真实像素、稳定 ID 和来源位置、当前选中 ID；图片逐文件验证 hash，模型请求日志记录同一图片。
- 不提供绑定模型的 `selection_review`、支持解释、置信度或前次自审判词。另一次无对话历史的调用使用同一 ecnu-plus 模型系列，不是独立模型系列或独立 Gold。

检查先从教材与旁白提炼必要关系，再分别记录对象相关性、图中支持的关系、缺失关系、不确定性及解释。完整图和未选区域只作上下文，不能替代选中区域的解释内容；明确允许整体图作为一个选中候选。返回 `SUFFICIENT / INSUFFICIENT / UNCERTAIN`，正向证据含来源引文、候选 ID 和具体像素描述。程序核验结构、选中 ID、引文定位和字段矛盾，**不能自动证明图像描述或关系判断是真的**。

`SUFFICIENT` 仅标记 `MODEL_ASSISTED_SUFFICIENT_NOT_GOLD`，保留 `visual_explanation_status=NOT_EVALUATED`。对象绑定通过不等于页面清楚、视频解释充分或学习效果提升。

## 接入修正及兼容方式

原结构与来源校验通过 → 隔离语义检查 → 充分则允许输出；不足或不确定则把必要/缺失关系、证据和不确定性作为定位错误交回原 v1.2 修正循环。反馈不提供预设替代 ID，原候选、来源和回复保持不变；模型可改选、改证据或明确拒绑。

沿用默认最多3轮修正、总时限、单次网络超时和重复失败检测。语义失败不能保留为可输出绑定，也不会回退到未获语义确认的旧选择。检查回复非法或引用不可定位记为不确定，不当作充分；模型选择空集合时，明确记录“未检查空选择”，不声称已经证明拒绑合理。多对象仍使用集合字段，单目标字段不伪造兼容；未修改下游视频接口。

```python
result = bind_source_conditioned(
    proposition, candidates,
    context_method_version=CONTEXT_SEMANTIC_VERSION,
    context_model_fn=existing_binding_callable,
    source_evidence=verified_source_evidence,
    semantic_model_fn=checker_callable,  # (prompt, image_paths) -> raw JSON
    semantic_full_figure={"local_path": full_image_path, "sha256": image_hash},
    initial_context_response=saved_binding_response,  # 可选
    max_repair_rounds=3,
    repair_deadline_sec=480,
)
```

两个调用方继续使用已有传输、账本及网络超时。同步回调的总时限在调用前后检查，不能强行中断不遵守网络超时的任意外部函数。

## 一轮冻结真实验证

调用前冻结代码、输入、候选、选区和判据，未把预期 verdict 发给模型。S1–S3 复用 v1.2 实际回复，不重跑首次绑定。另取已曝光的排名算法来源，构造两个本轮未用作开发的来源派生命题：这是**固定选区的受控检查输入，不是自动绑定预测，也不是独立测试集**。未修改旧实验。

| 案例 | 模型检查和修正的实际结果 | 对照来源及实际裁图的核查 |
| --- | --- | --- |
| S1 解码器＋输出 | 1次检查 `SUFFICIENT`，保留原联合选择 | 来源及输出裁图支持双输出、残差路径与视差分支。检查把分叉结构归到仅含模块标签的 decoder 裁图，区域证据归属不准确；选区集合有基本解释依据，不代表最终画面已验收 |
| S2 投影＋变形 | 1次检查 `SUFFICIENT`，保留原联合选择 | 原文和完整图支持光流引导变形；选中裁图只有标签和箭头端点，完整连接与 feature-map 角色未完整展示。检查描述了超出裁图的连接/Correlation，**存在借上下文补全关系的过度接受风险；选区关系充分性仍不能可靠确认** |
| S3 加权损失 | 第一次 `INSUFFICIENT` → 1次真实绑定修正仍选 Decoder＋Outputs → 第二次仍 `INSUFFICIENT` → `REPEATED_ERRORS` 停止，最终 `SEMANTIC_CHECK_FAILED`，无可输出选中 ID | 原文要求损失项及加权组成，架构裁图只有预测量。拒绝有实际依据。未观察到绑定模型自主改成合理拒绑；这是**系统拒绝错误结果**，不是修正成功或模型学会拒绑 |
| N1 反向梯度差分，仅选前向代码 | 1次检查 `INSUFFICIENT`，与预先判据一致 | 前向选区有原排名，但没有扰动后排名、两者差分及负倒数缩放；完整算法有这些内容，不能借未选部分通过 |
| N2 保存输入和排名供反向使用，选前向代码 | 1次检查 `SUFFICIENT`，与预先判据一致 | 选区和原文均明确写出 `save y and rk(y) for backward pass`，局部关系有据；不是最终页面或视频验证 |

本次 Coding Agent 实际查看了完整排名算法图，以及 decoder、outputs、projection、warping、forward 五个裁图；来源核查非盲、无独立人工 Gold。S1/S2 的模型 verdict 保持原样，核查分歧另存，不修改预测来制造通过或失败。

新 N1/N2 未观察到与预先判据冲突的检查结果；但两条受控命题不足以证明泛化。S2 暴露的可能误接受和 S1 的证据归属问题说明，第二次模型判断仍需证据审阅，不能直接作为真值。没有计算语义准确率。

## 修改、验证与记录

- `src/textbook2video/research/binding_methods.py`：仅扩展修正包装入口和版本参数；原 v1.2 绑定 Prompt、核心选择及证据规范化函数未改变。
- `src/textbook2video/research/binding_semantics.py`：小型独立检查函数，复用来源定位和既有模型回调；无新 Agent 或研究 Schema。
- `tests/test_binding_semantics.py`：13项定向测试，覆盖输入隔离、联合选区、修正、拒绑、不确定、非法引用、范围冲突、图片 hash、重复失败与超时。
- 相关6个测试文件合计 **118 passed**；测试导入清理后新增13项复核通过。development 预检 **33 passed**；触碰文件 Ruff、格式与 diff 检查通过；未跑全量测试。
- 对照 v1.2 最终快照，已有函数只改变 `_bind_context_with_repair` 和 `bind_source_conditioned`；Direct、Lexical、Embedding、绑定 Prompt、布局和时序未改。
- 实际7次请求：6次语义检查＋1次绑定修正；输入58,896、输出3,503，合计 **62,399 tokens**，请求耗时合计129.047秒，费用未知。固定上限23次，余量不补发；自动重试、健康请求、图片生成、TTS、录制均为0。

证据根目录：`.local/rq2-v13-semantic-20261111-01/`。

`freeze.json`、`precall-criteria.json`、`inputs/frozen-tasks.json` 保存调用前条件；`code_snapshot/` 保存实跑代码；`run-01/results/` 保存各轮原回复、语义核查及反馈；`calls.json`、`cost-summary.json` 保存真实调用；`source-review.json` 保存非盲来源/裁图核查；`integrity.json` 保存输入、历史父文件、代码与判据 hash 不变检查。上述 run-01 文件位于同名子目录。

本轮观察到的收益是：新增门禁可阻断一个旧有引用校验无法发现的关系错配，并真实驱动有界修正。未证明绑定算法优势、模型检查可靠性或最终教学表达提升；现有修正模型在 S3 仍失败。全部改动保留在工作树，未提交、未推送，保留无关修改。本轮停止，不追加优化或实验。
