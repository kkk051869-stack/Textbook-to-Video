# VisualPlan契约修复后：一次真实生成验证（2026-11-06）

基线4c1993e。复用原冻结反馈案例、generate决策、来源及页面，不重新调用Visual Decision。Visual Agent运行1次、max_iterations=1，所有真实模型请求硬上限1；未重试、改Prompt、修图或修改生产代码。

## 实际链路

| 阶段 | 结果 |
|---|---|
| VisualPlan响应契约 | 通过，plan_version为visual-plan-v1；既有严格解析器可接受，未做转换 |
| 编译前页面计划校验 | 失败：page plan must partition every existing body element exactly once |
| 视觉资产编译 | 未到达，编译资产0 |
| 语义审核 | 未到达；draft-result的semantic_status为UNCONFIRMED，不能报告语义通过 |
| 局部合成 | 未到达，接纳资产0、新增页面元素0 |
| 双视口页面渲染 | 未到达，无新视觉截图 |

本次模型明确返回正确协议常量，未复现上次“1”的错误；单次通过不等于格式可靠性已统计验证。候选JSON有1个视觉声明，这不是已编译/审核通过的视觉资产。

## 失败定位

原页有heading goal和flow_step steps。模型content_map把goal标为represented，把steps标为irrelevant_to_goal。执行器派生出的page_plan.replaces_element_ids包含[goal, steps]，support为空；页面校验器计算的正文集合不含heading，只有[steps]。替换集合额外包含标题goal，导致partition集合不相等。该异常属于编译前页面计划的一致性检查，不能误写成VisualPlan版本错误、已确认的图语义错误或布局截图失败。

模型认为旧步骤与目标无关，是独立的内容保全风险；本轮不修改其判断，也不把它和触发当前异常的直接集合原因混为一谈。没有让该替换计划修改原页。现有失败门禁生效，原始页面和generate决策不变，适配器记录VISUAL_AGENT_NOT_STRICT_ACCEPTED，命题继续待处理。

按用户约定，本次失败后停止，不修页面计划、不手工改候选、不追加请求，也不继续探查修改后是否会通过其他门禁。没有TTS或录制。

## 固定输入与证据

原输入：`.local/data/runs/visual-need-inference-20261106/feedback/`，五份文件raw/storyboard/graph/source_evidence/decisions复制后逐一验证hash不变。执行图仍仅补现有文件路径与raw hash，未改命题正文、跨度或引用；该适配与上次相同。

新运行目录：`.local/data/runs/feedback-generate-contract-20261106/`。

- frozen_manifest.json、原输入副本、execution_graph.json：冻结输入与定位元数据。
- model-1-request.json、model-1-response.json、usage.json：真实请求与原始回复。
- visual-agent/3d2ab04b891d6cb1/下model-request-0.json、model-response-0.txt、model-envelope-0.json、run.json：模型/执行器过程。
- revision-00/下raw_tool_request.json、request.json（派生page_plan）、structural-base.json、draft-graph.json、draft-result.json、failure.json：失败现场和中间产物。
- selection.json、result.json、summary.json：未接纳状态、失败阶段及输入未变证明。
- 本机脚本`.local/run_feedback_contract_once.py`，无凭据；运行产物不进Git。

## 成本与检查

真实ecnu-plus请求1次：输入6164、输出924、总7088 tokens，请求耗时25.609秒，费用未知；没有第二次请求或预算回避。图片生成0、语义VLM审核0、TTS0、录制0。development/rendering预检33 passed（11.44秒），G0 starter passed；无代码修改，未重复上轮44项测试或运行全量测试。

本轮证实版本契约修复后的真实回复能越过协议解析，并暴露下一个编译前页面计划门禁；仍未证明合格新增视觉能进入教学页面，不宣称图文混排或端到端成功。本轮到此结束。
