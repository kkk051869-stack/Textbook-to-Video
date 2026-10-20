# A/B 统一研究执行规程与未来路线图

> 状态：工作规程 v1.5
> 制定日期：2026-10-15
> 最近修订：2026-10-18（完成真实 lesson_002 Track A development smoke，并记录零 gold 对齐与后续边界）
> 适用范围：Textbook-to-Video 教学原则研究、内部系统实验、PresentAgent 外部对照、人工标注与论文结果整理
> 当前组织前提：同一负责人承担原成员 A 与成员 B 的全部工作；A/B 从“人员分工”改为“研究轨道名称”
> 编写基线：交接分支 `codex/ab-research-handoff-20261017`，从已推送的 AB 基线提交 `3b550112` 创建（交接文档提交后 HEAD 将变化）
> 协作镜像：腾讯文档“Text2vedio同步文档”（链接仅在协作渠道保存，不写入可能公开的 Git 仓库）

## 1. 文档目的与效力

本规程解决三个问题：

1. 在同一负责人同时承担 A、B 全部工作的情况下，如何避免两套代码、两套环境和反复交接；
2. 如何约束 AI 在长周期研究中不擅自改目标、改标签、改实验或把未验证产物写成结论；
3. 如何从当前代码状态推进到可复现的正式实验和可信论文结论。

本规程以以下文档的研究范围和科学边界为依据：

- [教学原则驱动的教材教学视频生成研究计划](教学原则驱动的教材教学视频生成_研究计划.md)；
- [教学原则驱动的教材教学视频生成研究思路报告](教学原则驱动的教材教学视频生成_研究思路报告.md)。

上述文档中的研究问题、P0/P1/P2 边界、证据链和可证伪条件继续有效；其中“成员 A / 成员 B 分别维护代码和定期交接”的安排不再适用。对于组织方式、分支管理、执行顺序和 AI 行为，本规程取代 [双人工作计划](双人工作计划.md) 和 [A 线合并状态与下一步](A线合并状态与下一步.md) 中与“仅负责单线”有关的规定。旧文档保留作历史依据，不删除、不覆盖。

发生冲突时按以下顺序处理：

1. 用户当前明确批准的研究决策；
2. 已冻结的数据契约、标注协议、数据集 manifest 和 preregistration；
3. 本规程的执行与治理规则；
4. 两份研究主文档的科学范围；
5. 旧工作计划、旧运行记录和聊天记录。

聊天记录不是长期事实来源。任何影响研究问题、标签、数据、条件、指标或论文主张的决定，都必须落入版本化文件。

## 2. A/B 的新定义

从本规程开始，A/B 不再表示两名代码维护者，也不表示两个长期 Git 分支。

| 名称 | 研究责任 | 主要产物 |
|---|---|---|
| Track A：Visual Decision | knowledge proposition、source evidence、视觉支持必要性、教材图复用、检索/生成触发、候选视觉与 acquisition | proposition graph、visual decisions、candidate pool、acquisition records、RQ1 指标 |
| Track B：Dynamic Alignment & Evaluation | narration proposition、语义绑定、动态事件、timing/signaling、runtime trace、rendered evidence、事件级评价 | binding results、dynamic plan、timed storyboard、animation trace、render evidence、RQ2/RQ3 指标 |
| Integrated AB | 同一输入、同一代码、同一版本下的端到端决策链和消融 | 可执行计划、成片、manifest、端到端消融结果 |

必须遵守：

- A、B 使用同一仓库、同一 commit、同一环境和同一份冻结输入；
- A、B 的差异通过版本化配置、feature flag 和输出目录表达，不通过两套长期代码表达；
- `C00/C01/C10/C11` 等实验条件是 treatment，不得再称为“成员 A/B 的版本”；
- PresentAgent 是外部参照系统，不是 Track B；
- 一名主执行者可以运行全部轨道，但人工标注和关键结果审查仍需保持盲化与独立性。

## 3. 不可改变的研究主线

### 3.1 P0 核心问题

P0 只保留连续的三层问题：

1. RQ1：Coherence 与 Multimedia 如何形成 proposition-level 的视觉支持与检索触发决策；
2. RQ2：显式 proposition→visual binding 与动态事件规划能否改善对象、时机和 signaling；
3. RQ3：plan、runtime 与 final-video evidence 能否可靠验证并定位上述决策。

统一因果链为：

```text
source
  → knowledge proposition
  → visual support / acquisition decision
  → narration proposition
  → proposition–visual binding
  → event and signaling plan
  → planned schedule
  → runtime execution trace
  → final-video observation
  → evaluation and bounded claim
```

任何实现、指标或论文段落都必须能指出自己位于这条链的哪一层。无法定位的新增模块默认不进入 P0。

### 3.2 P1 与 P2 边界

以下内容不允许为了“让结果更丰富”而混入 P0：

- P1：通用 AI 配图、自动多轮修复、layout/semantic/temporal 联合优化、repair convergence；
- P2：学习者实验、认知负荷、跨语言/跨领域泛化、presenter/Image Principle、生产级版权治理。

P1 功能可以存在于代码中，但默认关闭，不能成为 P0 正式实验的未记录变量。没有真实学习者实验时，禁止声称“提高学习效果”。

### 3.3 贡献必须可删除

每项候选贡献都必须有失败路径：

- visual need/retrieval 无法稳定标注：收缩为 Visual Necessity 分析；
- proposed 不优于 always/never/direct LLM：删除方法增益主张；
- no-source 消融无稳定影响：删除 source-conditioned 修饰；
- semantic binding 不优于 lexical/embedding/direct model：不进入 timing 方法主张；
- proposition-aware timing 不优于 current semantic timing：只保留 binding；
- event evaluator 无定位优势：降为人工评价协议；
- final-video visibility 不可靠：只报告 runtime onset 和人工可判定窗口。

不允许通过更换指标、删掉不利样本或临时增加模块来“救结论”。

## 4. 当前代码与证据状态快照

截至 2026-10-17，本节只记录可由当前工作树、远端引用、文件或测试证明的状态：

| 项目 | 当前状态 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| Git 基线 | `codex/organize-local-workspace` 的本地与远端均为 `3b550112`；交接分支 `codex/ab-research-handoff-20261017` 从该提交创建 | A 选择性集成、AB 门禁与收口记录已进入可审计远端基线 | 不代表真实课节已在服务器复现 |
| Python 环境 | 项目 `.venv` 为 Python 3.12.14，`jsonschema 4.26.0` | 本地测试环境满足 Python 3.11+ 与 Draft 2020-12 需求 | 不代表服务器环境相同 |
| 自动测试 | 收口时全量 `445 passed`；研究定向子集 `31 passed`；最终独立复审在其范围内为 `P0=0 / P1=0 / P2=0` | 当前工程、契约和已覆盖的 fail-closed 边界通过本地验证 | 不代表真实模型、真实课节、浏览器成片或研究结论正确 |
| G0 契约 | `research-generation-v2-v0.1`、mock package、animation trace 已存在 | schema 和跨文件关系具有测试基础 | 不代表所有真实数据已经按契约生成 |
| Track A 代码 | proposition graph、source evidence、visual decision、acquisition、candidate pool、gold alignment、deterministic baselines 已存在 | A 侧主要接口已进入统一代码 | 尚无当前合并 commit 对冻结真实课节的完整预测/评测结果 |
| Track B 代码 | binding methods、dynamic planner、signaling policy/diagnostics、P0 integration、runtime/render evidence 已存在 | B 侧方法骨架与 production 接入已经存在 | final-video visibility 仍默认 `not_reviewed`，不能由 runtime trace 代替 |
| 30 条 gold | `FROZEN / HUMAN_REVIEWED_GOLD / CONFIRMED_BY_USER`；`none=28 / source-sufficient=1 / extra-support-needed=1` | 可做接口回归、对齐检查和探索性诊断 | 不是双盲独立标注数据，不能证明外部准确率、一致性或方法优越性 |
| 实验预检 | development + rendering 已在 PowerShell 7 与 Windows PowerShell 5.1 通过；配置、dataset manifest、frozen-file manifest 均有严格 schema 和语义/hash/隔离校验 | 本地门禁能拒绝未冻结、越权引用、gold 泄漏、覆盖旧输出和多类路径绕过 | 目前没有可运行的正式配置，也没有正式 run manifest 执行入口 |
| A 历史导入 | `.local/a_research_import` 保存 annotation/dry_run | 可追溯旧 A 工作和人工确认过程 | 属于历史来源，不是当前 AB commit 的新实验结果 |
| 旧服务器实验 | 已有 8 课节 × 3 系统的 24 个视频和部分自动检查 | 证明旧版本实验链曾经运行 | 早于当前合并；不能自动代表当前代码的正式结果 |

当前还存在以下正式实验阻塞：

1. 仓库根目录没有 `.env`，当前没有已验证的真实 LLM 凭据；密钥只允许在接手人的本机或受保护环境中配置，禁止提交；
2. 仓库内没有真实 `lesson_002` 冻结输入，也没有与之配套的严格 dataset/frozen manifests；
3. `configs/experiments/` 只有不可直接执行的 TEMPLATE，没有 `config_status=RUNNABLE` 的正式配置；
4. 根据已验证配置与环境快照生成不可变 run manifest 的正式执行入口尚未实现；在此之前只能完成预检，不能把运行称为正式实验；
5. 尚无针对当前合并 commit 的真实单课结构化 smoke 或端到端成片记录；
6. 当前 30 条 gold 正类各只有 1 条，也没有两个独立盲化标注视角，不能承担正式方法比较；
7. 旧 PresentAgent/内部视频结果仍有 OCR、乱码、教材图真实出现情况等未完成 final-video 人工确认项。

因此，当前阶段定义为：**AB 统一代码、开发门禁、测试和远端基线已经收口；Gate 1A 为 `TESTED_MOCK`，Gate 1B 只完成机器门禁实现、尚未正式通过。下一步仍是本地准备真实单课和 run-manifest 入口，不是直接上服务器。**

## 5. 单一事实源与工作区规则

### 5.1 唯一代码事实源

- 当前统一工作树为 `Textbook-to-Video-worktrees/organize-local-workspace`；
- 原 A 单线 G0 工作区是只读来源与历史归档，不得被合并产物覆盖；
- 任何需要保留的 A 内容必须经过选择性合并进入统一仓库；
- 服务器不得形成另一套未回传的代码事实源；服务器只拉取已推送 commit；
- 禁止在本地 AB、A 归档、服务器三处同时手改同一功能。

### 5.2 分支规则

- 长期只保留稳定主线和一个短期集成/实验分支；
- Track A 与 Track B 不再各建长期分支；
- 每个提交只表达一个可解释变更：contract、method、runtime、evaluation、documentation 分开提交；
- 生成视频、音频、缓存、模型权重、`.env` 和批量运行目录不得提交 Git；
- gold、schema、prompt、配置和小型 manifest 必须进 Git；
- 正式运行前必须 `git status --short` 为空，并记录 `git rev-parse HEAD`；
- 服务器只能 `git pull --ff-only` 或检出指定 commit，禁止直接改后再忘记回传。

### 5.3 冻结与迁移

- 已冻结的 `research-generation-v2-v0.1` 不原地改语义；
- 不兼容变更必须新建版本并提供 migration、测试和变更说明；
- migration 输出必须标明 `producer`，不得伪装成人工或模型 gold；
- artifact 字段存在只表示“可存储”，不表示相应研究能力已经实现或验证。

### 5.4 Git 与腾讯文档同步规则

- Git 中的本 Markdown 是可审计、可回滚的权威版本；腾讯文档是供同学阅读、反馈和协作审阅的镜像；
- 影响研究范围、Gate、数据、标签、指标或 claim 的云端反馈，必须先核对当前统一工作树，再合入本文件；
- 不得直接用本地全文覆盖尚未归档的云端反馈；同步前先读取云端正文，并在本文件的“协作反馈处理记录”中留下采纳/不采纳及证据；
- 本文件发生实质修改后，同一任务内同步腾讯文档，并核对标题、首段、末段和正文长度；
- 云端临时讨论不能单独充当研究事实源；最终规则必须进入 Git commit，云端镜像注明对应 commit 或待提交状态；
- 腾讯文档 Token 仅保存在用户环境变量或受保护凭据中，不写入仓库、文档、日志、manifest 或聊天摘要。

## 6. AI 执行规矩

### 6.1 每次任务必须有任务合同

任何会改代码、数据、配置或实验产物的 AI 任务，开始前必须明确：

```text
目标：本次只解决什么问题
允许修改：明确文件或目录
禁止修改：gold、冻结 schema、实验定义、论文结论等
输入：版本、路径、hash、配置
预期输出：代码/报告/运行包
验收命令：pytest、schema、smoke 或指标脚本
停止条件：遇到哪些情况必须停下而不能猜
```

任务合同未明确时，AI 只允许做只读检查和提出方案，不允许扩张研究范围。

### 6.2 AI 不得自行做的决定

未经用户明确批准，AI 不得：

- 改 RQ、P0/P1/P2 边界、主要指标或正式数据集；
- 修改 frozen gold、人工标注或将 proxy 自动升级为 human gold；
- 将 `uncertain/abstain/NO_MATCH/not_reviewed` 强行改成正例；
- 把模型 rationale 当作 source evidence；
- 把 runtime event 当成 final-video visibility；
- 用 gold 内容进入生成 prompt、候选检索、规划或排序；
- 因测试难过而删除 baseline、降低阈值或跳过失败案例；
- 在 locked test 上反复调 prompt、阈值或选择模型；
- 只汇报成功尝试而隐藏失败、超时、重试和人工修复；
- 根据聊天记忆猜路径、环境、分支或数据版本。

### 6.3 主执行与独立验证

统一负责人可以让一个 AI 主执行 A+B 代码和运行，但必须设置独立验证步骤：

- 主执行 AI：实现、测试、生成 run bundle；
- 审查 AI：使用新的任务上下文，只读检查 diff、manifest、泄漏和指标，不直接改代码；
- 人工：批准 gold、实验定义、claim gate 和最终异常处理。

同一个 AI 的“自我复核”只能算工程检查，不能算独立标注或独立研究验证。

### 6.4 证据优先

所有状态结论必须指向可复核证据：Git commit、测试输出、JSON、hash、日志、帧、视频或人工签名。禁止使用“看起来已完成”“应该没问题”“大概一致”作为 gate 结论。

## 7. 环境与依赖规则

### 7.1 本地解释器

- 项目要求 Python 3.11+；
- Windows 优先使用仓库 `.venv\Scripts\python.exe`；
- 每次 Python 任务前记录 `sys.executable`、`sys.version` 和关键依赖版本；
- 禁止未经检查直接调用 shell 默认 `python`；
- `jsonschema` 必须满足 `>=4.18` 且能导入 `Draft202012Validator`。

### 7.2 依赖锁定

正式实验前必须新增可复现锁文件或等价的环境快照，至少记录：

- Python、pip、Playwright、浏览器、ffmpeg；
- `jsonschema`、`litellm`、TTS 后端及其版本；
- 模型 provider、model ID、API base 的非敏感标识；
- 操作系统、CUDA/GPU（如使用）、字体和 LibreOffice；
- 依赖安装命令和校验命令。

`.env` 和密钥永不进入 Git、日志、manifest 或聊天输出。

### 7.3 Preflight 是强制 gate

正式运行入口必须先执行统一 preflight，检查：

1. 项目解释器和依赖；
2. Git 工作树、branch、commit、远端同步状态；
3. schema、gold、输入数据、prompt 和配置 hash；
4. ffmpeg、浏览器、TTS、LLM/VLM 可用性；
5. 输出目录不存在或为空，不覆盖旧 run；
6. 数据 split 与模式匹配，locked test 未被开发模式调用；
7. 本地/服务器磁盘空间和权限；
8. 所需输入文件完整，禁止缺文件时自动构造“替代结果”。

任何一项失败都必须停止并给出明确错误，不允许静默 fallback 到另一解释器、另一模型或另一份数据。

## 8. 数据契约与证据链规则

### 8.1 ID 与关联

- 所有关联必须通过稳定 ID 或经审计的文本映射；
- 禁止按数组顺序猜旧、新 ID；
- 重复、缺失、歧义、跨课节引用必须显式失败；
- knowledge proposition 与 narration proposition 不得混为同一对象；
- one-to-many、many-to-one 和 abstain 必须可表达；
- proposition→visual→event 的每条边都应能回溯到 source 或明确说明无 source。

### 8.2 四层时间证据

严格区分：

1. `timed_storyboard`：planned trigger/time；
2. compiled timeline：HTML/runtime 的 start/duration；
3. `animation-trace-v0.1`：浏览器实际 dispatch、target resolution 和 status；
4. `render-evidence-v0.1`：最终 MP4 中人工/CV 观测的可见区间。

低层证据不能冒充高层证据。若最终视频尚未观测，必须保留 `not_reviewed` 或 `unobservable`。

### 8.3 产物状态

每个自动字段和实验产物必须记录：

- `producer`、版本、模型/provider；
- confidence 与 abstain reason；
- 输入路径与 SHA-256；
- artifact type、schema version、生成时间；
- 成功、失败、部分完成、未运行等状态。

`NOT_RUN`、`NO_MATCH`、`ABSTAIN`、`UNCERTAIN` 和 `FAILED` 都是合法结果，不得为了表格完整伪造预测。

## 9. Gold、标注与污染控制

### 9.1 当前 30 条 gold 的用途

当前 30 条 human-reviewed gold 只允许用于：

- schema 和 ID 对齐回归；
- baseline 复现；
- 当前分支预测的探索性诊断；
- 发现标签定义、接口和评测代码错误。

由于标签分布为 `none=28 / source-sufficient=1 / extra-support-needed=1`，禁止用它单独选择最终方法、阈值或论文主张。

### 9.2 Gold 永远是评测输入

- gold 只能在预测完成后由 evaluator 读取；
- 生成、检索、候选排序、binding、timing 和 signaling 阶段不得读取 gold；
- 运行 manifest 必须记录 gold 只进入 evaluation stage；
- 若发现泄漏，该 run 整体作废，不只删除某个指标。

### 9.3 正式标注

即使同一负责人统一开发 A+B，正式 gold 仍需两个相互盲化的标注视角。建议使用 `annotator_1`、`annotator_2`，避免与 Track A/B 混名。

流程必须是：

```text
冻结 annotation packet
  → 两份独立标注
  → agreement 报告
  → 保留分歧
  → 人工 adjudication
  → 冻结 gold 与 hash
```

AI proxy 可帮助生成候选标注和 review packet，但必须标为 `PROXY`；没有两名真实独立标注者时，不得声称 inter-annotator agreement。原研究门槛继续适用：proposition boundary agreement 目标不低于 0.80，核心分类 κ/α 预注册目标不低于 0.67；未达标则按研究计划收缩问题。

### 9.4 数据 split

- dev：允许调试 prompt、阈值和实现；
- validation：用于一次或有限次数的模型/配置选择，并记录每次使用；
- locked test：方法、prompt、阈值和候选池冻结后只运行一次；
- split 必须按 document，而不是 proposition 随机拆分，避免同文档泄漏；
- 5 个旧 pilot 和 30 条当前 gold 是否进入 dev，必须在 manifest 中明确；不得临时改为 test。

## 10. 实验结构与公平性

### 10.1 Experiment 1：Visual Support / Retrieval Decision

比较至少包括：

- Never Retrieve；
- Always Retrieve；
- keyword/visual-type heuristic；
- Direct LLM decision；
- no-source decision；
- proposed source- and proposition-conditioned policy。

主要指标：macro-F1、per-class recall、coverage、abstention、calibration、retrieval cost、候选 appropriateness。need 与 acquisition/retrieval 必须分开计分。

RQ1 的公平性不是让所有方法直接拿到同一“最终候选池”。所有条件必须共享同一教材、source evidence、检索语料库和候选宇宙；各方法仍应独立输出 `none/reuse/retrieve/no-match` 及自己的候选选择，否则会抹掉 RQ1 正在比较的决策差异。

### 10.2 Experiment 2：Semantic-Temporal Dynamic Alignment

所有方法必须使用同一冻结 proposition 与候选池。比较至少包括：

- lexical/Jaccard；
- embedding；
- Direct LLM/VLM；
- current sentence/element 或 semantic timing；
- proposed proposition-aware binding + planning；
- proposed without signaling 与 with signaling。

主要指标：binding/target accuracy、onset error、window overlap、early/late/missing/wrong-target、signal density/overload，以及无法观测比例。

### 10.3 Experiment 3：端到端消融

在同一 Textbook-to-Video platform 上比较：

1. frozen v1；
2. `+ Visual Support/Triggering`；
3. `+ Semantic Binding`；
4. `+ Dynamic Planning`。

禁止给各条件使用不同的 source、讲稿、音频、主题、时长预算或模型成本。候选资产按阶段处理：RQ1 条件共享检索语料库和候选宇宙，但允许产生不同的检索/复用决策；进入 RQ2 的 binding/timing 比较后，必须冻结并共享同一候选子集。需要严格配对的后续阶段，应复用 frozen narration/audio/candidate pool。

### 10.4 PresentAgent 的位置

- PresentAgent 只作为外部参照与评价迁移对象；
- 不替代子任务 baseline；
- 不因 PresentAgent 结果较好或较差而改变内部方法；
- 只有输入数据、PresentAgent commit、配置、模型和产物 hash 一致时，旧外部结果才可复用；
- 当前合并修改影响内部字幕、字体、动画、音频和模板，若论文声称使用当前 merged system，内部正式视频原则上需要重跑；
- 复用或重跑必须在实验 manifest 中逐系统说明。

### 10.5 两套数据范围不得混写

现有资料同时涉及：

- 8 课节的内部系统/PresentAgent 成片对照；
- Doc2Present 30 份 source 的方法与泛化计划。

它们必须有不同的 dataset ID、manifest、用途和结果表。正式实验前要明确 primary dataset、pilot dataset、external reference dataset，不能把 8 课节结果写成 30 文档方法实验，也不能把 30 条 proposition gold 写成 30 文档 test。

## 11. 本地与服务器职责

### 11.1 必须先在本地完成

- 代码、schema、配置和文档修改；
- 单元测试、契约测试、critical static checks；
- deterministic baseline；
- 一个真实课节的结构化 smoke；
- gold alignment 与泄漏检查；
- 小规模 API 调用和失败路径验证；
- run manifest 生成与恢复测试。

服务器不是调试代码的第一现场。若本地可稳定复现的错误，不得靠反复服务器运行试错。

### 11.2 服务器承担

- GPU、本地大模型、VLM/OCR 和高成本 TTS；
- 多课节批处理和完整成片；
- 统一 Linux 环境下的正式复现；
- 大规模帧抽取、视觉检查和结果归档。

服务器正式运行前必须满足：commit 已推送、配置已冻结、本地工作树干净、本地 gate 通过、输出路径全新、服务器 preflight 通过。

### 11.3 升级顺序

```text
本地 schema/unit tests
  → 本地真实单课结构化 smoke
  → 本地 gold alignment / method report
  → 服务器单课完整成片 smoke
  → 单课人工视觉检查
  → 小批量 2–3 课节 pilot
  → 冻结方法与配置
  → 正式批量实验
```

禁止从 mock tests 直接跳到 8/30 份正式批量运行。

## 12. Gate 制度

### Gate 0：研究与契约冻结

通过条件：RQ、标签、ID、目录、mock、schema、split 角色清楚。当前 `research-generation-v2-v0.1` 基本完成；不兼容修改必须走 migration。

### Gate 1A：代码工程就绪

通过条件：

- 项目 `.venv` 可识别；
- 全量 pytest 通过；
- touched files 的 Ruff 通过；
- 全仓库至少通过关键错误检查（未定义名称、语法、明显导入错误）；
- 已知 `target_ids` 未定义问题在当前统一工作树中修复并新增直接测试。

当前状态：**本地通过，待提交**。权威工作树已修复 `target_ids` 作用域错误并新增直接回归测试；项目 `.venv`、全量 pytest、四个 touched files 的完整 Ruff，以及全仓库 `F821/F841` 检查均通过。提交前仍需审查 diff；该状态不等于 Gate 1B 或正式实验就绪。

### Gate 1B：可复现实验就绪

通过条件：

- `doctor`/实验 preflight 通过；
- 工作树干净，目标 commit 已推送并可由服务器精确拉取；
- 实验输入、配置、prompt、schema、gold、候选宇宙及其 hash 已记录；
- run manifest、唯一 run ID、全新输出目录和失败恢复规则已准备；
- 服务器环境快照与本地 gate 结果可追溯。

当前状态：**未通过**，原因是当前文档改动尚未提交/推送，且实验 preflight、真实课节 run bundle 和输入冻结记录尚未完成。

### Gate 2：真实结构化单课

至少选择一个冻结真实课节，产出并验证：

- source evidence；
- proposition graph；
- visual decisions；
- acquisition/candidate pool；
- binding comparison；
- dynamic plan；
- gold alignment（若该课在 gold 中）；
- manifest 和输入/输出 hash。

不允许用 mock 产物替代。

### Gate 3：服务器单课成片

同一 commit 在服务器完成一个课节的 baseline 与 P0 配对成片，检查：

- 输入、讲稿、音频和候选池是否严格配对；
- HTML、MP4、字幕、字体、中文、音频、分辨率、帧率；
- runtime trace 与 target resolution；
- final-video 人工/CV observation；
- 可恢复重跑是否产生一致结构化产物。

### Gate 4：正式标注与候选池

通过条件：正式 annotation packet 冻结、双份独立标注完成、agreement 达标或问题已收缩、candidate pool 覆盖要求满足、`NO_MATCH` 保留。

### Gate 5：方法与分析冻结

冻结：代码 commit、prompt、模型、阈值、候选池、随机种子、失败规则、主结果选择规则和统计脚本。此后 locked test 不再调参。

### Gate 6：正式批量运行

使用全新 run ID 和只读输入完成批量实验。失败重试必须保留原 attempt，不得覆盖。

### Gate 7：结果与 claim 审计

先生成盲化结果表，再做统计和 claim gate。任何未通过 contribution gate 的内容从论文主要贡献中删除或降级。

## 13. 每次运行的标准程序

### 13.1 Run ID 与目录

建议统一为：

```text
runs/<study_id>/<run_id>/
  manifest.json
  README.md
  configs/
  logs/
  cases/<case_id>/<condition>/
  metrics/
  failures/
```

`run_id` 必须唯一且不可复用。正式输出目录不得“清空后重跑”；使用新 attempt 目录。

### 13.2 运行前

必须记录：

- Git commit、branch、dirty 状态；
- Python/依赖/OS/浏览器/ffmpeg/GPU；
- dataset、split、case list 及 SHA-256；
- config、prompt、schema、gold、候选池 SHA-256；
- provider/model、temperature、seed、timeout、retry；
- treatment、baseline、输入复用规则；
- 预期产物和停止条件。

### 13.3 运行中

- stdout/stderr 写日志；
- 每个 case 独立状态，单个失败不覆盖其他 case；
- 网络、模型、TTS 和渲染重试计数必须保存；
- 人工改动必须形成 patch 或 correction record；
- 不允许在一个 run 进行中修改代码、prompt 或配置；
- 如果必须修复，关闭当前 run，生成新 commit 和新 run ID。

### 13.4 运行后

- 校验 schema、跨文件 ID、hash 和文件完整性；
- 输出 success/failed/skipped/not-run 数量；
- 保存失败样例，不删除；
- 生成逐项结果，不只生成平均数；
- 对视频执行 ffprobe、字幕/音轨检查、关键帧抽取和人工抽检；
- 将 manifest 和小型报告提交 Git，大型产物存外部目录并记录路径/hash；
- 结果发布前由只读审查者检查泄漏、配对和选择偏差。

## 14. 测试与质量门禁

测试分四层，任何一层都不能替代另一层：

| 层 | 目的 | 最低要求 |
|---|---|---|
| Unit/contract | 代码和 schema 基本正确 | 全量 pytest；关键静态错误为 0 |
| Real-data smoke | 真实输入能走通且关系正确 | 至少 1 个真实课节、无猜 ID、无虚构资产 |
| Runtime/render | 浏览器和视频真正执行 | target resolved、MP4 可读、音轨/字幕/字体正常 |
| Research validity | 实验能支持主张 | 无泄漏、公平 baseline、冻结 test、独立标注、claim gate |

对当前仓库的 Ruff 历史债务采用“两轨治理”：

- 新增或修改文件不得引入新的 lint 问题；
- 全仓历史格式问题另建清理任务，不与研究方法提交混在一起；
- `F821` 等可能导致运行失败的功能性错误立即阻断实验，不得以“pytest 没覆盖到”为理由忽略。

## 15. Baseline 与消融纪律

- 所有 baseline 使用相同输入、split、候选池和评分脚本；
- Direct LLM/VLM 未调用时必须记录 `NOT_RUN`，不得模拟其输出；
- Always/never/heuristic 即使表现差也不得删除；
- human oracle 只能作为 ceiling，不能与自动方法公平性混写；
- 每个消融只改变一个预先声明因素；
- 若同时改变 prompt、模型、候选池和 timing，则不能归因于单一模块；
- 主要指标和 secondary/exploratory 指标必须提前区分；
- 报告 per-class、coverage、abstention 和 failure，不只报 accuracy；
- document 内的 proposition/event 属于嵌套观察，正式统计使用 document-level bootstrap 或 mixed-effects，而不是把所有 proposition 当独立样本。

## 16. 失败、重试与修复

### 16.1 失败不能被隐藏

每次失败记录：case、stage、错误类型、输入 hash、attempt、是否可重试、最终处置。超时、内容解析失败、目标不存在、候选不足、VLM 拒绝、录制失败都应进入失败统计。

### 16.2 重试

- 重试使用相同输入和配置；若配置变化则视为新 run；
- 重试次数上限预先定义；
- 首次成功率和最终成功率分开报告；
- 禁止只保留质量最好的一次随机输出，除非 selection rule 已预注册并对所有方法相同。

### 16.3 Repair

P1 repair 必须有 `max_iterations`、state hash、objective vector、rollback、重复状态/振荡检测和 patience stop。修复不能覆盖 canonical artifact；每轮作为新 candidate 保存。没有这些条件时，只允许人工诊断，不声称自动闭环优化。

## 17. 文档、状态与审计记录

长期状态必须写入仓库或 run bundle，不能只留在聊天中。至少维护：

```text
docs/研究/AB统一研究执行规程.md
reports/runs/<run_id>.md
logs/issues/issues.csv
configs/experiments/*.yaml
```

每次里程碑状态只使用以下词：

- `PLANNED`：只有计划；
- `IMPLEMENTED`：代码已写，未通过完整验证；
- `TESTED_MOCK`：仅 mock/单元测试通过；
- `PILOTED_REAL`：真实小样本通过；
- `FROZEN`：版本、输入和 hash 已冻结；
- `RUN_COMPLETE`：运行完成但尚未审计；
- `AUDITED`：已完成独立审查；
- `CLAIM_READY`：满足预注册 claim gate。

禁止只写“完成”。必须指出完成的是代码、运行、审查还是论文证据。

## 18. 安全、版权与外部资源

- 密钥、账户、私人路径和未授权数据不得进入 Git；
- 外部视觉必须保存 URL/来源、license/provenance、本地 hash 和获取时间；
- 无明确许可的候选不得进入正式成片或公开数据包；
- AI 生成图必须记录 provider/model/prompt/seed/hash，并与检索图分开；
- PresentAgent、模型权重和第三方代码记录具体 commit/version；
- 删除服务器材料前必须核对 `realpath`、大小和精确目标，不递归删除宽泛目录。

## 19. 从当前位置开始的路线图

### Milestone 0：本地工程收口

1. 修复 `build_timed_storyboard_v2` 的未定义 `target_ids`，补直接测试；（已提交并推送）
2. 建立实验专用 preflight 和依赖/环境快照；（已提交并推送）
3. 为 A/B 配置建立机器可读模板，不再靠长命令手填；（模板和严格验证器已提交，正式 RUNNABLE 配置尚未创建）
4. 全量 pytest、关键 Ruff、schema 和 gold hash 检查通过；（已完成，最近证据为 445 passed）
5. 审查后推送当前合并提交和本规程。（已完成；远端 AB 基线为 `3b550112`）

当前判定：Gate 1A 已通过并标记 `TESTED_MOCK`；Gate 1B 尚缺真实输入、凭据、RUNNABLE 配置与正式 run manifest，因此 Milestone 0 的“正式实验就绪”定义尚未满足。

### Milestone 1：当前 AB 的真实单课闭环

1. 先选 `lesson_002` 做 Track A 的 gold 对齐真实运行；
2. 再选 `lesson_001` 或同一可完整出片课节做 Integrated AB；
3. 产出完整结构化链、method report、candidate pool、dynamic plan 和 manifest；
4. 本地检查无泄漏、无歧义 ID、无虚构视觉；
5. 服务器只跑一个课节的 baseline/P0 配对成片并人工检查。

完成定义：Gate 2 和 Gate 3 通过。

### Milestone 2：正式标注和评测集修复

1. 扩充正类与边界样本，避免 28/1/1 决定方法；
2. 冻结 annotation packet；
3. 完成两个真实独立标注视角、agreement 和 adjudication；
4. 冻结 dev/validation/locked test 及文档级 split；
5. 冻结候选池、`NO_MATCH` 和 provenance。

完成定义：Gate 4 通过。

### Milestone 3：RQ1 与 RQ2 方法实验

1. 先跑 deterministic baselines；
2. 再跑 Direct LLM/VLM 和 proposed；
3. 所有 binding 方法共享候选池；
4. timing 使用实测 sentence/proposition cues；
5. validation 选择完成后冻结方法与统计脚本。

完成定义：Gate 5 通过。

### Milestone 4：正式服务器批量实验

1. 先 2–3 课节小批量；
2. 再运行冻结的 8 课节成片对照；
3. 若执行 Doc2Present 30 文档实验，使用独立 study ID 和 manifest；
4. 当前 merged internal conditions 需要按冻结 commit 重跑；
5. PresentAgent 是否复用由输入和环境 hash 决定。

完成定义：Gate 6 通过。

### Milestone 5：评价、统计与论文

1. 完成 final-video observation，而不是停在 runtime trace；
2. 完成 OCR/VLM/人工视觉确认和错误归因；
3. 先盲化评分，后揭示 condition；
4. 执行 document-level 统计；
5. 按 claim gate 删除不成立的贡献；
6. 保存论文表图所对应的 run ID、脚本和 hash。

完成定义：Gate 7 通过且相关结论达到 `CLAIM_READY`。

## 20. 一票否决项

出现以下任一情况，正式实验或论文主张必须暂停：

- 工作树 dirty 或服务器 commit 与 manifest 不一致；
- gold 泄漏到生成、检索、排序或规划；
- locked test 被用于调参；
- schema/ID 通过顺序猜测补齐；
- 缺失资产被自动替换为未记录生成物；
- runtime trace 被写成 final-video visibility；
- 失败样本被删除或只保留最佳随机结果；
- proxy/AI 标注被写成双人人工 gold；
- baseline 输入、候选池、讲稿或音频不一致；
- 依赖、模型或 prompt 变化但沿用原 run ID；
- 存在功能性静态错误或真实单课尚未跑通却开始批量实验；
- 用旧服务器结果声称当前 merged commit 的效果而无版本说明。

## 21. 每次开始工作的最短检查表

```text
[ ] 当前任务合同已写清目标、允许/禁止修改、验收和停止条件
[ ] 使用统一 AB 工作树，不修改 A 归档和服务器代码
[ ] 已确认解释器、依赖、branch、commit、dirty 状态
[ ] 已确认本次是开发、pilot、validation 还是 locked test
[ ] 已确认 gold 不进入生成链
[ ] 已确认输入、配置、prompt、候选池和输出目录
[ ] 已运行相关 pytest、schema 和 critical static checks
[ ] 真实运行前已生成唯一 run ID 和 manifest
[ ] 失败、重试和人工修改都有记录位置
[ ] 结果只支持已通过的 claim，不从工程通过跳到研究结论
```

## 22. 核心原则总结

以后不再采用“一个人做 A、另一个人做 B、最后把两套代码合并”的方式。统一做法是：

> **一个集成代码事实源、两个研究轨道、同一套冻结输入、分层证据、独立审查、逐 gate 晋级。**

统一负责人负责整条链并不会降低科学要求。恰恰因为没有天然的人员边界，更要通过盲化标注、只读审查、冻结 hash、不可覆盖 run、严格 claim gate 和机器可执行检查，主动制造必要的独立性与可追溯性。

## 23. 协作反馈处理记录

### 2026-10-15：腾讯文档首轮反馈

1. **“删除 `target_ids` 未定义阻塞”——不采纳。** 反馈引用的是另一 checkout 的文件；在当前权威工作树的 `build_timed_storyboard_v2` 中，`target_ids` 仍未在函数作用域定义。该项保留到当前分支修复并新增直接测试为止。
2. **“候选池规则需要区分 RQ1 与 RQ2”——采纳。** RQ1 改为共享 source、检索语料库和候选宇宙，但保留方法各自的检索与候选决策；RQ2 的 binding/timing 比较共享冻结候选子集。
3. **“Gate 1 拆成工程就绪与实验就绪”——采纳。** 原 Gate 1 拆为 Gate 1A 与 Gate 1B，避免 Git/服务器暂时不可用被误写成代码工程失败，同时两者仍必须在正式实验前全部通过。

本记录用于保留云端审阅的处理结果；后续每次实质反馈均按同样格式记录“结论、证据、修改位置”。

## 24. 统一执行日志

### 2026-10-15：Milestone 0 / Gate 1A 工程收口（进行中）

**任务合同**

- 目标：先修复 `build_timed_storyboard_v2` 的目标元素 ID 映射错误并补直接回归测试，再执行 Gate 1A 验证；
- 允许修改：`src/textbook2video/research/proposition_schema.py`、对应测试、本执行日志；
- 禁止修改：gold、冻结 schema 语义、RQ、实验条件、A 单线归档和服务器代码；
- 验收：项目 `.venv` 下相关 pytest、全量 pytest、touched-file Ruff 与全仓库关键静态检查；
- 停止条件：若 storyboard 到 timed storyboard 的 ID 语义不明确，则先补证据，不猜测映射。

**环境证据**

- 权威工作树：`Textbook-to-Video-worktrees/organize-local-workspace`；分支：`codex/organize-local-workspace`；起始 commit：`9e3b934ba14b4592b5f964c373efbc0996ae70c9`；
- 明确使用仓库 `.venv\\Scripts\\python.exe`，实测 Python `3.12.14`；
- 实测 `jsonschema 4.26.0`，`Draft202012Validator` 可导入。此前“默认 Python 3.8 / jsonschema 太旧”不是当前配套环境的事实，后续命令不得退回 shell 默认解释器。

**困难、解决与结果**

1. `target_ids` 在 `build_storyboard_v2` 中定义却未使用，而 `build_timed_storyboard_v2` 在另一个函数作用域直接引用，形成 `NameError` 风险。解决：删除前者的无用局部变量，在 timed 函数内按当前 segment 的 legacy element ID → v2 element ID 重建映射；未改变 schema 或 ID 语义。
2. 新增直接回归测试，验证 legacy animation target 会映射到 `research_generation_v2.element_id`。相关测试结果：`3 passed`。
3. touched-file Ruff 首次暴露两个目标文件原有的 52 条格式/导入债务。解决：只对这两个已触碰文件执行机械格式化和 import 修复，不扩散到其他模块；复查结果：touched-file Ruff 通过。
4. 全量测试结果：`416 passed in 27.20s`。
5. 全仓库关键静态检查首次发现两项旧 `F841`：`animation_gen.py` 的 `qa_summary`、`css_hotfix.py` 的 `first`。核对后确认前者调用的是纯汇总函数且结果未参与单页修复，后者从未参与 overlap 修复逻辑；解决：删除无效计算/变量，不改变布局决策。
6. 处理上述文件时，完整 Ruff 进一步暴露 32 条历史导入、长行和无效 f-string 债务。解决：先应用 Ruff 安全修复，再只整理被报告的具体语句；没有执行全文件格式化，也未改变算法分支。
7. 最终复验：四个 touched files 完整 Ruff 通过；全仓库 `ruff --select F821,F841` 通过；全量测试 `416 passed in 25.92s`。

当前结论：Gate 1A 已在本地工作树通过。改动尚未提交/推送，实验 preflight、输入冻结和 run manifest 尚未完成，因此 Gate 1B 仍未通过，正式实验不得启动。

### 2026-10-17：Milestone 0 / Gate 1B 预检与配置收口（进行中）

**任务合同**

- 目标：把实验环境、Git 状态、渲染依赖、LLM 凭据存在性、冻结文件 hash 和 A/B 配置变成可执行预检，不在条件不完整时启动服务器实验；
- 允许修改：预检脚本、实验配置/schema/测试、缺失但被主研究计划引用的 G0 冻结说明、本执行日志；
- 禁止修改：A 归档、gold 内容、冻结 schema 语义、正式 split、服务器代码和任何密钥值；
- 验收：开发模式预检与渲染检查通过；要求 LLM 时能对缺失凭据明确失败；全量 pytest 和关键 Ruff 通过；云端日志与本地事实一致。

**困难、解决与结果**

1. 旧 `check_research_g0_starter.ps1` 调用了 shell 默认 `python`，既不能保证使用仓库配套环境，也没有记录依赖、Git 或输入 hash。解决：预检只接受仓库 `.venv`/`.venv312`，拒绝回退 shell Python；检查 Python `>=3.11`、`jsonschema>=4.18`、`Draft202012Validator`、branch/commit/dirty/ahead/behind、运行工具，并在 `.local/research_preflight/` 生成不含密钥值的唯一环境快照。
2. 新预检首次运行发现 AB 工作树缺少主研究计划明确引用的 `docs/研究/G0_研究数据契约冻结说明.md`。核对 A 归档后确认这是选择性合并遗漏，不是要重新合并整条 A 分支。解决：仅把该文件引入 AB；A 归档未改。引入文件与 A 归档逐字节 SHA-256 相同：`bc7f3ca3b0e35b7489ac21713f38852323426074d5ab3d7e6be967bf35641ce1`。
3. Playwright bundled Chromium 不存在，初版预检因此发出渲染警告；但项目 `doctor` 显示实际支持的 Microsoft Edge 可用。解决：不再只看 bundled Chromium 文件，改为实际执行一次 headless `msedge` 启停探测；`-RequireRendering` 现已通过，`ffmpeg` 也可用。
4. AB 工作树、主仓库、本地旧副本和 A 归档四处均无 `.env`，进程/用户环境也没有 `LLM_API_KEY` 或 `ECNU_API_KEY`。解决：新增只返回布尔值、不输出凭据内容的检查；development 可继续静态工作，`-RequireLLM` 以及 pilot/validation/locked-test 会明确失败。没有猜测、复制或把密钥写入仓库。
5. 规程要求的 A/B 机器可读配置原先不存在。解决：新增版本化 experiment config schema、不可直接执行的单课模板及 fail-closed Python 验证器。正式 commit 不写进配置，避免“配置包含自身 commit”的自引用；而由正式预检强制 `fetch`、clean worktree、`HEAD == upstream`，再把实际 commit 写入不可变环境快照和后续 run manifest。locked test 改为与 `run_id` 绑定、带证据文件 hash 的单次授权记录，而不是布尔开关。
6. 初版验证器只校验直接 `{path, sha256}`，任意 manifest 字段和传递文件仍可能绕过 hash 或夹带 gold。解决：新增 `ab_dataset_manifest_v1` 与 `ab_frozen_file_manifest_v1` 两个严格白名单 schema，拒绝未知字段；逐项校验所有传递文件的仓库内路径和 SHA-256，并同时检查 generation/evaluation 路径、内容 hash、文本中直接路径和规范化后的等价路径。
7. 初版 placeholder 规则没有覆盖 `FILL_ME_IN`，development 也可能接受 mode 不匹配的 `RUNNABLE` 配置。解决：扩充占位符规则；仅允许 TEMPLATE 在 development 中跳过可运行性语义，任何 RUNNABLE 配置都必须与请求 mode 一致。pilot/validation/locked-test 还必须使用 Git 已跟踪的配置和全部冻结输入。
8. storyboard 转换原先会对缺失/重复 element ID、未解析 target、缺失 event ID 或非对象 animation 静默跳过或晚失败。解决：legacy→v2 映射和两个 storyboard builder 统一 fail closed，并为成功映射和所有负向边界补直接测试。
9. 初版快照允许外部指定路径，存在覆盖配置/冻结输入以及 junction/symlink 绕过的风险。解决：删除外部快照路径参数；只在固定 `.local/research_preflight/` 下生成 UTC 时间戳加随机 GUID 的文件；目录任一层为 reparse point 即拒绝，并以 `FileMode.CreateNew` 原子创建，绝不覆盖旧文件。
10. Git 文档一度写入腾讯共享文档直链，可能把协作信息带到公开仓库。解决：仓库只保留“协作渠道中的腾讯文档”说明，不保存 URL、文档 ID 或 token；全仓敏感字样扫描无命中。腾讯文档 token 仅保留在本机环境/连接配置中。
11. 第四轮只读审查继续发现两个 P1：已声明 JSON 还能指向未声明的本地二级文件；两个 storyboard builder 仍允许重复 `event_id`。解决：扫描每个已声明 generation 文件中的 JSON 字符串、同对象路径片段组合和文本路径 token，按仓库根及来源文件目录解析；只要指向现存本地文件，就必须已在严格 manifest 中声明并通过 hash，否则拒绝。两个 builder 对完整 artifact 维护事件 ID 集合，重复即失败。新增“二级未声明文件”“directory + filename 拼接 gold”“重复 event ID”三个反例回归。
12. 复审反例进一步发现 `file://` URI 会被远程 URL 规则跳过，纯文本 prompt 中的 URI 不会进入 JSON 字符串扫描，Windows `C://` 等价路径会被误判为远程 URL，超长但可规范化的 `./` 路径会被跳过；任意字段两两拼接和大量直接字符串还存在无界候选风险，无 gold 的 development 配置也未执行未声明依赖检查。解决：JSON 与纯文本中的本地 file URI 都先 URL decode；Windows drive path 先于远程 URL 识别；本地长路径先规范化再检查；所有直接字符串、组合字符串、文本路径 token 和 file URI 共用单文件硬上限。本地依赖检查对所有 RUNNABLE mode 生效，任何上限溢出都 fail closed。为每个反例均新增回归。
13. 最终本地证据：全量测试 `445 passed in 24.45s`；全部触碰 Python 文件 Ruff 通过，全仓 `ruff --select F821,F841` 通过，3 个新 JSON Schema 自检通过，`git diff --check` 通过；PowerShell 7 与 Windows PowerShell 5.1 均通过 development + rendering 预检，最新研究子集均为 `31 passed`。要求 LLM 或正式模式仍会因缺少凭据/冻结 RUNNABLE 配置而按预期停止。
14. 最终独立只读复审重新运行四个最新绕过反例、32 条定向测试与全量 445 条测试，结论为 `P0 = 0、P1 = 0、P2 = 0`（限本轮审查范围）；未再发现影响当前正式 gate 的可复现实质缺口。该结论只说明本地工程门禁达到提交条件，不等同于真实单课实验或论文证据完成。
15. 提交前 staged whitespace 检查发现，从 A 归档逐字节引入的 G0 冻结说明原本就使用 Markdown 双空格硬换行，并保留末尾空行；直接清理会破坏已核对的源文件 hash。解决：不改冻结内容，只在 `.gitattributes` 对该精确文件关闭 whitespace 报警；其他文件继续接受完整 `git diff --cached --check`，复验通过。

**当前 Gate 状态**

- Gate 1A：本地通过，状态为 `TESTED_MOCK`；
- Gate 1B：机器门禁与本地环境检查已实现并通过 development 验证，但正式 Gate 尚未通过；
- 尚缺：可用 LLM 凭据、真实输入及严格 dataset/frozen manifests、冻结 RUNNABLE 配置和由其生成的正式 run manifest；
- 本记录写入时的提交前状态：分支 `codex/organize-local-workspace` 相对 upstream `ahead 2 / behind 0`，工作树 dirty；这是开发收口状态，不是正式运行状态；
- 决策：先完成审查、提交、推送和共享文档同步，再准备真实单课输入；当前不启动服务器实验，也不把 development 预检写成正式实验就绪。

### 2026-10-17：Milestone 0 工程提交与远端核验

- 工程收口提交：`92090726f207eae18be251835a1a2418f4342925`（`research: enforce unified AB experiment gates`）；
- 已推送到 `origin/codex/organize-local-workspace`；通过 `git ls-remote` 独立读取远端引用，确认工程提交与远端完全一致，而不是只依据 push 命令输出判断；
- 该次推送同时包含此前尚未推送的两条 A 选择性集成提交，未改写历史、未推送到 `master`、未修改 A 归档；
- 工程提交后的工作树 clean，分支相对 upstream `ahead 0 / behind 0`；本段自身作为后续纯文档提交保存，因此最终远端 HEAD 可在该工程提交之后；
- 当前结论仍是：Milestone 0 的本地工程门禁已达到提交条件，Gate 1B 尚缺真实冻结输入、RUNNABLE 配置、LLM 凭据及正式 run manifest，服务器实验继续暂停。

### 2026-10-17：交接分支与文档收口

- 从远端已核验且工作树 clean 的 AB 基线 `3b550112` 创建新分支 `codex/ab-research-handoff-20261017`；没有修改 `master` 或 A 单线归档；
- 交接复核发现，第 4 节仍保留“415 tests、本地领先远端”等 10 月 15 日历史快照。解决：不删除历史执行日志，而是把顶部事实快照更新为 10 月 17 日证据，并单独新增本交接执行单，避免接手人把旧时点当当前状态；
- 重新以工作树为准搜索：没有 `RUNNABLE` 配置、真实 `lesson_002` 路径、仓库根 `.env` 或正式 run-manifest 执行入口；这些缺口均被明确列为正式 Gate 阻塞，而不是由聊天记忆推断；
- 交接变更没有改代码或冻结数据。验证结果：development + rendering preflight 通过并再次得到研究子集 `31 passed`；单独运行两个相关测试文件为 `32 passed`；全量测试为 `445 passed in 21.19s`；所有新增/修改文档的本地 Markdown 链接可解析；`git diff --check` 通过；
- 初始交接文档提交 `a7e60f6b00f53c1be956230f4a3135d7b3123bcd` 已推送到新分支，并通过 `git ls-remote` 核对远端 SHA 与本地一致、ahead/behind 为 `0/0`；
- 共享文档同步采用“先读取云端、确认无未归档反馈，再全量镜像 Git 权威正文并检查 v1.4、交接分支、Gate 状态和末段清单”的流程。同步前云端仍是已知 v1.3 且没有新增批注或末尾反馈；
- DOC 全文替换使用 `[1, end)` 后，旧文档位置 0 的首字母仍被保留，首次回读把标题显示为 `AA/B`。解决：使用 `find` 返回的真实 `[0, 19)` 坐标精确替换为 `A/B 统一研究执行规程与未来路线图`，不手算其他正文位置；随后再次回读标题、正文长度、v1.4、分支、第 25 节、Gate 阻塞、445 tests 和末段清单，并确认旧 v1.3、415 tests 与临时占位符均不存在。同步失败时保留 Git 提交，不用旧云端内容反向覆盖当前规则。

## 25. 2026-10-17 接手摘要与下一步执行单

本节是交给下一位执行者的最短事实入口。详细文件导航另见 [AB 研究交接说明](AB研究交接说明.md)；两处内容冲突时，以本规程、冻结 manifest 和当前 Git 状态为准，不以聊天摘要为准。

### 25.1 接手时的权威状态

- 权威仓库工作树：`Textbook-to-Video-worktrees/organize-local-workspace`；A 单线 G0 工作区只读，禁止覆盖、回写或把它重新当成开发分支；
- 已完成的 AB 远端基线：`origin/codex/organize-local-workspace`，提交 `3b550112e8cf3ffa1cb3b384388261e63c724392`；
- 本次交接分支：`codex/ab-research-handoff-20261017`，从上述 clean/pushed 基线创建；接手前先核对其远端 HEAD、工作树为空和 upstream 一致；
- `master` 未接收这些研究改动；除非另有明确审批，不得把交接工作直接推到 `master`；
- Git Markdown 是规则的权威版本，腾讯文档是协作镜像。云端有新反馈时先记录到第 23 节并处理，再同步 Git，禁止盲目全文覆盖反馈；
- `.env`、Token、账号、私人路径、视频/音频、缓存和批量运行目录不得提交 Git。腾讯文档 URL 和文档 ID 也只留在协作渠道。

### 25.2 已完成且可继承的工作

1. **A/B 统一完成。** A/B 现在是 Track A（Visual Decision）和 Track B（Dynamic Alignment & Evaluation），不是两个人或两条长期分支。两轨使用同一仓库、commit、冻结输入与环境。
2. **A 的必要内容已选择性进入 AB。** 包括 visual decision、gold alignment、候选/获取接口、协议与 G0 冻结说明；没有把 A 归档整体覆盖到 AB。
3. **G0 数据契约已冻结。** `docs/研究/G0_研究数据契约冻结说明.md` 与 A 归档原件逐字节一致，SHA-256 为 `bc7f3ca3b0e35b7489ac21713f38852323426074d5ab3d7e6be967bf35641ce1`；双空格硬换行和末尾空行是冻结内容，不要为格式清理而改写。
4. **工程缺陷已收口。** `target_ids` 映射、缺失/重复 element ID、缺失/重复 event ID、未解析 target 等路径改为 fail closed，并有回归测试。
5. **正式配置门禁已实现。** 有 experiment config、dataset manifest、frozen-file manifest 三类严格 schema 和 Python 验证器；会检查 hash、模式、split、共享输入、公平条件、gold 隔离、传递本地依赖、路径等价绕过、候选预算和不可覆盖输出。
6. **预检已实现。** `scripts/check_research_g0_starter.ps1` 强制仓库 `.venv`/`.venv312`，检查 Python、依赖、Git、渲染工具、LLM 凭据存在性和冻结 hash，并在 `.local/research_preflight/` 原子写入唯一快照；该目录被忽略且不允许 junction/symlink。
7. **本地环境已核验。** 当前 `.venv` 为 Python 3.12.14、`jsonschema` 4.26.0；Microsoft Edge 可作为 headless 浏览器，`ffmpeg/ffprobe` 可用。不要再调用 shell 默认 Python。
8. **质量证据已收口。** 全量 `445 passed`、研究定向 `31 passed`，触碰文件 Ruff、全仓 `F821/F841`、schema 自检和 diff check 均通过；最终独立只读复审在本轮范围内为 `P0=0 / P1=0 / P2=0`。
9. **远端和共享文档已建立。** AB 基线已经推送并独立读取远端引用核验；本规程已有腾讯文档镜像。旧服务器结果保留为历史证据，但不能冒充当前 commit 的结果。

### 25.3 尚未完成，禁止误报为“可正式实验”

1. 没有已验证的 LLM 凭据或仓库根 `.env`；不要向 Git、日志、manifest 或共享文档写密钥值。
2. 没有真实 `lesson_002` 数据包及严格 dataset/frozen manifests；仓库搜索不到真实 `lesson_002` 路径。
3. 没有 `config_status=RUNNABLE` 的正式配置；`ab_single_lesson_pilot.template.json` 只是模板，验证器应当拒绝它用于正式运行。
4. 没有从已验证配置和环境快照生成正式 run manifest、锁定实际访问输入并启动流水线的入口。
5. 没有当前 commit 的真实单课结构化 smoke、paired baseline/P0 成片或 final-video 人工审查。
6. 30 条 gold 仅是用户确认的最小只读参考：`none=28 / source-sufficient=1 / extra-support-needed=1`，retrieval 为 `no=29 / generation-candidate=1`。它来自既有 proxy 后的人审确认，不等于两个独立盲化标注者，也不足以选最终方法、调阈值或支撑论文效果主张。
7. Gate 2–7 均未通过；任何“真实效果更好”“提高学习效果”“已经可批量实验”的表述都没有当前证据支持。

### 25.4 下一位执行者必须按此顺序继续

1. **先读，不先跑。** 阅读本规程、两份研究主文档、G0 冻结说明、`configs/experiments/README.md` 和三个 AB schema；确认 A/B 是研究轨道。
2. **核对 Git 与环境。** 使用交接分支，确认 clean、upstream、commit 和 `.venv`；只运行 development preflight，不配置服务器。
3. **本机配置 LLM。** 在受保护的本地 `.env` 或进程环境中配置真实凭据，仅检查“存在/可调用”，不打印值、不提交。若所用 provider/API 与模板不符，先版本化修改配置说明和测试，不能临时绕过。
4. **确定真实单课输入。** 由负责人明确 `lesson_002` 的权威源文件、许可、用途和保存位置；若不能确认，不得用相似文件猜测替代。
5. **冻结全部输入。** 创建严格 dataset manifest，以及 source、prompt、candidate universe/subset、script、audio 等 frozen-file manifests；每个传递文件都写仓库相对路径和 SHA-256。gold 只能列在 evaluation 输入。
6. **实现正式 run-manifest 入口。** 入口必须接收验证后的 config 与 preflight snapshot，记录实际 commit、配置/hash、依赖、模型、prompt、输入、输出、随机种子和访问审计；不得覆盖旧 run，也不得在执行后回填伪造的运行前信息。
7. **创建版本化 RUNNABLE pilot 配置。** 从模板复制新文件，替换全部占位符，使用唯一 run ID 和尚不存在的输出目录，固定 mode/split/条件；配置和所有输入必须先进入 Git。
8. **提交并推送后再跑正式预检。** formal preflight 要求 clean、fetch 成功、HEAD 与 upstream 一致、LLM/渲染可用、RUNNABLE 配置和全部 hash 通过；任何失败都先修复，不加跳过开关。
9. **只在本地跑一个真实结构化 smoke。** 先生成 proposition graph、visual decisions、gold alignment（若适用）、binding、dynamic plan、timed storyboard、trace 和 method report；检查 schema、跨文件 ID、gold 隔离与访问日志。
10. **本地证据通过后才上服务器。** 服务器检出同一已推送 commit，先跑一个课节的 baseline/P0 配对，不跑 8/30 份批量；下载或保留不可变 run bundle 后人工查看最终视频。
11. **再决定是否进入 Gate 4。** 在正式方法比较前，扩充正类/边界样本，实施两个独立盲化标注视角、agreement/adjudication，并冻结 dev/validation/locked-test。locked test 在方法冻结后仅授权运行一次。

### 25.5 建议命令（从仓库根目录执行）

```powershell
# 1. 先确认事实源；预期工作树 clean，且 HEAD 与 upstream 一致
git status --short --branch
git rev-parse HEAD
git rev-parse '@{u}'

# 2. 必须使用项目解释器
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import importlib.metadata as m; print(m.version('jsonschema'))"

# 3. 日常开发预检；允许当前正在审查的文档/代码处于 dirty，仅限 development
.\scripts\check_research_g0_starter.ps1 -Mode development -AllowDirty -RequireRendering

# 4. 相关定向与全量测试
.\.venv\Scripts\python.exe -m pytest tests/test_ab_experiment_config.py tests/test_research_generation_v2.py -q
.\.venv\Scripts\python.exe -m pytest -q

# 5. 先单独验证正式配置；不要对模板使用正式参数
.\.venv\Scripts\python.exe -m textbook2video.research.experiment_config `
  configs/experiments/<frozen-run>.json --repo-root . --expected-mode pilot

# 6. 只有配置与输入已提交、推送且工作树 clean 时，才运行正式 pilot preflight
.\scripts\check_research_g0_starter.ps1 `
  -Mode pilot -ConfigPath configs/experiments/<frozen-run>.json
```

正式 preflight 不得带 `-AllowDirty`；失败后不得改为 `development` 再把结果写成正式通过。若 Windows PowerShell 与 PowerShell 7 结果不同，两者都应记录，先修兼容性。

### 25.6 必须立即停止并升级给负责人的情况

- 无法确认真实课节、gold、prompt、候选池或音频的权威来源；
- 需要改冻结 schema、标签定义、P0/P1/P2 边界、主要指标或论文 claim；
- 配置或输入 hash 不一致、工作树 dirty、HEAD 与远端不一致、输出目录已存在；
- gold 出现在生成 prompt、检索、排序、binding、timing 或 planning 的任何输入/传递依赖中；
- 只能靠删除失败样本、复用旧输出、手改中间 JSON、覆盖 run 或挑最好随机结果才能继续；
- runtime trace 与最终视频不一致，或没有 final-video 证据却准备写可见性结论；
- 服务器需要直接改代码，或有人要求用旧服务器结果代表当前 commit；
- locked test 已经被运行过，或有人要求再次调参/再次运行；
- 任何密钥、私人 URL、版权不明资产或大体积生成产物准备进入 Git。

### 25.7 已遇到的困难及可复用解决方式

- **默认 Python 版本错误、依赖过旧：** 不修 shell 默认解释器，统一调用仓库 `.venv`；预检在找不到受支持 venv 时直接失败。
- **Playwright bundled Chromium 缺失：** 用项目实际支持的 Microsoft Edge 做一次 headless 启停探测，不以某个 bundled 文件是否存在代替运行验证。
- **A 归档有必要文件但不能整体合并：** 逐文件核对研究计划和 hash，只选择性引入缺失的 G0 冻结说明，A 归档保持只读。
- **冻结文档触发 whitespace 报警：** 不改字节；仅对该精确文件在 `.gitattributes` 关闭 whitespace 报警，其他文件仍执行完整 diff check。
- **本地文件引用可能绕过 manifest：** 验证器同时扫描 JSON、纯文本、file URI、Windows drive path、规范化等价路径和字段组合，并设统一候选预算；超限或解析不清一律 fail closed。
- **快照路径可能覆盖或被 junction 绕过：** 固定写入 `.local/research_preflight/`，逐层拒绝 reparse point，使用 UTC 时间戳、GUID 和 `CreateNew` 原子创建。
- **共享文档可能与 Git 分叉：** 每次同步先读取云端；有反馈则先归档到第 23 节，Git 提交后再全量镜像并核对关键标记。Git 始终是可审计事实源。

### 25.8 接手确认清单

```text
[ ] 我已确认 A/B 是两个研究轨道，不是两个维护者或长期分支
[ ] 我使用交接分支和仓库 .venv，未修改 A 归档或 master
[ ] 我能解释 Gate 1A 已通过、Gate 1B 尚未通过的区别
[ ] 我知道 30 条 gold 只能评测，且 28/1/1 不能支撑方法优越性
[ ] 我没有把 template、development preflight、mock test 或旧服务器结果当正式实验
[ ] 我会先冻结 lesson_002 输入与全部 manifest，再创建 RUNNABLE 配置
[ ] 我会先实现正式 run manifest，再进行真实正式运行
[ ] 我会在本地单课通过后才申请服务器单课 paired run
[ ] 我会保留失败、重试、访问日志和 final-video 人工检查证据
[ ] 我不会提交凭据、腾讯文档信息或大型生成产物
```

## 26. 2026-10-18 真实 lesson_002 Track A development smoke

### 26.1 已完成

- 负责人确认既有冻结 `lesson_002` 为本轮内部研究权威输入，并提供可用的 ECNU OpenAI-compatible 凭据；凭据只保存在用户级环境变量中，没有进入 Git、日志、run manifest 或共享文档。
- 新增严格 dataset manifest、candidate-universe manifest、候选 payload、真实源文件、基线 script/storyboard，以及由 storyboard `kp1–kp5` 明确归纳且标为 `BASELINE_DERIVED_PENDING_HUMAN_REVIEW` 的 lesson plan；所有传递文件均有仓库相对路径与 SHA-256。
- 新增 `config_status=RUNNABLE` 的 Track A development 配置，条件为 Never Retrieve、Always Retrieve、Keyword Heuristic、Pool Availability 与 proposed visual decision。该配置不是 pilot/validation/locked-test 配置。
- 新增正式 run-manifest 入口和运行时访问审计：要求 clean/pushed、snapshot/config/commit/upstream 一致、全部输入已跟踪，拒绝输出覆盖、未声明输入、hash 漂移和 generation 阶段读取 gold。
- 本地真实接口最小调用成功；clean preflight 在 commit `83086014b9212067e09c05a44949b48544a015db` 上通过，branch/upstream ahead/behind=`0/0`，LLM 与 rendering 均可用，研究子集 `31 passed`。
- r3 单课结构化 smoke 通过：31 个 knowledge propositions、25 个 narration propositions、25 个 visual decisions；决策动作计数为 `generate=12 / retrieve=6 / reuse=3 / none=4`，状态为 `DECIDED=24 / UNCERTAIN=1`。四个确定性 baseline 均生成独立输出。
- 访问日志共 9 条；gold 只有 1 条访问记录，阶段为 `evaluation`，没有出现在 generation 访问中。运行输出保存在被忽略的 `.local/research_runs/`，未提交 Git。
- 验证结果：run-manifest/config 定向测试 `29 passed`，全量 `445 passed, 4 skipped`，触碰 Python 文件 Ruff 通过。

### 26.2 保留的失败与修复

- r2 没有删除或覆盖，状态为 `FAILED_PRESERVED`。失败原因是模型选择复用教材图 `fig7-6`，但旧 storyboard 的 image 元素只有 `src`，缺少机器可校验的 `source_image_id`，校验器按设计拒绝继续。
- 修复只补充既有 image 元素到冻结候选 `fig7-6` 的显式 ID 映射，并同步更新 storyboard、dataset manifest 与配置 hash；没有放宽校验、修改模型输出、复用 r2 中间结果或引入 fallback。r3 从新提交重新执行。
- GitHub HTTPS 代理一度只能读不能写。等价提交通过 GitHub Git Data API 重建时，因 API 将时间统一为 UTC 导致 commit SHA 不同；在确认 tree SHA 完全相同后同步本地/远端引用，随后常规 push 恢复。该过程没有 force push，最终 upstream 一致。

### 26.3 不能据此声称的结果

- 现有 30 条工作 gold 中只有 7 条属于 `lesson_002`；当前图谱与这 7 条均没有通过严格的规范化精确文本匹配，`aligned=0 / scored=0 / coverage=0`。因此准确率、macro-F1 与方法差异均不可解释。
- 本轮只证明真实凭据、真实单课、冻结输入、访问审计、proposition graph、visual decision、四个 baseline 和 evaluation 隔离能够完整运行；不证明 proposed 优于 baseline，不完成正式双盲标注，也不通过 Gate 2–7。
- Gate 1B 仍不得写成“整体正式通过”：当前配置是 Track A `development`，尚无 Track B 所需 candidate subset、narration/audio manifests、binding/dynamic plan/timed storyboard/runtime trace/final-video evidence，也没有正式 pilot 配置。

### 26.4 下一步顺序

1. 先人工复核由旧 storyboard 归纳的 `kp1–kp5` lesson plan、31 个 knowledge propositions 和 25 个视觉决策；不得用 gold 反向改 generation prompt。
2. 独立设计并冻结 gold→当前 proposition graph 的人工 crosswalk 或重新标注协议；需要双人盲化、agreement/adjudication，不能为了提高本次 coverage 临时放宽文本匹配。
3. 只有 Track A 人审和 crosswalk 协议通过后，才补齐 Track B 的 candidate subset、narration、audio manifests 与集成配置。
4. 再运行一个新的本地 Integrated AB 单课，生成 binding、dynamic plan、timed storyboard、trace 和 final-video evidence；未完成前不上服务器、不跑批量、不写效果结论。

### 26.5 Track A 人工复核方法

复核对象位于 r3 不可变运行目录，按以下顺序读取，不要直接编辑 JSON：

1. `generation/source_evidence.json`：确认每个 `raw-unit-*` 与冻结教材原文一致，教材图 `fig7-6` 的文件、caption、availability 和 teaching-asset status 正确。
2. `generation/proposition_graph.json`：逐条检查 31 个 `knowledge_propositions` 是否原子、忠实且能由 `source_refs` 支撑；再检查 25 个 `narration_propositions` 是否为 storyboard narration 的精确连续片段，span、segment 和 knowledge-proposition link 是否正确。
3. `generation/visual_decisions.json`：对每条 narration proposition 检查 `action`、source sufficiency、retrieval suitability、rationale evidence 和 confidence。`reuse` 必须指向该段实际存在的 `fig7-6`；`retrieve` 必须有可执行 query/acceptance criteria；`generate` 必须确实无法由 source/retrieval 满足且 prompt 不引入教材外事实；装饰性需求应判为 `none`。
4. `baselines/*.json`：只检查四个 baseline 是否遵守固定规则和共享相同 proposition/candidate 输入，不用 proposed 的结果或 gold 反向修改 baseline。
5. `evaluation/gold_alignment.json`：当前 7 条均为 `no_exact_text_match`，只核对失败原因，不计算或解释准确率。需要另行冻结人工 crosswalk/重标协议，不能手改该文件制造匹配。
6. `access_log.jsonl` 与 `manifest.json`：确认 generation 无 gold，gold 只在 evaluation 出现一次；commit/config/input hash、状态和输出目录与 r3 一致。

人工复核建议另建只追加的 review 表，至少包含：`artifact`、`item_id`、`verdict=accept/revise/reject`、`issue_type`、`evidence`、`reviewer`、`reviewed_at`。发现任何 source 不忠实、命题边界错误、跨段错链、无依据 reuse、把装饰性图当教学图或教材外事实时，应标记 `reject` 并停止进入 Track B；不得直接修改 r3 产物。

## 27. 2026-10-19 Integrated AB 字幕与录屏交接

### 27.1 本轮形成的可复用规则

- 字幕显示层与研究 timing 层必须分离：SRT 可按实测句子区间确定性拆分，P0 semantic timing 仍使用未拆分原始 sentence cues。
- 冻结 UTF-8 文本允许 raw/LF/CRLF 三种等价 hash；二进制不允许规范化。gold 隔离也按规范化内容比较。
- 无 LLM 的冻结 development 运行可由 preflight 的 `llm_required=false` 放行；正式模式不得继承此豁免。
- 旧 storyboard 的本地教材图只能从 storyboard 同级 `images` 或同案例 `source/images` 解析；同名文件 hash 不同必须停止。
- legacy storyboard 未携带 v2 `element_id` 时，不得设置 `T2V_RESEARCH_GENERATION_V2=1`。
- Windows 录屏除了 Edge 和系统 ffmpeg，还必须验证 Playwright 管理的 ffmpeg；布局报告路径接近 260 字符时必须使用确定性短名。
- 任何代码、环境或配置修复都必须保留原失败并使用新 run ID；不得在 r3/r4/r5 上原地续跑后改写状态。

### 27.2 当前里程碑

- r3、r4、r5 均按 `FAILED_PRESERVED` 保留；详细原因见 `lesson_002_IntegratedAB字幕修复与复跑交接_20261019.md`。
- r6 配置已冻结并通过静态 schema/hash/gold 隔离校验，但尚未执行 preflight 或实验。
- 当前可接手分支为 `codex/ab-research-handoff-20261017`，r6 代码基准提交为 `744dc37982ce5baaaa8a8cbcf7f7e883dadcc79f`。
- 全量回归为 `463 passed, 2 skipped`；该结果只说明代码回归通过，不代表 Gate 1B 或研究效果通过。

### 27.3 尚未解除的边界

- 没有成功的 r6 baseline/P0 paired run、最终 SRT/quality report 或人工 final-video review，Gate 1B 仍未通过。
- 冻结 candidate subset 尚未接入 `produce` CLI 的 P0 acquisition/retrieval；配置审计不等于方法链实际消费。
- 云端历史 r2 run bundle 在本机缺失，因此只能引用其摘要，不能把它作为本机复核证据。
- 未进行服务器、批量、pilot、validation、locked-test 或正式双人盲标；论文方法优越性 claim 仍被禁止。

## 28. 2026-10-20 视觉主链路优先与关系图开发交接

### 28.1 最新优先级与协作反馈

已核对共享文档末尾“最高优先级｜视觉主链路重建｜2026-10-20”以及负责人本轮“先改善图像效果、复用已有模板”的要求，采纳为当前工程顺序。旧交接中“立即冻结并跑 r8”的安排暂缓；不删除旧记录，也不改 RQ、gold、冻结契约或正式实验定义。

当前先完成五项工程工作：VisualSpec 的 create/revise/compose 工具化；替换默认 image.description → draw_svg 路径；自适应 SVG 布局；一页一主视觉的页面规划；截图语义/可读性检查与局部 spec 修订、新 revision 闭环。完成后才允许真实单课全链路 smoke，人工逐页通过后再讨论 baseline/P0 对比和服务器实验。工程开发中的自动修订不自动成为 P0 正式实验的处理因素，后续仍需按第 3 节冻结条件。

### 28.2 当前已完成的增量

- 六个现有课程页面已采样诊断；三张手工设计稿只用于效果定标，不冒充自动生成结果。
- 学校 ecnu-plus 已真实调用成功；密钥仅保存在本机环境，不进代码、Git、共享文档或运行包。本轮关系图为程序绘图，没有调用 ecnu-image 文生图。
- 新增三类可复用关系图组件和 `kind=relationship` 增量规格，接入现有资产编译器及 P0 自动规划入口，并传递实际主题。
- 实现原文引用验证、中文换行、内容预算、连线标签避让、原始响应与失败保留。原文片段存在不能证明模型释义或连线正确。
- `.local/relationship_api_preview/20261020-r5/` 的三张真实模型预览已渲染；模板类型事前指定，并非自动选型通过验收；人工审阅待完成。
- 2026-10-21 提交前独立复核发现并修复长数值/宽字符溢出、生成指令冒充原文证据两项问题；新增浏览器及伪证据反例。最终全量回归 `529 passed`。本轮状态是组件工程及真实小规模开发预览，不是 Gate 1B 或研究效果通过。

### 28.3 未完成与接手要求

- 非 P0 默认整课仍使用旧视觉路径，未完成默认接入、整页规划和截图语义修订闭环；尚无当前新组件的整课 MP4 验收。
- r7 时长修复保留，但未启动 r8；不允许用视觉预览替代 paired run、final-video evidence 或人工盲标。
- 接手人先读 [当前研究交接卡](当前研究交接卡.md) 最新部分、[关系图实现与复现说明](关系图模板化与学校API实跑_20261020.md) 和 [视觉现状诊断](视觉效果现状诊断_20261020.md)，先验收三张真实自动输出，再按 28.1 补齐主链路。
- 本地失败/预览目录不进 Git；跨机器接手须另行提供无密钥输入包、原始模型响应、manifest 与截图，学校令牌由接手人自行配置。
- 共享文档后续状态同步只读取末尾最新交接段及必要锚点，追加后回读新增段；除非做全面审查，不重复读取整篇历史。
