# f11 短期探索性评价（开发样本，2026-11-15）

结论：已完成冻结输入的一轮 RQ1/RQ2 对照与双 Judge 评价，以及既有 f11 视频的抽帧核查。**尚无可靠证据证明 Proposed 优于 Direct 或简单基线，不应直接进入正式规模实验。** 工程执行已打通，但来源上下文过短、候选图关系缺失、Judge 不确定/不一致及连续焦点保持问题仍影响结论。

## 1. 冻结、选样与方法身份

证据包：`D:/Code/vibe coding/Textbook-to-Video/.local/runs/e01/`。主输入为同一份 flows.pdf，第 1–15 页；SHA-256 为 `a8e4c9326d29a76715da00af8c9332f0af1081d7ef5649dd339c7a4a1688d55e`。f11 MP4 为 315.933333 秒，1600×900，SHA-256 为 `9c902926b8bd0de929152b238b8399fa444b472910b41394f99c3370930629af`。

源码 HEAD：`b5f4714ee1f8df4cfb66e68f1b76d50ab0219c83`，分支 `codex/joint-visual-planning-spike-20261113`；存在既有未提交修改，HEAD 不能单独代表运行代码。保存了 166 个源码/Prompt/配置文件、工作区差异与版本清单。f09、f11 及原始上游运行共 1000 个文件形成内容哈希清单；结束时全部复核无变化。媒体在原路径按哈希冻结，未复制成另一套视频；教材和评价方案另有副本。完整 provenance 见 `source-version.json`、`frozen-results-manifest.json`、`integrity-after.json` 及保留的 f09/f11 运行清单。

`protocol.json` 在新比较调用前固定：RQ1 为全部 4 条实际 generate，加第 2/5/6/7/8/10 页各第一条 none，共 10 条；RQ2 固定原审计第 11/12/13/14/15/17 行，共 6 条，覆盖像素依赖、高斯拒绑、Conv-LSTM、SQUEEZE 失败、SPLIT 成功和实验表格。所有样本已用于研发或被查看，均非盲测/独立测试。没有为任何方法修改输入、候选或旧结果。

重要边界：

- f11 普通视觉增强 `research_condition=null`，保留其全部真实结果，**不重标成正式 RQ1 Proposed**。本轮另以现有 `research_condition=proposed/direct_llm` 接口在同一冻结来源、同一原页资产资格下作决策层对照。两者都不启用普通入口的原生组件充分性扩展，故该对照不证明 f11 页面增强策略孰优；原页充分性仍有接口范围限制。
- RQ1 未新检索或生成任何素材。Never/Always 是策略输出；retrieve 不等于检索成功。输入来源清单没有可复用图片，未验证 reuse；也没有外部检索 catalog。
- RQ2 复用 Proposed v1.3 原结果及最多 3 轮修正，Direct 只调用一次；不能宣称等成本优势。Direct 复用此前已授权的多对象输出适配，不改语义规则。Lexical/Embedding 本身为单候选方法，集合能力差异保留。
- Judge A=`ecnu-plus`，响应模型 `qwen3.8-flash`；B=`ecnu-max`，响应模型 `deepseek-flash`。匿名方案、同一来源/像素、独立调用；B 与生成方法同系列，仍有偏差。模型裁判不是 Gold。

## 2. f11 全量盘点

RQ1：27 条决策＝none 23、generate 4、reuse 0、retrieve 0；4 条生成均已尝试，4 张 SVG 编译并进入第 1/3/4/9 页及 f11 MP4。原审核 ACCEPT 1、REVISE/带告警使用 3，不把采用等同通过。完整原始决策、资产 hash、审查与被排除关系见 `inventory/rq1-all.json`、`inventory/rq1-assets.json`。

| 页 | 素材 | 原审核/采用 | 本轮 Judge A/B | 实际问题 |
| --- | --- | --- | --- | --- |
| 1 | 可逆变换→高斯基分布 | REVISE / used_with_warning | ACCEPT / ACCEPT | 正向映射清楚；没有逆向关系，不能单凭图证明可逆操作 |
| 3 | 像素上下文 | REVISE / used_with_warning | REJECT / REVISE | 4 条输入关系被局部排除，剩下顺序链；“随后”不自动等价于条件依赖全部前序像素 |
| 4 | Conv-LSTM→参数→高斯条件 | ACCEPT / validated（模型级） | REVISE / ACCEPT | 结构总体可读；当前绑定没有同时关注均值/方差输出节点，来源窗口也未含完整参数关系 |
| 9 | 潜在空间分解 | REVISE / used_with_warning | REJECT / REVISE | 排除关系后存在孤立节点；部分通道依赖/分解关系表达含混 |

本轮资产 Judge 完全相同判词仅 1/4；二值 ACCEPT/非 ACCEPT 相同 3/4。A 严格 ACCEPT 为 1/4，B 为 2/4。它们评价的是既有素材像素，不是所有对比方法各自生成资产的质量。

RQ2：32 个绑定任务＝BOUND_MULTIPLE 9、BOUND 4、关系不足拒绑 6、SEMANTIC_CHECK_FAILED 3、SEMANTIC_UNCERTAIN 1、BINDING_FAILED 9。另有第 8/10/11 页因无可寻址视觉对象跳过。9 个技术失败为组件截图提取器不支持原生组件，不能计为合理拒绑。13 个接纳绑定组均进入动态计划，形成 50 条目标级 focus；没有本轮已接纳组因 focus 数量预算而被删。全量原回答、修正轮次与失败见 `inputs/rq2-full-report.json`、`inventory/rq2-all.json`。

## 3. RQ1 评价表

| 方法 | 决策输出/总数 | 实际动作 | Judge A/B 可接受/总数 | A/B 判定一致/可比项 | 素材适用性 | 不确定/无效 | 成本 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| never_retrieve | 10/10 | {'none': 10} | 7/10；3/10 | 3/10 | 未运行获取；无素材效果比较 | A:0不确定/0未归类；B:4不确定 | 实际 tokens 见 costs.json |
| always_retrieve | 10/10 | {'retrieve': 10} | 9/10；3/10 | 3/10 | 未运行获取；无素材效果比较 | A:0不确定/0未归类；B:4不确定 | 实际 tokens 见 costs.json |
| direct_llm | 10/10 | {'generate': 7, 'none': 3} | 8/10；5/10 | 5/9 | 未运行获取；无素材效果比较 | A:0不确定/1未归类；B:4不确定 | 实际 tokens 见 costs.json |
| proposed | 10/10 | {'generate': 4, 'none': 6} | 6/10；3/10 | 5/10 | 未运行获取；无素材效果比较 | A:0不确定/0未归类；B:4不确定 | 实际 tokens 见 costs.json |


口径：可接受数除以固定 10 条，不是准确率；Judge B 有 4 条全局 abstain，全部保持不确定，**即使原回复的 acceptable 数组也列出所有方案，也不计作接受**。Judge A 对 Direct 有 1 条未归类。匿名等价提议按现有 canonical 机制合并；一致数统计 A/B 标签相同，不等于正确。2 个事先选定项目各做双 Judge 顺序交换：4 对中 2 对可接受集合改变，2 对偏好集合改变，保留首次结果，不择优替换。

Direct 请求 generate 7 次，正式 Proposed 4 次；这仅是策略差别。两者没有在本轮取得新的生成素材，不能比较实际素材成功率，更不能据低调用比例宣称视觉必要性更准确。逐项命题、来源编号、动作、判词、匿名映射见 `rq1/case-table.md`、`rq1/cases.json` 和原始 `calls/`。

## 4. RQ2 评价表

| 方法 | 总数 | 绑定/拒绑/失败/未跑 | A/B 可接受/总数 | 判词一致/配对有效 | 关系充分 A/B | 过度强调 | 可见证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| lexical | 6 | 4/2/0/0 | 4/6；3/6 | 4/5 | 3/4；0/4 | 见逐句与视频；无过度强调 Gold 率 | 仅原 Proposed 有 f11 视频，其余未录制 |
| embedding | 6 | 0/0/0/6 | NOT_RUN | 不可计算 | 未核查 | 见逐句与视频；无过度强调 Gold 率 | 仅原 Proposed 有 f11 视频，其余未录制 |
| direct | 6 | 6/0/0/0 | 5/6；4/6 | 4/5 | 5/6；0/5 | 见逐句与视频；无过度强调 Gold 率 | 仅原 Proposed 有 f11 视频，其余未录制 |
| proposed | 6 | 4/1/1/0 | 3/6；3/6 | 4/4 | 3/4；2/4 | 见逐句与视频；无过度强调 Gold 率 | 仅原 Proposed 有 f11 视频，其余未录制 |


“可接受”仅计 BOUND_SUPPORTED 或 ABSTAIN_REASONABLE，分母固定 6；Judge 无效、方法失败与未跑单列，不能把它们算成已判断错误。关系充分的分母只含成功返回 SUFFICIENT/INSUFFICIENT/UNCERTAIN 的非空选择核查，**不是六句准确率**。Embedding 唯一请求返回 HTTP 400：`At most 32 items are allowed`，为本次批量请求超出接口限制，不是语义能力失败；遵守本轮不重试，6 条标 NOT_RUN，未用哈希回退冒充 Embedding。

| 页/命题 | Proposed 原始结果 | Direct / Lexical | 分歧与独立证据 |
| --- | --- | --- | --- |
| 3 像素依赖 | 选 11 个内部对象（6 节点+5 连线） | 均选整张图 | 两位对象 Judge 接受 Proposed；但完整图仍缺直接依赖关系。强调更多对象不能补回素材缺失关系 |
| 4 高斯条件分布 | 关系不足拒绑 | Direct 选高斯分布节点；Lexical 拒绑 | 两个对象 Judge 都判拒绑漏选；关系核查 A 充分/B 不充分。不能把漏绑直接写成方法错误定论 |
| 4 Conv-LSTM 预测 | Conv-LSTM+2 条 produces 边，未选 μ/σ 节点 | Direct 另含 μ/σ，共5对象；Lexical 拒绑 | A 首次判 Proposed WRONG、Direct PARTIAL，交换后 PARTIAL/支持；B 首次引文非法，不能以交换结果补齐。独立关系核查对 Proposed 又说充分，显示评价口径不一致 |
| 5 SQUEEZE | 语义检查失败，未输出有效焦点 | 两基线选 step-0 | 原文 raw-unit-0321–0323 明确 `[4C,N/2,N/2]`，而讲稿和画面写通道翻倍。基线被对象 Judge 接受不代表内容正确；原 Proposed 失败含引用越出0490–0492候选范围及关系不足，不能重写成“识别事实错误的正确拒绑” |
| 5 SPLIT | 选 e3--step-1 | 二者相同 | 对象 Judge 一致支持；关系核查 A 充分/B 不充分：卡片只是文字，未画出两支输出，属于对象选择与解释充分的区别 |
| 7 3.24 bits/dim | 选 e3--row-3 | 三者相同 | 对象 Judge 均支持，但两个关系 Judge 都说不足。原文 raw-unit-0836 为 Affine 3.31/41.0，0837 为 MixLogCDF 3.24/41.9；现表将3.24与Affine同列，存在事实混用 |

Conv-LSTM 的稳定目标全 ID、全部各方法选择及标签见 `rq2/cases.json`。原 Proposition 来源只取 raw-unit-0465–0467，谈长程依赖，未包括 0443–0464 的参数和条件分布上下文；“引用编号存在”不等于解释该预测关系。SQUEEZE 与实验数字同样有现成的更完整原文，但本轮不修改来源或重跑。

RQ2 共 1 次前向对象 Judge 引文失败，1 次关系 Judge 自相矛盾失败，均原样保留，不补调用。对 Conv-LSTM 交换顺序后，两套 Judge 的判词也发生变化。因此不能用当前接受比例给方法排名。过度强调仅记录候选集合范围及真实画面观察，没有可信参考标签，不制造过度强调率。

## 5. RQ3：MP4 的实际证据

复核原视频，未重新录制。Planned/Compiled 对应 13 个绑定组、50 条目标级 focus；Compiled 共 114 条事件，Runtime 115 条记录（含额外 legacy 记录），50 条 focus 均 executed。浏览器 actual_ms−planned_ms 为 1–6ms，均值3.26ms；这只是调度偏差，不是旁白词级误差。时间来自实测音频 cue，句内子句时序仍为近似。

从 f11 原 MP4 提取并实际查看 39 张前/中/后帧，覆盖全部 13 个绑定窗口；索引 `rq3/reviewed-windows.json`，原图 `rq3/frames-v2/`，联系表 `rq3/contact-*.jpg`。没有连续完整听看，也没有新增 Baseline 视频。

- 11 个窗口的中点可见至少一种强调，其中第1页第二阶段只见箭头发亮，不能确认该阶段全部5目标持续高亮。
- 第5页126.69–129.44秒，SPLIT 单步骤确实被突出；SQUEEZE失败，mAR/拼接没有对应接纳绑定，不是播放器丢掉这三步。
- 第4页109.80–113.36秒，Conv-LSTM和连线可见强调，但μ/σ输出节点不是焦点；图的其余关系保留为背景。
- 第7页216.411秒、第9页275.866秒及旧276.000秒帧，没有明显的预期焦点。它们对应事件仍是 executed，必须保留视觉缺失/持续不足记录。
- 只读代码发现播放器每次 focus 独立设置去除同一 class 的定时器，连续重用目标时旧定时器未被替换。其到期时间与上述缺失吻合；尚未做隔离复现，不把它写成全部场景的确定根因。本轮不修复。

这些是抽帧级 Coding Agent 观察，**不是 50/50 最终画面通过，也不是人工 Gold 或完整音画验收**。原 `Render Evidence` 的 not_reviewed 不被改写为已通过。首次抽帧脚本曾把全局时间再次叠加页面起点，失败的 `rq3/frames/` 保留且不用于结论；修正仅在本轮取证脚本，最终使用 `frames-v2`，没有更改媒体/生产时序。

## 6. 成本、未完成项与最小下一步

新增真实请求89次：20次RQ1方法、6次Direct绑定、1次Embedding（失败）、24次RQ1匿名Judge、14次RQ2对象Judge、16次关系Judge、8次素材Judge。输入242203、输出32303、总274506 tokens；费用接口未提供，不估算。响应成功88次不等于所有校验有效。没有模型重试，没有图片生成、TTS、produce、录制、代码/Prompt/阈值修改或 Git 提交推送；仅新增本地评价脚本、证据与本报告。未运行无关测试。

未完成：Embedding 对照；reuse/真实retrieve类别；各方法实际获取素材的公平对照；独立未暴露教材；Baseline视频对照；完整连续听看与逐对象可见窗口审核；等调用预算的Proposed/Direct比较。这些不以本轮报告冒充已完成。

下一步只建议三件事，未实施：

1. 先让来源窗口包含关系所需的完整证据，并隔离已确认的SQUEEZE/实验配置事实冲突。不是放宽引用真实性，而是用现成原文避免“有编号但不支持关系”。
2. 对连续同目标 focus 的解除竞争做最小隔离复现；检验视频可见持续时间，而不是新增高亮次数。修复后用已有计划验证，不重生整课。
3. 在来源和可见性条件可控后补齐Embedding批量接口限制，收紧Judge结果解释的一致口径，并以少量未暴露样本核验。本轮证据不足以支撑方法优势或学习效果主张。

详细账目、所有原始响应和失败见 `calls.json`、`calls/`、`costs.json`；两张评价表及逐项对照位于 `rq1/`、`rq2/`。完成本轮后停止，不自动改算法或追加实验。
