# RQ2 v1.1两例真实模型验证（2026-11-10）

结论：固定输入下，v1.1真实执行了两次并通过JSON/Schema/来源引用校验，产生一个patient焦点和一个联合焦点。按代码快照冻结当前v1.1为后续比较候选；这不是通用稳定性、教学充分性或论文优势证据。本轮没有据输出修改Prompt或方法，也没有补发请求。

## 固定条件

- 基线Git HEAD：14f3113572a787ba0580f178cd72399f1fab565d，另有上轮未提交的v1.1修改。本轮完整复制当前代码，不能把基线HEAD冒称实际运行方法版本。
- 方法：source-context-teaching-focus-v1.1；核心binding_methods.py SHA256为 `18e7df86d12364527c8af3fbe3aaaf0e504f98080921836dcb1ccf8222ea0677`。
- 输入：旧Doc2Present RQ2的flows-complex-s1/s2、原source_context、同一完整Figure2及原5个候选；候选hash与旧任务相同，完整Figure2 hash与旧调用账本相同。没有重做教材、旁白或候选。
- 选择依据：已曝光开发案例，专门检查旧actor-only拒绑和引用契约失效之后，新关注角色/联合证据能否真实运行，不是盲测或公平优势对比。调用前expectations.json已固定：ri可作patient关注；SPLIT可作操作关注；其他关系选择须有来源支持，允许合理拒绑。
- 预算2次、ecnu-plus、temperature=0、每次max_tokens=4096、timeout=120秒、底层重试0；不运行Judge、Embedding、Visual Decision或媒体链。沿用既有_call_model账本和绑定入口，仅加本地一次性驱动。

## 实际输出与离线核对

|案例|历史结果（保留）|本轮真实原结果|具体证据与解释|判断边界|
|---|---|---|---|---|
|flows-complex-s1|actor-only拒绑|BOUND → flow-data-ri；attention_role=patient；evidence_complete=true|focus_quote为“operate only on ri”；source_quote为后续层只操作ri、li保持不变的完整句；解释ri是操作作用于的数据分支|关注对象合理，程序引用校验通过；单个ri裁片不能充分表达ri/li对比，不宣称视觉教学完成|
|flows-complex-s2|整体INVALID，原模型已识别SPLIT，但其他候选引用错误|BOUND_MULTIPLE → flow-split + flow-data-ri；evidence_complete=true|SPLIT为actor，ri为patient；joint_focus引用SPLIT分两路、后续层只处理ri及li不再变换的原文，解释操作与另一分支的对照关系|联合选择有上下文依据，但该句主述是li固定，ri只是对照；解释中“Both objects are necessary”强于证据。候选缺少li，不能把集合视为完整或唯一必需解释|

两份输出均无被隔离候选（rejected_candidate_ids为空），所以这次没有真实触发BOUND_PARTIAL_EVIDENCE，不能据此声称局部错误隔离机制已在真实模型中验证。所有提交候选的来源和角色引用均通过现有校验；语义合理性的上述判断为非盲工程审阅，不是独立Gold。

联合焦点已经真实返回并进入现有绑定结果，但尚未接通多目标媒体消费者。本轮没有页面截图或视频，不证明裁剪、布局、时序已解决，也不以原视频证明这次新预测的效果。

## 调用和验证

|请求|输入tokens|输出tokens|合计tokens|服务请求耗时|费用|
|---|---:|---:|---:|---:|---|
|s1|3622|858|4480|41.516秒|未返回|
|s2|3628|1370|4998|34.781秒|未返回|
|合计|7250|2228|9478|76.297秒|未知，不估算|

实际2/2次传输OK、2/2次新契约校验通过，无重试，预算耗尽后停止。0 Judge、0新Embedding、0图片、0TTS、0录制、0模型健康检查。development -AllowDirty -RequireLLM预检通过，仅检查凭据存在，不进行健康请求；预检内33项测试通过，未重跑上轮83项绑定测试或全量测试。当前shell的预检未找到ffmpeg/ffprobe，不影响本次绑定验证，不表示媒体工具验收。

运行前后冻结输入和代码hash相同，protocol的SHA256为 `1fa7e4b766ccad9ce9f8fed6da3823f212f3afcb422b499bc03415c67f3056ea`。git diff --check通过。没有修改生产逻辑、Prompt、旧预测、原账本或原实验数据。

## 冻结和证据入口

完整本地目录：`.local/rq2-focus-v11-smoke-20261110-01/`（本工作树内，未上传）。

- `protocol.json`、`expectations.json`：事前输入/代码hash、判据和预算；`inputs/`：固定任务、来源PDF/页面及原图候选；`code_snapshot/`：实际运行源码。
- `run-01/prompts/`、`run-01/calls.json`：真实请求和原始回复、usage及失败字段；`run-01/results/`：未经人工改写的新绑定输出；`summary.json`和`integrity.json`：调用和完整性结果。
- `freeze.json`：状态SMOKE_PASSED_FROZEN_CANDIDATE，保存方法代码、协议和结果hash。freeze文件SHA256：`4f9a04ef5c428575ba38b33bab54203318fd11e25b6c16302a304f10e025b10b`。
- 本地驱动 `.local/rq2_focus_v11_smoke_20261110.py` 已随快照保存；execute有独占锁，不允许再次执行同一运行。

冻结指可追溯代码候选快照，不是Git发行版或正式实验配置；当前方法代码仍未提交/推送。这两个已看过的案例不足以估计跨案例稳定率。后续是否开展相同教学目标、候选集合与输出粒度下的公平比较仍待决定，本轮不自动启动。