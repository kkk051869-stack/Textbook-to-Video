# lesson_002 Integrated AB 字幕修复与复跑交接

> 状态日期：2026-10-19
> 工作分支：`codex/ab-research-handoff-20261017`
> 已推送代码基准：`744dc37982ce5baaaa8a8cbcf7f7e883dadcc79f`
> 证据等级：development，本地单课；不是 pilot、validation、locked-test 或服务器结果。

## 1. 本轮接手时的事实

- 先读取腾讯共享文档，再将本地分支快进到云端指定提交 `17584a6ce19c02bc62e2a874a83f634d7efb9798`。
- 云端记录称另一台机器完成了 Integrated AB r2：Track A r10 为 49 条 knowledge propositions、35 条 narration propositions、35 条 visual decisions；Track B 为 10 个 WAV、35 条 sentence cues、约 229.685 秒；P0 runtime 为 66/66 browser events、0 error。
- 云端同时明确：Gate 1A 仅为 `TESTED_MOCK`；Gate 1B 未通过；r2 的唯一质量阻塞是 9 条字幕 cue 超过 8 秒，最大约 17.2 秒；30 条 gold 仍为 `28/1/1` 工作参考，不是正式双盲证据。
- 云端所指 r2 `.local` run bundle 不在当前工作树或已检查的本地 worktree 中，因此本轮不能复核其视频、质量报告或哈希。云端摘要保留为历史说明，不能替代本机可审计证据。
- Git 的旧《当前研究交接卡》仍停留在“Track A only”，与云端更新状态不一致；本轮已更新。

## 2. 已完成的代码与冻结输入修复

### 2.1 字幕显示层拆分

- 提交 `ecad2a9`：只在 SRT 显示层按实测句子区间确定性拆分过长 cue。
- 单条显示 cue 上限为 8.0 秒；文本不重复；拆分后完整覆盖原句时间区间。
- P0 的语义 timing 仍使用未拆分的 35 条原始 sentence cues，避免把显示层修复混入研究变量。

### 2.2 冻结 hash 与跨平台换行

- 发现旧 `candidate_subset_track_b.json` 中 `proposition_graph.json` 与 `visual_decisions.json` 的 hash 不是当前文件的真实内容 hash；同时 Windows CRLF/LF 会造成同一文本在不同机器上误报漂移。
- 提交 `338a6ef`：冻结 corrected `candidate_subset_track_b_v2.json`，并让文本输入校验只接受 raw/LF/CRLF 三种等价字节形态；二进制仍严格按原始 SHA-256。
- gold 隔离也使用规范化内容比较，避免仅通过换行差异绕过同内容检测。

### 2.3 无 LLM 的冻结 development 运行

- 提交 `54164cf`：run manifest 按 preflight 的 `llm_required` 判定，而不是一律要求 LLM 凭据。
- 明确冻结输入、无需模型调用的 development 单课可以离线准备；pilot/validation/locked-test 仍 fail closed。
- 当前机器没有完整 LLM 凭据，所以不能执行任何真正需要模型的生成或复核。

### 2.4 同案例教材原图解析

- r3 在 TTS 前失败：旧 storyboard 只写 `fig7-6_区块链数据结构.png`，代码只在 `baseline/images` 查找，而冻结图像实际位于同案例 `source/images`。
- 提交 `5f29791`：只允许按顺序检查 storyboard 同级 `images` 与同案例 `source/images`；若两处同名文件 hash 不同则拒绝；没有更宽泛 fallback。

### 2.5 旧 storyboard 与 research-v2 标志

- r4 完整生成了 35 个 SAPI 句子文件、10 个合并 WAV 和 35 条 sentence cues，随后失败。
- 原因：`T2V_RESEARCH_GENERATION_V2=1` 要求每个 element 有 v2 `element_id`，但冻结 storyboard 是 legacy 格式，只有旧 ID。
- r4 已标记 `FAILED_PRESERVED`；没有原地重试。诊断证明在不设置该环境变量时，同一音频可生成 10 段定时 storyboard，总时长约 229.690 秒，并能解析冻结教材原图。
- r5 audio spec 固定：legacy storyboard 运行时该变量必须未设置或为 false。

### 2.6 录屏依赖与 Windows 长路径

- r5 成功完成 SAPI 音频、semantic timing、教材图复制和 10 页确定性 HTML；实测为 10 WAV、35 原始 sentence cues、229.686 秒。
- r5 在录屏开始时失败：Playwright 缺少其管理的 `ffmpeg-1013/ffmpeg-win64.exe`。系统 ffmpeg 存在不能替代该依赖。
- 已用项目环境执行 `python -m playwright install ffmpeg`，本机 Playwright ffmpeg-1013 已安装。
- 同时发现第二视口报告全路径为 266 字符，超过传统 Windows MAX_PATH。提交 `744dc37` 增加确定性短文件名回退；独立诊断确认 1920×1080 与 1366×768 两份报告均成功落盘，且 browser layout check 的 blocking result 为 PASS。
- r5 仍标记 `FAILED_PRESERVED`；安装环境依赖和修复代码后没有覆盖或续跑 r5。

## 3. 当前可接手入口

- 分支：`codex/ab-research-handoff-20261017`
- r6 代码基准：`744dc37982ce5baaaa8a8cbcf7f7e883dadcc79f`
- 待运行配置：`configs/experiments/ab_lesson002_integrated_development_sapi_r6_20261019.json`
- r6 audio spec：`datasets/research_generation_v2/frozen/ab-real-lessons-dev-v1/inputs/lesson_002_audio_spec_sapi_v6.json`
- r6 audio manifest：`datasets/research_generation_v2/frozen/ab-real-lessons-dev-v1/manifests/audio_track_b_sapi_v6.json`
- 配置静态校验：PASS，43 个传递文件通过 schema/hash/gold 隔离校验。
- 全量测试：`463 passed, 2 skipped`；触及文件的 Ruff `I/F821/F841` 通过；`git diff --check` 通过。

## 4. 明确没有完成的工作

- **r6 尚未运行。** 没有 r6 preflight snapshot、run manifest、access log、baseline/P0 输出或 final MP4。
- **没有完成 baseline/P0 成对实验。** 不能声称相同音频哈希、相同 sentence-cue hash、相同时长预算已在 r6 实证成立。
- **没有生成修复后的最终 SRT/quality report。** 字幕拆分逻辑有测试，但 r5 在字幕/最终质量阶段之前失败；Gate 1B 仍未通过。
- **没有人工观看最终视频。** HTML layout check 不能替代 final-video visibility review。
- **Track B candidate subset 尚未接入 `produce` CLI。** 当前配置会冻结并审计该文件，但 `--p0-retrieval-catalog` 需要顶层 `assets`，现有 subset 是 `candidates` 结构；不得宣称完整 RQ2 candidate-subset wiring 已验证。
- **没有服务器实验、没有批量运行、没有 pilot/validation/locked-test。** 也没有形成可用于论文效果结论的证据。
- **没有正式双人盲标。** 30 条 gold 的 `28/1/1` 分布仍不能支持方法优越性比较。

## 5. 下一位执行者的建议顺序

1. 检出并确认分支 `codex/ab-research-handoff-20261017`，使用仓库 `.venv`，确认工作树 clean 且 HEAD 与 upstream 一致。
2. 不要复用 r3/r4/r5 输出，不要覆盖旧 run。只从 r6 配置创建新的 development preflight snapshot 和 run manifest。
3. baseline 命令必须显式设置 `T2V_TTS_BACKEND=sapi`，并移除 `T2V_RESEARCH_GENERATION_V2`；固定 voice、rate、theme、browser、fps、timing mode 和 repair=0。
4. baseline 成功后，P0 必须复用 r6 baseline 的冻结音频目录，并显式使用 Track A r10 proposition graph 与 visual decisions。
5. 比较 10 个 WAV、35 条原始 sentence cues、source/script/theme/duration 的 hash；检查 SRT 显示 cue 最大时长不超过 8 秒和 quality report 无长字幕告警。
6. 检查 runtime trace/browser evidence，再从 baseline/P0 最终 MP4 抽帧并人工观看；没有人工 final-video 证据不得通过 Gate 1B。
7. 单独设计 candidate-subset 到 P0 acquisition/retrieval 的明确适配层；不要把现有 subset 直接伪装成 retrieval catalog。
8. 只有本地单课 paired run 和人工复核通过后，才讨论服务器单课；仍不得直接批量。

## 6. 失败产物与 Git 边界

- r3、r4、r5 均位于被忽略的 `.local/research_runs/`，必须保留但不会上传 GitHub。
- Git 中只保存代码、测试、冻结配置/manifest 和文字报告；音频、视频、凭据、私人 URL、腾讯文档 token 不得进入 Git。
- 失败 run 的具体状态以各自 `manifest.json` 为准；不能删除失败、手改中间结果后宣称成功，也不能用云端 r2 摘要替代本机缺失的不可变 bundle。
