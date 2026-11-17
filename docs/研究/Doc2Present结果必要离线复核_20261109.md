# Doc2Present结果必要离线复核（2026-11-09）

基准9a026ac。本轮只检查已有结果，模型/配音/录制0，不改生产代码、来源、阈值或原预测。Release已校验SHA256，独立解包D:/t2v-audit/20261109-release/doc2present-local-dev-20261109；媒体索引162个引用hash全部匹配。初次长路径解包失败现场保留，短路径解包成功。审计合同与结果在仓库.local/offline-review-20261109/。

## 重点提示消融：本批没有触发处理差异

三文档proposition_aware与without_signaling的compiled.json内events数组去掉event_id后完全相等；不指整个compiled文件或HTML字节相同。dynamic-plan中DVC/Factorized均只有show/show/dim，Flows无对象事件，没有focus。

runner的without_signaling只过滤focus；planner中的dim标记signal_action=NO_SIGNAL、decision_reason=target_no_longer_relevant，属于cleanup。planner只在同一对象关联的后续命题上进入提示选择，这批4条有效绑定各指不同对象，未进入该分支。因此当前证据是“没有触发提示的样本上，两条件没有实际处理差异”，不是“已经证实开关坏了”。本批不能评价signaling增益；如果论文把dim也定义为signaling，则当前消融只去focus的操作定义与论文定义需先统一，但不能事后改旧条件或重标旧视频。

不为制造差异添加提示/换样本/重录。本批消融标NO_TREATMENT_CONTRAST，保留原视频和事件。

## 六条绑定核查

| 命题 | 现有context结果 | 离线判断 |
|---|---|---|
|dvc-complex-s1|Motion Compensation Net|原文直接说明motion compensation network获取预测帧，候选标签对应|
|dvc-complex-s2|Residual Decoder Net|原文说明quantized representation送入residual decoder，候选对应|
|factorized-complex-s1|HDR Decoder|上下文通过sky decoder作为HDR prior解释this decoder；与候选对应，仍保留指代核查范围|
|factorized-complex-s2|Shadow MLP|原文明确点名shadow MLP，与候选对应|
|flows-complex-s1|拒绑|候选ri是被操作的数据，不是执行操作的layers；符合当前actor-only条件，但不能推广为ri不适合作一般讲述的视觉关注对象|
|flows-complex-s2|INVALID_RESPONSE|不是合理拒绑，也不是模型未识别SPLIT；见下|

以上为工程来源/候选对应核查，主执行实际查看6张候选裁剪图；不创建人工Gold或方法正确率。前4条context与lexical/Direct选相同对象，仍无相对增益证据。候选裁剪图主要是模块标签，不能据此认定完整输入输出关系已被教学画面表达。

Flows第二条原调用context:flows-complex-s2（call_id13）中，flow-split明确SUPPORTED。但flow-squeeze这个NOT_SUPPORTED候选的source_quotes只有“SQUEEZE trades off spatial resolution for channel depth”，actor_quote却为“the SQUEEZE operation”、action_quote为“transforms”、patient_quote为“it”，三者均不在提交引文中。校验器对所有提交角色引用检查，因此整个预测无效。原INVALID保留，不删除干扰候选、不修原回复或人工填SPLIT。这是“局部证据格式失败导致整份输出失效”，不能混为语义选错。

## RQ1及后续边界

RQ1仍23/54输出、Judge0/24，接口失败后停机；本轮不resume或补发。no-source条件因缺source_refs被前置门禁全部拒绑，体现程序依赖，不能单独解释成来源让模型更懂语义。

必要检查已结束。现有RQ2请求/14个MP4无需重跑，15个计划条件的分母不变，遗留raw仍未恢复。本轮未开展所有最终帧/连续音轨验收。不启动正式批量。若下一步补RQ1，应另建冻结运行、复用成功输出并明确失败分母；若要评价signaling或actor-only之外的视觉绑定，应在新任务先固定操作定义，不继续修这批样例。
