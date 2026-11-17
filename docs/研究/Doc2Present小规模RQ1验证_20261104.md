# Doc2Present 小规模 RQ1 任务合同（2026-11-04）

基线 f98b0b9；用户指定数据集并授权按规划继续。
目标：一次新文档、小预算的真实方法比较与双Judge正反序诊断；不为方法获胜调参。
输入：固定Doc2Present快照5656f79，DVC和Factorized两文档，摘要首两连续原句，每文档2条；配置rq1_doc2present_small_dev_v3.json；每文档Figure1完整图块。原文仅NFKC、断行连字与空白规范化，不改写指代。已核对当前工作树已存RQ1包，无这两文档命中；其他机器历史不可核验，故称新于本机已知RQ1，不称独立locked test。
允许修改：现有v2运行器的配置化入口/数据准备、对应测试、本配置及报告；不新增方法或平行协议。新目录.local/rq1/20261104-doc2present-small-v3/run01-package/，不得覆盖。
预算：上限40传输，6种模型条件×4=24，双Judge×双序×4=16；3个确定性baseline无需模型。material review、健康检查、图片生成、TTS、录制各0。无失败储备，不重发同任务；传输失败立即停止后续调用，保留未完成计划分母。
评价：预先定格式有效15/16及以上作为可继续扩样的开发性参考线，完整16位置均报告；判断稳定性报告同别名正反序的接受/首选集合差异，双别名不称独立模型家族。不强迫唯一第一，不要求Proposed胜出。不达参考线时保留结果，本轮不再调Prompt重跑。后续RQ2可固定同一视觉对象独立比较，不以RQ1获胜作前置条件。
门禁：来源与许可严格保持，数据集MIT不替代嵌入第三方图权利；参考MP4不进入生成。无新增gold或人工标注。冻结教材、旧run、baseline算法、G0不改。
验收：针对配置化数据集准备/校验的测试、既有runner/Judge测试、development预检、实际请求账本/tokens/耗时（费用未知记null）、离线重算调用0。代码独立只读复核后执行真实模型。
停止：hash冲突、来源不匹配、越预算、模型服务失败、需更改语义门槛则停止；无须人为制造配图成功。

## 实际结果（本轮结束，不追加调用）

代码基准：`13f5d2d5cf2b76a3d59f15caaaa84fe9d4b47419`，运行前已推送，快照dirty=false。协议SHA256：`3a60418e04c75a68470b048e4c70bb4672fc2080c90bf71d9c380c622b1b5874`。

实际40/40次：方法24、Judge16；传输40/40 OK，无重试。9种条件×4命题共36/36份方法输出有效，裁判16/16通过既有严格校验，另逐条对照保存请求的JSON Schema也16/16有效，达到事前15/16开发参考线。新样本与旧批次不同，不能将有效率变化因果归于Prompt修复。

正反序8对：首选提议集合变化4/8，可接受提议集合变化7/8；动作层首选变化4/8，可接受动作集合变化6/8。双别名同序8对：首选动作集合变化4/8，可接受动作集合变化8/8。不存在稳定裁判真值，不强行多数表决。

| 方法 | none/reuse/retrieve/generate | 可接受/16 | 并列首选/16 |
|---|---|---:|---:|
| never_retrieve | 0/4/0/0 | 12 | 10 |
| always_retrieve | 0/0/4/0 | 9 | 0 |
| keyword_heuristic | 0/4/0/0 | 12 | 10 |
| direct_llm | 2/2/0/0 | 15 | 14 |
| proposed | 3/1/0/0 | 14 | 10 |
| no_source | 3/0/1/0 | 11 | 5 |
| without_source_sufficiency | 3/1/0/0 | 14 | 10 |
| without_retrieval_suitability | 2/2/0/0 | 15 | 14 |
| without_uncertainty_handling | 2/2/0/0 | 15 | 14 |

上述16槽位是4条命题的重复模型代理判断，不是16个独立样本。Proposed没有显示胜过Direct；来源充分性消融与Proposed在这4条上动作相同，不能据此声称该机制有效。无source条件在2条上动作不同，另有1条拒判，但差异不等于质量改善。未做显著性检验或学习效果推断。

素材获取门禁仍阻止未独立核实权限的源图/候选正式落地，formal ACCEPT=0；本轮未做素材代理检查、图片生成、TTS、视频、健康检查或人工标注。这不被记为视觉必要性判断错误。参考MP4没有进入生成。

调用实测：prompt 99,578、completion 14,971、total 114,549 tokens。38/40调用返回缓存细节，已知cached tokens合计10,496；另2次未知，不能当完整缓存总数。请求耗时求和567.343秒，execute墙钟570.328秒；费用全部未知（null）。

定向37 passed、development预检33 passed，Ruff与diff检查通过，独立只读复核通过；未跑全量。无调用准备核对中发现/修正40预算报告、旧主题coverage及图注混正文；这些准备目录没有发送模型请求，均保留。

原包verify PASS：38输入、199输出文件hash，4条引文、2候选hash通过。迁移副本verify PASS；analyze-only调用40→40、新增0，重算report与原report完全相同。

证据原包：`.local/rq1/20261104-doc2present-small-v3/run01-package/`；迁移副本：同父目录`relocation-copy-01/`；迁移分析：`relocation-analysis.json`。原始回复、调用账本、Prompt及代码快照均在包内，未进Git。

复现（仓库.venv）：`python scripts/run_rq1_doc2present_v2.py verify --package-root <package>`；`python scripts/run_rq1_doc2present_v2.py analyze-only --package-root <package> --output <新文件>`。只重算，不重发。

下一步：本轮RQ1开发诊断收口，保留未解决的顺序/别名分歧和无方法增益结论，不继续调到胜出。转入RQ2小规模比较的输入/条件冻结：选择具备对象关系与动作过程的来源段落，共享同一对象、旁白和音轨，分别比较绑定与时序；当前摘要4句不能充当完整动态时序样本。保留来源和最终视频客观证据，裁判仅作补充代理。RQ2尚未运行，不把本次RQ1完成写成整项研究完成。
