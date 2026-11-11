# RQ2教学关注绑定最小修正 v1.1（2026-11-10）

基线14f3113；只修正source-conditioned context binding及直接相关比较适配，不开展新实验。依据原研究计划RQ2的proposition→visual object→event依赖，以及《RQ2六句教学表达对照核查_20261110.md》。新方法版本为 `source-context-teaching-focus-v1.1`，沿用现有绑定结果外壳，不改G0契约。历史运行、预测、账本和判词未改。

## 原任务偏差

原Context Prompt无条件追加ACTOR_BINDING_RULES，要求候选是执行者，输入、输出和patient不算匹配；程序只接受唯一SUPPORTED，多个有依据的对象都被视为歧义。原研究目标是适合讲解的视觉关注对象，未要求等同于语法或语义actor。Context因此比Direct/简单基线实际执行了更窄的任务。六句核查中的ri说明这种偏差，但此次没有教材/对象ID特例。

## 修改内容

- `binding_methods.py`：调用 `bind_source_conditioned(..., context_model_fn=...)` 时默认采用教学关注目标，允许actor、patient、input、output、relation。保留actor/action/patient源文角色，不把patient改名为actor。新增关注角色和focus_quote，明确解释候选与命题的语义关系；仍要求来源引文、候选标签、AFFIRMED支持及具体解释。词面分数仅在已有模型语义支持和有效引用后参与旧评分，不负责救回无来源结果；阈值及原权重未改。
- 多个SUPPORTED默认仍拒绑，避免把多个替代答案或不同过程全选。只有显式joint_focus提供同一关系的来源引文、各成员作用，且候选集合恰等于全部已验证支持项，才输出 `BOUND_MULTIPLE`、`selected_candidate_ids`。单目标保留旧 `selected_candidate_id`；多目标此字段为null，绝不挑首项冒充唯一答案。未解决的UNCERTAIN候选使选择拒绑。
- `required_target_role="actor"` 显式保留原actor模式及整份严格引用校验，旧版回归使用该参数。无context_model_fn的旧source-conditioned评分路径不变。新旧方法通过context_method_version区分，旧格式响应不会在新方法里自动迁移为成功。
- 比较runner的新准备包写方法版本；Direct与Judge共享教学关注规则，显式actor配置继续同用actor约束。联合集合按集合匿名分组，不能误当null拒绑；汇总保留状态分布与partial_evidence，不把部分证据隐藏在BOUND总数。未修改任何已冻结比较配置或旧报告。

## 引用错误的原子性

|范围|处理与原因|
|---|---|
|全局JSON/Schema、缺失或未知候选、非法枚举|整份失败：候选空间或结构不可信|
|SUPPORTED或UNCERTAIN候选的引文、角色、标签错误|整份失败：可能改变选择或歧义判断，不能隔离后制造唯一答案|
|联合集合不完整、包含未验证支持候选、关系引文错误|整份失败：关联本身不可信|
|结构合法且明确NOT_SUPPORTED候选的局部引用错误|该行拒绝，保存原行与具体错误，不作为语义排除已验证；保留其他独立有效关注证据。若有有效单焦点返回BOUND_PARTIAL_EVIDENCE，并标evidence_complete=false及rejected_candidate_ids；不声称唯一或穷尽所有合理焦点|
|没有有效焦点且存在局部坏证据|INVALID_CANDIDATE_EVIDENCE，不能包装成合理拒绑|

部分成功不是完整语义审核通过；联合结果也保留局部失败标记。模型给出的语义蕴涵/角色身份仍不能由“引文确实存在”确定性证明，字段和注释继续明确NOT_ENTAILMENT_GOLD。没有忽略错误或补造引用。旧Flows INVALID仍原样保留；本轮没有修改或重评分该响应。

## 能力边界

本次解决的是方法定义与证据处理：合理patient/输入输出可被选作关注对象，有明确关系依据的多对象关联可保存，不再无条件要求actor。它没有解决候选裁剪、输入输出箭头缺失、页面混排、字幕或动态时序。结果显式写 `visual_explanation_status=NOT_EVALUATED`，对象合理不代表视觉解释充分。

多对象只接通绑定结果和比较入口；旧单目标媒体/时序消费者没有在本轮扩展，不宣称BOUND_MULTIPLE已能驱动成片。未来实际比较必须固定共同目标定义、候选和集合评价口径，不用Proposed能多选而Baseline只选一个来制造优势；当前Direct仍保留原单候选输出能力，联合集合仅是新方法的可记录能力，不是已验证的比较增益。

## 离线验证和状态

- 6个直接相关测试文件：83 passed（context教学关注、旧actor、比较入口、source binding及既有自动绑定媒体接线回归）；新测试覆盖5种关注角色、多候选无联合证据拒绑、有效联合与坏联合、局部负候选隔离、支持/不确定候选坏引用整体失败、Schema失败、无来源不调用、无支持不靠词面救回、负极性、旧响应不静默迁移和部分证据计数。
- 保留旧actor回归语义，新增用例是非教材特例的离线工程夹具；不是模型预测或教学Gold。
- development -AllowDirty预检通过，其中项目要求33项检查测试通过；未要求rendering/LLM。当前shell预检未找到ffmpeg/ffprobe，故未验证渲染能力；本轮无需媒体工具。
- binding模块及相关测试Ruff通过；比较runner除E501外通过。runner原HEAD有11个E501，修改后仍有10个原有长行；未顺手重排无关脚本。git diff --check通过。
- 已确认测试使用本工作树src；虚拟环境editable默认曾指向另一旧工作树，最终验证显式设置PYTHONPATH到当前src。首次单独导入触发过LiteLLM公开成本表下载尝试并超时，后续使用本地成本表；这不是模型/健康检查请求。模型、图片、TTS、录制调用均0。

真实模型能否稳定给出合适关注角色和联合关系、局部失败率是否下降、是否优于Direct/简单基线，均未验证。本轮不重新跑六句，不启动RQ1/RQ2实验。只修改绑定模块、必要比较适配和定向测试，新增本方法说明；无关工作树修改保留。未提交或推送。