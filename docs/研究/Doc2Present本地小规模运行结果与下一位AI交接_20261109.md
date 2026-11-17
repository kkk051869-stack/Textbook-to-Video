# Doc2Present 本地小规模运行结果与下一位 AI 交接（2026-11-09）

## 运行结论

本轮在 `codex/visual-acquisition-handoff-20261030` 上对三个已曝光开发论文输入（DVC、Factorized、Normalizing Flows）启动了本地 RQ1/RQ2 小规模比较，并生成绑定预测驱动的有声条件视频。它不是正式/locked 实验，不是整课视频，也没有人工 Gold 或学习效果结论。

完整运行包（准备、输入快照、调用账本、原始回复、失败现场、音频、HTML、截图、原始录制和 MP4）作为 GitHub Release 附件发布：

- Release：<https://github.com/kkk051869-stack/Textbook-to-Video/releases/tag/doc2present-local-dev-20261109>
- 附件：`doc2present-local-dev-20261109.tar.gz`，859,801,165 bytes（约 820 MiB）
- SHA256：`DF916C61DBC44F541B361602AB960A1B53AAAF88630925577BA0C440EFA2473C`
- 包内根目录：`.local/doc2present-local-dev-20261109/`

本地执行报告也在包内：`execution-result-20261109.md/json`。运行使用基线 `5cf0cf2b42ed6caa8f1e51cd4ac42dc15efa4511` 加上包内冻结的未提交差异快照；不要把后续本报告提交 SHA 当成模型运行代码基线。输入 PDF 的原始 rights 字段未修改，本轮只代表明确授权范围下的本地开发使用，不表示开放许可、素材 ACCEPT 或正式语义审核通过。

## RQ1：部分运行，未完成方法比较

- 六次模型请求中五次成功，一次 `BadGatewayError`：`without_uncertainty_handling / dvc-abstract-s1`。runner 在传输失败后按冻结门禁停止，未重试。
- 部分报告覆盖 23/54 个计划方法输出；确定性基线已产生结果，但模型条件只处理了第一个 RQ1 命题。Judge 有效结果 0/24。
- 成功请求共 11,120 tokens（prompt 9,203、completion 1,917）；失败请求没有 usage；费用未知。
- 证据：包内 `ready-v2/rq1/run-01/{calls.json,report.json}`。

## RQ2：六项绑定比较完成

| 方法 | 有效预测 | 绑定 | Judge 代理结果摘要 |
|---|---:|---:|---|
| lexical | 6/6 | 6 | 23 BOUND_SUPPORTED |
| embedding | 6/6 | 6 | 20 BOUND_SUPPORTED、3 WRONG |
| direct_llm_vlm | 6/6 | 6 | 23 BOUND_SUPPORTED |
| source_conditioned_legacy | 6/6 | 0 | 11 ABSTAIN_MISSED、12 ABSTAIN_REASONABLE |
| source_conditioned_context | 5/6 | 4 | 15 BOUND_SUPPORTED、2 ABSTAIN_MISSED、2 ABSTAIN_REASONABLE；另有 1 个 INVALID_RESPONSE |
| source_conditioned_context_no_source | 6/6 | 0 | 11 ABSTAIN_MISSED、12 ABSTAIN_REASONABLE |

37/43 次调用成功，使用 104,052 tokens（prompt 91,764、completion 12,288）；planned Judge 槽位 24，有效 23；有效正反序配对中未见判词变化。Judge 是模型代理，不是人工真值。完整统计在包内 `ready-v2/rq2/run-01/report.json`。

## 有声视频与页面证据

视频由保存的 `source_conditioned_context` 自动预测驱动，未手填绑定：

- DVC：`dvc-complex-s1 → dvc-motion-compensation`；`dvc-complex-s2 → dvc-residual-decoder`。
- Factorized：`factorized-complex-s1 → factorized-hdr-decoder`；`factorized-complex-s2 → factorized-shadow`。
- Flows：一项 `ABSTAINED_NO_SOURCE_SUPPORTED_CANDIDATE`，一项 `INVALID_RESPONSE`；相应视频没有候选图像，只呈现标题与旁白文字。

计划 15 个（3 文档×5 条件）视频，完成 14 个；DVC/simple_rule 在录制中断后留下 raw WebM，后续录制器因输出已存在而拒绝覆盖，没有合格 MP4。不要删除现场或重录来凑 15/15。

14 个成片均有 video/audio/subtitle 流，14/14 严格校准成功、14/14 解码通过；Runtime 共 50/50 个记录事件执行。内容时长误差最大 0.043 秒。六句实测 SAPI 音频在运行前生成，本轮复用，未新增 TTS 调用。

15 份 HTML 均运行双视口布局门禁；门禁通过但 Flows 有“可见元素过少/垂直偏移”警告。实际查看的代表帧：DVC 的 Residual Decoder 与 Factorized 的 Shadow MLP 在目标事件后可见，但裁剪图块丢失邻近图边；Flows 帧只有文字并有大留白。其余帧仍是 `NOT_REVIEWED`，没有连续完整听看。

开始录制的前两次 CLI 在生成视频后，因为命令环境漏设 `T2V_FFPROBE` 而在汇总阶段报错；设置正确工具路径后仅重新执行离线报告/探测，没有重录，最终两个视频也通过严格校准。

## 调用、验证和边界

- 本轮 RQ1+RQ2 共 43 次请求尝试；成功 token 合计 115,172，RQ1 失败请求用量未知。供应商费用均未提供，未估价。
- 无图片生成、无本轮新 TTS、无健康检查模型请求。没有全量测试；运行前定向测试 21 passed、development/rendering 预检 33 passed（均为准备阶段结果）。
- 不报告人工正确率、方法普遍优越性、正式实验结论或学习效果。

## 下一位 AI 的直接任务

1. 拉取本分支并下载上述 Release 包；校验 SHA256 后，从 `ready-v2` 两个有效包和 `media-v2/evidence-index.json` 开始，不使用已标为 superseded 的旧包。
2. 不重跑已完成的 37 个 RQ2 请求或 14 个 MP4。RQ1 `resume` 会被原有 `stop_on_transport_failure` 阻止；不得清空失败账本、覆盖运行包或重复已成功请求。先把 RQ1 标为部分失败。如果负责人另行决定补完，须先提出新冻结运行方案，写清已成功输出如何复用、失败项是否继续计失败、请求上限与新的 run_id。
3. 对 14 个 MP4 做工程证据核查：从 `frame-index.json` 把计划事件、Runtime 时间与实际帧对应起来，检查视觉目标窗口、字幕/音频轨与完整内容；区分实际查看与未审核帧。无需新增人工标注、Gold 或 Kappa 流程。
4. 仅离线检查 DVC/simple_rule 遗留 raw WebM 的时间戳、帧和 Runtime；能否恢复只按现存证据判断。不得覆盖原始文件，也不得为补齐数量重复录制。
5. 更新综合结果时保留预定分母 15（14 完成、1 未完成）、RQ1 Judge 0/24 和 Flows 的拒绑/无效输出；Judge 结果继续标模型代理。先完成运行证据复核，再判断是否需要新研究运行。

腾讯文档交接卡将追加同一结论及该 Release 链接；历史内容保留。
