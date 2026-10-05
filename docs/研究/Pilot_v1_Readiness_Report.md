# Pilot v1 Readiness Report

## 1. 总结论

**READY**：数据包已满足“双人独立人工标注”的最低条件。该结论只表示 evidence package、空白模板与执行协议可用，不表示原则 taxonomy 已被验证，也不表示任何研究假设成立。

## 2. 已选择案例

`lesson_002`、`lesson_004`、`lesson_007`、`lesson_011`、`lesson_012`。选择依据是 source/visual 类型、signaling action、renderer 声明、正常执行与 target missing 的覆盖，而非已知教学错误。

## 3. 每案证据完整性

| case | source | KP | narration | elements/events | planned evidence | runtime trace | final MP4 |
|---|---|---|---|---|---|---|---|
| lesson_002 | AVAILABLE | PARTIAL：candidate/reference | AVAILABLE | AVAILABLE | AVAILABLE；无独立 before-timing 版本 | AVAILABLE | AVAILABLE |
| lesson_004 | AVAILABLE | PARTIAL：candidate/reference | AVAILABLE | AVAILABLE | AVAILABLE；无独立 before-timing 版本 | AVAILABLE | AVAILABLE |
| lesson_007 | AVAILABLE | PARTIAL：candidate/reference | AVAILABLE | AVAILABLE | AVAILABLE；无独立 before-timing 版本 | AVAILABLE | AVAILABLE |
| lesson_011 | AVAILABLE | PARTIAL：candidate/reference | AVAILABLE | AVAILABLE | AVAILABLE；无独立 before-timing 版本 | AVAILABLE | AVAILABLE |
| lesson_012 | AVAILABLE | PARTIAL：candidate/reference | AVAILABLE | AVAILABLE | AVAILABLE；无独立 before-timing 版本 | AVAILABLE | AVAILABLE |

五案 MP4、HTML、trace、source 与 annotation templates 均已导出；每案抽样 5 个 event 生成三层证据索引和邻域帧。

## 4. 已知缺失证据

- 五案均缺独立 `storyboard_before_timing`；归档的两个 storyboard 文件内容相同；
- 五案均缺 `sentence_cues.json`，没有 forced-alignment sentence timestamp；
- 缺生成时 prompt 精确 hash 与可信原始生成 timestamp；
- `lesson_012` 缺 render images；
- KP/source 只到 candidate/reference 层，尚无人工 proposition-level provenance gold；
- runtime trace 不包含最终对象的可靠 rendered visibility interval；
- 样本没有确认的 focus/dim，也没有确认发生的 LLM renderer fallback。

这些缺失限制后续结论强度，但不阻止本轮人工 operationalization/observability pilot：最终 MP4、旁白、source、planned/runtime evidence 仍可供人工分层判断。

## 5. 当前必须人工判断的字段

- 最终 proposition 边界、ID、文本和 narration time；
- proposition ↔ KP ↔ source evidence 绑定；
- Visual Necessity / applicability；
- Visual Correctness / relation 与支持它的 element/source；
- acceptable temporal window；
- MP4 中 observed visible start/end 与可观察状态；
- Temporal Contiguity label；
- Signaling applicability、label、expected/observed target；
- confidence、reason、notes 与 uncertainty reason。

## 6. 已自动预填的字段

- lesson、case、segment、element、animation、event ID；
- narration 和 deterministic subtitle chunk 候选边界/时间；
- candidate KP/source lexical links 与 score；
- storyboard elements、animations、timeline；
- compiled/planned time、runtime trace、target lookup 结果；
- audio duration、source paragraphs 与 source image 引用；
- HTML/MP4 路径、抽样 event 邻域帧；
- snapshot 来源、hash、Git/model/TTS/renderer 元数据及缺失项。

上述均为客观事实或机器候选，不是 pedagogical gold。

## 7. 明确未自动生成的判断

系统没有自动生成 proposition gold、source/KP gold、visual necessity、visual correctness、temporal violation、rendered visibility、signaling correctness、confidence 或 adjudication。所有 annotation templates 的这些字段保持空值，agreement 工具对未完成输入返回 NOT_READY。

## 8. 主要风险

1. 272 个 subtitle-derived proposition candidates 可能需要大量 SPLIT/MERGED，实际人工命题数尚未知；
2. 标注者可能把主题相关误当解释正确，或把 technical target missing 误当教学违规；
3. Source ablation 容易受完整标注和 case memory 污染，必须最先执行；
4. 邻域帧是离散采样，无法代替 MP4 判断精确可见区间；
5. 当前 action 与 renderer 多样性有限，pilot 可检验定义可用性，但不能代表所有动态教学视频；
6. 中文文本/字幕若在标注环境出现编码或播放器显示问题，应先停下修复数据读取，不得带病标注。

## 9. 预计人工工作量

| case | segments | proposition candidates | elements/events |
|---|---:|---:|---:|
| lesson_002 | 10 | 64 | 65 |
| lesson_004 | 9 | 50 | 57 |
| lesson_007 | 8 | 38 | 50 |
| lesson_011 | 9 | 70 | 52 |
| lesson_012 | 9 | 50 | 60 |
| **合计** | **45** | **272** | **284** |

每名标注者另有 30 个 source-ablation 项和 25×3 个三层证据判断。按首轮熟悉 taxonomy、逐项查看 source/MP4 与记录理由估计，每名标注者约需 10–14 小时；不含培训、休息、规则修订和最终 adjudication。应先用两案校准时间，再更新估算，不能把候选条目数等同于最终 proposition 数。

## 10. 下一步

开始双人独立标注。
