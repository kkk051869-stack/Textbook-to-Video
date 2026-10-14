# A 线合并状态与下一步

> 更新日期：2026-10-13
> 范围：只记录成员 A / Visual Decision Track；不代表执行 B 线任务。

## 合并原则

研究范围以《教学原则驱动的教材教学视频生成_研究计划.md》和《教学原则驱动的教材教学视频生成_研究思路报告.md》为准。Mayer 的完整原则体系是理论背景；当前实现只推进与 A 线视觉决策相关的原则链：Coherence / Multimedia → visual support need → source-first reuse / retrieval decision。语义—时间动态对齐与事件级成片评价不在本次 A 线执行范围内。

目标分支已有 `research_generation_v2` 契约、命题与来源结构、视觉决策/采集、P0 规划、动态呈现和成片证据模块。本地 G0 工作区提供了更细化的 A 侧标注协议、基线诊断、候选池实验和用户审阅记录。两边 `visual_decision.py` 的 API 与数据模型不同；因此保留目标分支实现，不做覆盖式复制，也不把旧版脚本直接接到新契约上。

## 已并入的内容

- 两份研究主文档；
- A 侧最终标注协议 v4.2、基线记录、人审指南；
- 本地 A 线 `annotation/`（225 个文件，约 1.69 MB）和 `dry_run/`（419 个文件，约 9.88 MB）的完整副本，位置为被 `.gitignore` 忽略的 `.local/a_research_import/`。原始本地 G0 仓库保持不变；A→B handoff 未复制，也不作为本次 A 工作输入。

30 条 human-reviewed gold 的冻结记录：

- 状态：`FROZEN` / `HUMAN_REVIEWED_GOLD`，30/30 接受、0 修改；
- 标签分布：`none=28`、`source-sufficient=1`、`extra-support-needed=1`；
- `human_reviewed_gold.json` SHA-256：`5e5b1dbd953eef0e5cf8a12ec7ec36a128c195b9b252f31c8af231ec29cb14de`；
- 可复现的最小只读副本已提交到 `datasets/research_generation_v2/reference/a_visual_support_gold_v0.1/`；规范化 JSON SHA-256 为 `d5ec065f116f5ab9fb668b81becfa0185a788e2cfeb989c8f15325d483342139`；
- 原记录的 `formal_accuracy` 和 `inter_annotator_agreement` 为空。因此它是用户审阅过的 A 工作 gold，不是双人一致性、外部准确率或多样本方法有效性的证据。

本地既有的描述性基线（这 30 条上）：`never_retrieve` accuracy 0.80 / macro-F1 0.390；`always_retrieve` accuracy 0.033 / macro-F1 0.022；`keyword_heuristic` accuracy 0.533 / macro-F1 0.323。由于正类各只有 1 条，这些数字只作运行与基线复现记录，不能据此选择或宣称某个策略有效。

## 当前 A 线位置

G0 契约与目标分支 v2 生成链已经存在；本地完成过 A 视觉支持标签定义、30 条审阅 gold、若干确定性基线、检索触发和候选池探索。分支内已有的动态规划/事件证据代码不意味着本轮开始执行 B 的标注、PresentAgent 或评价工作。

下一道 A gate 是把“当前分支的预测”与这份 gold 做**安全、可复现的对照**，而不是再跑一遍旧版预测脚本。接入前必须：

1. 按课节与命题文本建立旧、新 ID 的一对一映射；重复、缺失或不唯一都显式失败，禁止按顺序猜 ID；
2. 将标签数据作为独立评测参考，只在生成结束后用于评分，禁止进入 lesson plan、prompt 或生成候选；
3. 输出可审计的逐项匹配/未匹配清单、映射覆盖率、类别分布和分类型指标；
4. 对当前 30 条仅报告探索性结果。若要比较策略或做主张，先扩展正类覆盖并冻结独立样本；该扩展包不得冒充两名真实标注者的一致性结果。

本地旧版 `scripts/run_visual_support_need_*` 依赖另一版 `visual_decision.py` 的私有 API/目录布局，不能直接复制到当前分支运行。后续应实现一个只读的 gold 对齐与评分适配层，复用当前分支的预测产物，不改写冻结 gold，不改变 `research_generation_v2-v0.1` 契约。

当前分支已加入 `src/textbook2video/research/gold_alignment.py` 和 `scripts/evaluate_visual_support_gold.py`。每次按单课节调用，输出也放在 `.local/`，例如：

```powershell
python scripts/evaluate_visual_support_gold.py `
  --gold datasets/research_generation_v2/reference/a_visual_support_gold_v0.1/human_reviewed_gold.json `
  --proposition-graph <该课节的 proposition_graph.json> `
  --visual-decisions <该课节的 visual_decisions.json> `
  --output .local/a_research_import/evaluations/<case-id>.json
```

适配层只接受唯一的课节 + 命题文本匹配，再沿 proposition graph 的 knowledge→narration 关系聚合预测；无匹配、歧义、缺少关联决策或关联决策冲突都会报告出来，不会猜 ID。当前工作树没有已冻结课节的 graph/decision 运行产物，因此本次只完成接口，未生成虚构评测结果。

适配结果同时记录三个输入文件的 SHA-256，并将 Visual Support Need 与探索性的 retrieval/generation 指标分开报告。当前 AB 契约上的确定性 baseline 位于 `src/textbook2video/research/visual_decision_baselines.py`；它复用当前 P0 decision schema，不覆盖 AB 的 `visual_decision.py`。

## 后续顺序（A 线）

1. **Gold–prediction adapter**：实现严格 ID/text 对齐和只读评分；先用当前分支已保存的真实预测产物验证接口，缺输入时报告缺口，不调用在线模型伪造结果。
2. **扩展评测集**：从已冻结 source 中选取具有充分类别覆盖的命题，生成代理独立标注和审阅包；所有模型/代理标注明确标成非 gold，用户确认前不升级状态。
3. **A 线视觉决策/候选实验**：在冻结候选池上分别评估 need 与 acquisition，不把候选可用性误写成 retrieval 质量；保留 `NO_MATCH` 和 source-first 控制。
4. **生成链落地**：仅在指标与契约稳定后，将 A 决策写入 v2 生成 sidecar，并通过显式 feature flag 保持旧输出兼容。

本次没有执行或修改 B 专属的 PresentAgent、语义—时间标注、事件评价或 A→B 交接任务。
