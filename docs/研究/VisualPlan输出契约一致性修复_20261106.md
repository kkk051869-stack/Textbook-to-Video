# VisualPlan输出契约一致性修复（2026-11-06）

本轮模型调用0、视觉生成0、语义审核0；未重跑跨帧反馈案例。只修正模型可见的协议要求及其与现有解析器的一致性。

## 根因

既有visual_plan_contract将协议值放在version字段，required_fields却要求响应中的plan_version。系统Prompt仅要求遵循allowed/required字段，没有直接说明plan_version必须取哪个常量，也没有可供对照的响应字段Schema。真实回复把它误写为“1”。契约常量与校验器并非取值冲突，问题是模型可见的映射不够明确。

当前调用使用response_format=json_object。它限制JSON语法，不保证字段常量、必填项和类型。LLM客户端允许透传response_format，但代码/既有运行不能证明当前模型网关支持严格json_schema；本轮禁止模型调用，因此保持现有json_object，不进行能力探测或静默回退，不宣称服务端结构化约束已接通。

## 实际修改与元数据取舍

- visual_model_interface.py：由现有模式字段表及同一VISUAL_PLAN_VERSION生成response_schema，明确plan_version为string且const=visual-plan-v1，列出各模式required、允许字段类型并禁止额外根字段。提示Schema与本地类型检查共享_PLAN_TYPES，避免两处漂移。
- visual_tools.py：现有系统提示明确遵循response_schema中的固定协议常量，不能缩写为数字或使用修订轮次。
- 版本值确属协议元数据，不是模型规划内容。程序现在统一生成这个固定要求；保留既有版本化响应接口，不自动补填缺失版本或覆盖错误版本，以免将不明协议/旧响应误当成当前版本。若未来改为执行器封装协议头，应显式迁移模型边界，本轮不引入另一种响应格式。
- VISUAL_PLAN_VERSION、各模式必填字段、允许字段及严格解析结果不变。节点、边、来源、关系枚举和模式选择不变；根响应Schema不冒充完整图语义Schema，嵌套内容仍须通过原有结构、来源及语义门禁。没有修改角色约束、图规划、修订或页面合成逻辑。

此修改按执行器模式构建，适用于不同教材、全候选、对象更新及受限编辑模式，不含任何跨帧反馈样例规则。

## 离线验证

定向测试44 passed（16.01秒）：覆盖7种执行器模式的合法响应、错误版本字符串/数字/null/未知版本、缺少版本或必填字段、非法字段和字段类型；验证提示Schema与严格解析器对这些输入一致。合法协议头下的非法节点结构仍由既有check_structure拒绝。真实调用入口的mock回归确认新契约进入请求，response_format继续为json_object，未引入模型传输。

development预检33 passed（8.95秒），G0 starter passed；diff检查通过，未跑全量测试。

历史真实回复离线重放：`.local/data/runs/feedback-generate-once-20261106/visual-agent/3d2ab04b891d6cb1/model-response-0.txt`，SHA256=fc0e0c017de7e52e9890da2718b816abca0fb3ed58d33b67d3dbb86a237cb99a。原plan_version仍为“1”，解析器依旧返回“plan_version must be visual-plan-v1”，Schema也报告常量不符；没有更改历史回复。新旧契约的allowed_fields和required_fields离线比较相同。

本轮重放证据保存在`.local/data/runs/visual-plan-contract-offline-20261106/replay.json`及contract.json。已有失败没有被升级为通过。

## 未验证边界

尚未通过真实模型确认明确后的格式能否稳定遵循；没有验证网关严格JSON Schema能力、候选的真实编译、语义正确性、合格资产或局部图文合成。本轮只交付更明确且同源的输出协议说明及严格离线验证，不宣称视觉生成链路已经成功。
