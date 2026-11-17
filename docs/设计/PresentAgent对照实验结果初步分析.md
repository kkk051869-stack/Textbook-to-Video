# PresentAgent 对照实验结果初步分析

更新时间：2026-08-10

## 1. 当前实验状态

本轮对照实验已经完成两类自动/半自动检查：

1. 内容覆盖自动评分：用云端本地 `qwen3-32b-awq` 对 24 个正式视频做文本证据评分。
2. 视觉产物质量初筛：用 `ffprobe`、`ffmpeg` 和关键帧图像统计检查视频完整性、空白帧、低细节帧、过暗/过亮等基础问题。

当前已经确认：

- 24 个正式视频全部存在并可读取。
- 24 个视频的内容评分全部解析成功。
- 每个视频均成功抽取 8 张关键帧，共 192 张。
- 自动标出的 4 张“空白/低细节疑似帧”已经人工复核，均属于淡入/淡出或切页转场抽样误报。
- 目前没有发现视频文件损坏、黑屏、白屏、持续空白或明显时长异常。

当前尚未完成：

- OCR/VLM 级别的文字可读性检查。
- PresentAgent 视频中文字是否乱码的最终确认。
- 教材图片是否真实出现在视频画面中的视觉确认。

## 2. 数据与结果路径

内容自动评分结果：

- 云端：`/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/metrics/vlm/judge_outputs/formal_text_qwen32b_v1`
- 本地：`D:/Code/vibe coding/Textbook-to-Video/outputs/presentagent-evaluation-results/formal_text_qwen32b_v1`

视觉产物检查结果：

- 云端：`/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/metrics/visual_artifact_checks/formal_heuristic_v1`
- 本地：`D:/Code/vibe coding/Textbook-to-Video/outputs/presentagent-visual-artifact-checks/formal_heuristic_v1`

整合后的评价表：

- 本地：`D:/Code/vibe coding/Textbook-to-Video/outputs/presentagent-evaluation-templates/PresentAgent对照实验评价表.xlsx`
- 云端：`/ai/data/textbook-to-video/evaluation/presentagent-evaluation-templates/PresentAgent对照实验评价表.xlsx`

相关报告：

- `docs/设计/PresentAgent对照实验结果初步分析.md`
- `docs/设计/PresentAgent视觉产物质量检查初步报告.md`

## 3. 内容覆盖自动评分结果

评分范围：

- 8 个正式课节
- 每课节 3 个系统版本：`internal_C01`、`internal_C11`、`presentagent`
- 共 24 个视频
- 评分模型：`qwen3-32b-awq`
- 评分方式：基于生成视频文本、结构化输出、annotation 和元数据的文本证据评分

全部 24 个视频均解析成功。

| 系统 | 视频数 | 核心知识点均分 | 保留题均分 | 图片文本证据均分 | 文本证据视频质量均分 | 错误记录数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| internal_C01 | 8 | 2.0000 | 1.9583 | 0.0000 | 2.0000 | 8 |
| internal_C11 | 8 | 1.9444 | 2.0000 | 0.3636 | 2.0000 | 7 |
| presentagent | 8 | 1.9444 | 1.9375 | 0.8182 | 2.0000 | 6 |

核心观察：

- 三个系统在文本内容覆盖上整体都接近满分。
- `internal_C01` 的核心知识点覆盖最好，54 个核心知识点评分均为满分。
- `internal_C11` 的保留题表现最好，48 个保留题均为满分。
- `presentagent` 在图片文本证据上更高，但这只说明文本/结构化输出中更容易出现图片线索，不等于真实画面中的图片使用更好。
- 所有错误记录均为 `missing_key_content`，没有发现自动评分层面的事实错误或幻觉类错误。

## 4. 内容覆盖中的具体差异

### 4.1 核心知识点

`internal_C01` 在 8 个课节中核心知识点均为 2 分。

`internal_C11` 和 `presentagent` 各有 3 个核心概念被评为 1 分，均属于部分覆盖：

| 课节 | 系统 | 概念 | 问题摘要 |
| --- | --- | --- | --- |
| lesson_001 | internal_C11 | c006 | 提到 6G 和数据中心，但没有明确提到西部数据中心和边缘数据中心 |
| lesson_001 | presentagent | c006 | 提到数字鸿沟和 6G，但没有明确提到西部数据中心等具体措施 |
| lesson_004 | internal_C11 | c003 | 提及参与者和推动者，但没有明确受益者和见证者 |
| lesson_004 | presentagent | c003 | 提及受益者，但没有明确参与者和推动者 |
| lesson_005 | internal_C11 | c006 | 提及数据特性，但没有明确类比资本 |
| lesson_005 | presentagent | c006 | 没有明确提及与资本的类比及探索特性 |

这些问题不是明显讲错，而是关键细节没有讲完整。

### 4.2 保留题

保留题用于检查视频内容是否足以推出教材中的关键问答。

低于满分的条目包括：

| 课节 | 系统 | 问题 | 问题摘要 |
| --- | --- | --- | --- |
| lesson_005 | presentagent | q005 | 没有直接讲出资本正反两面，只部分覆盖 |
| lesson_007 | presentagent | q005 | 提到社会运作成本，但没有明确风险变化 |
| lesson_011 | presentagent | q003 | 提到传统管理方式难以应对，但没有明确租赁关系和责任主体问题 |
| lesson_012 | internal_C01 | q001 | 缺少计数或统计分组 |
| lesson_012 | internal_C01 | q004 | 缺少资源受限和西部算力支持 |

其中 `lesson_012__internal_C01` 是内部版本中保留题表现最低的组合，需要在后续结果分析中单独说明。

### 4.3 图片文本证据

图片文本证据评分整体偏低，尤其是两个内部版本。

这不能直接解释为“视频中没有图”。原因是当前评分只看文本/结构化输出。如果画面里出现了图片，但讲稿或结构化文件没有显式记录图片编号、图片名称或图片承载内容，文本证据评分仍可能给低分。

当前只能得出：

- `presentagent` 更容易在文本计划或结构化输出中保留图片相关线索。
- `internal_C01` 的生成文本里几乎没有体现教材图片使用情况。
- `internal_C11` 只在少数课节中体现了图片相关线索。
- 真正的图片出现情况仍需要后续做关键帧图像匹配、VLM 或人工视觉确认。

## 5. 错误类型

错误记录共 21 条，全部是 `missing_key_content`。

| 系统 | minor | major | 总数 |
| --- | ---: | ---: | ---: |
| internal_C01 | 3 | 5 | 8 |
| internal_C11 | 2 | 5 | 7 |
| presentagent | 4 | 2 | 6 |

解释：

- 自动评分没有发现明显事实错误。
- 问题主要是关键内容遗漏。
- `presentagent` 的错误总数较少，但保留题均分也略低，说明它可能在某些问题上表达较泛，未能支撑精确答案。

## 6. 视觉产物质量检查结果

本轮视觉产物检查使用确定性脚本完成：

- 用 `ffprobe` 检查视频是否可读取。
- 读取视频时长、分辨率、帧率、编码格式。
- 比对视频清单中的时长与实际探测时长。
- 用 `ffmpeg` 从每个视频抽取 8 张关键帧。
- 用图像统计指标检查疑似黑屏、白屏、空白页、低细节帧、过暗、过亮、过密画面。
- 生成 contact sheet，便于后续复核。

总体结果：

- 24 个视频文件均存在。
- 24 个视频均可被 `ffprobe` 正常读取。
- 所有视频均为 1920x1080。
- 所有视频均为 25fps。
- 所有视频编码均为 h264。
- 实际时长与视频清单一致。
- 每个视频均成功抽取 8 张关键帧，共 192 张。

按系统聚合结果：

| 系统 | 视频数 | ffprobe 正常 | 空白帧疑似 | 低细节帧疑似 | 过暗帧 | 过亮帧 | 高优先级复核视频 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| internal_C01 | 8 | 8 | 3 | 4 | 0 | 0 | 2 |
| internal_C11 | 8 | 8 | 1 | 4 | 0 | 0 | 1 |
| presentagent | 8 | 8 | 0 | 0 | 0 | 0 | 0 |

## 7. 问题帧人工复核结论

自动脚本标出 3 个高优先级复核视频，涉及 4 张关键帧：

| 视频 | 时间点 | 自动标记 | 人工复核结论 |
| --- | ---: | --- | --- |
| lesson_001__internal_C11 | 15.3s | 空白/低细节疑似 | 开场标题页切到内容页的淡入/淡出空档，前后帧正常 |
| lesson_002__internal_C01 | 164.8s | 空白/低细节疑似 | 视频末尾附近切页转场，前后帧有正常内容 |
| lesson_004__internal_C01 | 107.7s | 空白/低细节疑似 | 表格页切到条形图页的淡出/淡入空档，前后帧正常 |
| lesson_004__internal_C01 | 126.7s | 空白/低细节疑似 | 条形图页切到流程/要点页的淡出/淡入空档，前后帧正常 |

复核方式：

- 对每个疑似问题时间点额外抽取前后窗口帧。
- 查看 `problem_windows/*.jpg` 中的前后连续画面。
- 判断空白帧是否持续存在，还是只出现在切页瞬间。

复核结论：

- 4 张问题帧均属于抽样刚好落在动画转场空档。
- 前后帧都有正常内容。
- 不属于视频损坏、黑屏、白屏或持续空白。
- 因此，内部系统的高优先级自动告警应降级为“转场抽样误报”。

补充结果文件：

- 本地：`D:/Code/vibe coding/Textbook-to-Video/outputs/presentagent-visual-artifact-checks/formal_heuristic_v1/manual_frame_review_notes.csv`
- 本地窗口帧：`D:/Code/vibe coding/Textbook-to-Video/outputs/presentagent-visual-artifact-checks/formal_heuristic_v1/problem_windows/`
- 云端：`/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/metrics/visual_artifact_checks/formal_heuristic_v1/manual_frame_review_notes.csv`
- 云端窗口帧：`/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/metrics/visual_artifact_checks/formal_heuristic_v1/problem_windows/`

## 8. PresentAgent 视觉产物观察

PresentAgent 的 8 个视频在本轮确定性检查中没有出现：

- 黑屏
- 白屏
- 空白帧
- 过暗帧
- 过亮帧
- ffprobe 失败
- 视频损坏

从 contact sheet 观察，PresentAgent 视频有明显统一模板特征：

- 统一绿色/深色模板。
- 页面样式高度相似。
- 多数页文字密度偏高。
- 画面内容接近铺满整页。

脚本记录了 `crop_proxy_frame_count=8`，但查看 contact sheet 后判断这主要是模板全屏背景导致的启发式弱提示，不应作为异常结论。

## 9. 当前仍不能确认的问题

当前仍不能最终确认“视频中文字是否乱码”。

原因：

- 云端没有 OCR 引擎。
- 当前使用的 Qwen32B 是文本模型，不是视觉模型。
- 图像统计指标只能发现黑屏、空白、过暗、过亮、低细节等问题。
- 乱码、错字、字体渲染异常需要 OCR/VLM 或人工视觉确认。

因此，此前观察到的 PresentAgent“PPT 正常但视频中文字乱码”问题，仍需要专门检查。

## 10. 当前可靠结论

当前可以下的结论：

- 24 个正式视频都是完整、可读取的视频文件。
- 三个系统的视频都没有基础产物损坏问题。
- 内容覆盖自动评分全部成功，三套系统在文本内容覆盖上整体接近满分。
- `internal_C01` 核心知识点覆盖最好。
- `internal_C11` 保留题表现最好。
- `presentagent` 图片文本证据更高，但不能等同于真实图片展示更好。
- 自动视觉检查中内部系统少量空白/低细节告警已经人工复核，均为转场抽样误报。
- PresentAgent 没有被自动指标标出黑屏、空白、过暗或过亮问题。
- PresentAgent 模板高度一致，文字密度偏高，需要继续检查可读性。

当前不能下的结论：

- 不能说 PresentAgent 没有乱码。
- 不能说任一系统真实视觉质量已经通过最终检查。
- 不能用文本证据评分代替视觉质量评分。
- 不能用图片文本证据分直接代表图片真实展示效果。
- 不能用本轮图像统计指标替代 OCR/VLM 或人工视觉判断。

## 11. 下一步建议

下一步不建议马上优化系统，建议先完成“文字可读性专项检查”。

优先级：

1. 人工快速查看 8 张 `contact_sheets/by_lesson/*.jpg`，重点看 PresentAgent 行的文字是否乱码或不可读。
2. 如需自动化，安装或接入 OCR/VLM：
   - OCR：PaddleOCR、EasyOCR、Tesseract 中文模型
   - VLM：Qwen-VL、InternVL、GPT-4o 或同类视觉模型
3. 对有 required_images 的课节做图片出现情况检查：
   - 是否出现教材原图或等价视觉内容
   - 是否出现在相关讲解附近
   - 多图课节是否至少覆盖关键代表图
4. 完成文字可读性和图片出现检查后，把结果并入评价表。
5. 再决定是否需要优化内部系统。

当前更稳妥的实验叙述是：

> 本实验目前已完成文本内容覆盖评分和基础视觉产物完整性检查。结果显示三套系统在内容覆盖上整体接近满分，24 个视频均为完整可读取产物，未发现黑屏、白屏、持续空白或视频损坏。当前尚需进一步通过 OCR/VLM 或人工复核确认文字可读性与图片实际使用情况，尤其是 PresentAgent 视频中文字是否乱码的问题。
