# lesson_002 Integrated AB r7 失败与 r8 交接

## 结论

r7 不是成功的 paired run。baseline 完整成功，P0 在录制前被时长一致性门禁拒绝。失败证据已保留，代码修复已通过定向测试，但必须创建 r8 从头复验。

## r7 已完成的证据

- 分支：`codex/ab-research-handoff-20261017`
- r7 冻结提交：`9ea16f73ae1cfbf1e339cb47b997bf42c0661439`
- preflight：development + rendering PASS
- 配置：43 个传递文件校验 PASS
- baseline：10 WAV、35 cues、约 229.685 秒、两视口各 10/10 页布局 PASS、最终有声 MP4/SRT/quality report 成功
- P0：冻结音频复制成功，phase-two plan 成功，两视口各 10/10 页布局 PASS
- 失败：artifact integrity 检测到音频 `229.685s` 与 P0 timed storyboard `179.120s` 不一致，拒绝录制

## 根因与修复

P0 在测得冻结音频时长后生成 phase-two plan，并第二次物化 candidate。旧实现从原始 baseline storyboard 重新复制，覆盖了已经测得的 `audio_duration_sec` 和语义 timing。

修复在 `src/textbook2video/pipeline/orchestrator.py`：第二次物化后只携带已测量的 duration、timeline 和 animations；计划阶段新增的元素绑定与研究元数据保持不变。携带前严格检查段落 ID、旁白和正时长，任何漂移均失败。

测试新增于 `tests/test_orchestrator.py`，覆盖：

- 实测 timing 被保留；
- 计划元素与 `research_p0` 元数据不被覆盖；
- 旁白漂移时拒绝继续。

已完成定向回归：`37 passed`。全量回归被人工中断，没有结果，接手者必须先补跑。

## 证据边界

- r7 P0 没有最终 MP4，因此不是 paired success。
- r7 的 candidate-subset 只是声明、校验和访问审计，尚未被 acquisition/retrieval 实际消费。
- 冻结决策中的 generate/retrieve 项在无 LLM、无 catalog 情况下没有变成已审核资产。
- 教材图 `fig7-6` 没有本次 run 的 visual-semantic ACCEPT，仍被 fail closed。
- Gate 1B、服务器实验、批量实验和论文效果 claim 均未解锁。

## r8 接手清单

1. 补跑全量测试。
2. 新建 r8 config/audio manifest 并更新当前实现 hash。
3. 提交、推送、重新 preflight。
4. 新建 r8 manifest/output，完整跑 baseline。
5. P0 复用 r8 baseline 冻结音频，完整跑到 MP4。
6. 自动比较 10 WAV、35 cues、逐段时长、总时长及关键输入 hash。
7. 查看 runtime/render evidence，人工完整观看两条视频。
8. 在 Git 和腾讯共享文档同时写明成功、失败、警告与证据边界。
