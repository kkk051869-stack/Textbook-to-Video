# AB 研究交接说明

> 交接日期：2026-10-17
> 交接分支：`codex/ab-research-handoff-20261017`
> 起始基线：`3b550112e8cf3ffa1cb3b384388261e63c724392`
> 当前阶段：Gate 1A = `TESTED_MOCK`；Gate 1B = 尚未正式通过
> 权威规程：[A/B 统一研究执行规程与未来路线图](AB统一研究执行规程.md)

## 1. 一句话状态

AB 代码、契约、开发预检、回归测试和已推送远端基线已经收口；下一步仍是在本地准备真实 `lesson_002`、严格 manifests、LLM 凭据和正式 run-manifest 入口，完成真实单课结构化 smoke 后才能安排服务器单课 paired run。当前不具备直接启动正式服务器实验的条件。

## 2. 从哪里接手

- 统一工作树：`D:\text python\Textbook-to-Video-master\Textbook-to-Video-worktrees\organize-local-workspace`
- 交接分支：`codex/ab-research-handoff-20261017`
- 已完成的 AB 基线：`origin/codex/organize-local-workspace` @ `3b550112`
- A 单线归档：只读来源，禁止覆盖或继续并行开发
- `master`：未合入本轮研究改动，未经批准不要推送
- 共享文档：腾讯文档“Text2vedio同步文档”是协作镜像；URL、文档 ID 和 token 不写 Git

先执行：

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse '@{u}'
.\.venv\Scripts\python.exe --version
.\scripts\check_research_g0_starter.ps1 -Mode development -RequireRendering
```

预期：工作树 clean、HEAD 与 upstream 一致、Python 来自仓库 `.venv`。若不一致，先查明原因，不能直接运行实验。

## 3. 已完成

- Track A 和 Track B 已统一到同一代码事实源；A/B 不再代表两名成员或两条长期分支。
- A 的必要研究内容已选择性合入；A 归档未被改写。
- G0 冻结说明已补齐并按原字节保存；SHA-256 为 `bc7f3ca3b0e35b7489ac21713f38852323426074d5ab3d7e6be967bf35641ce1`。
- proposition/storyboard ID 映射及缺失、重复、未解析边界改为 fail closed。
- experiment config、dataset manifest、frozen-file manifest 的 schema、语义/hash/隔离验证器已建立。
- development/formal preflight 已建立，固定使用仓库 venv，并记录 Git、依赖、工具和冻结输入快照。
- 本地环境已验证为 Python 3.12.14、`jsonschema` 4.26.0；Edge、ffmpeg/ffprobe 可用。
- 收口证据：全量 `445 passed`，研究定向 `31 passed`，最终独立复审范围内 `P0=0 / P1=0 / P2=0`。
- 工程提交 `92090726f207eae18be251835a1a2418f4342925` 和规程收口提交 `3b550112e8cf3ffa1cb3b384388261e63c724392` 已推送到原 AB 分支。

## 4. 未完成

- 没有真实 LLM 凭据或仓库根 `.env`。
- 没有真实 `lesson_002` 数据及严格 dataset/frozen manifests。
- 没有 `config_status=RUNNABLE` 的正式配置；现有 JSON 是不可运行模板。
- 没有根据验证后的 config + preflight snapshot 生成正式 run manifest 的执行入口。
- 没有当前 commit 的真实单课结构化 smoke、paired baseline/P0 成片或 final-video 人工检查。
- 30 条 gold 严重不平衡（28/1/1）且不是两个独立盲化标注者的正式数据，不能用于最终方法选择和论文效果 claim。
- Gate 2–7 未通过，旧服务器结果不能代表当前 merged commit。

## 5. 必须按顺序做的下一步

1. 阅读 `AB统一研究执行规程.md` 第 25 节及研究主文档、G0 冻结说明、实验配置 README。
2. 在本机受保护位置配置 LLM 凭据，只验证存在和调用，不打印或提交。
3. 由负责人确认真实 `lesson_002` 权威来源、许可和用途；无法确认就停止。
4. 建立严格 dataset manifest 和 source/prompt/candidate/script/audio 等 frozen manifests，逐文件记录路径与 SHA-256；gold 只能进入 evaluation。
5. 实现正式 run-manifest 入口和实际文件访问审计；禁止覆盖旧 run。
6. 从模板创建版本化、无占位符、唯一输出目录的 RUNNABLE pilot 配置。
7. 提交并推送全部配置/输入后，在 clean 且与 upstream 一致的 commit 上运行正式 preflight。
8. 本地只跑一个真实结构化 smoke，核对 schema、ID、gold 隔离、method report 和访问日志。
9. 本地通过后，服务器只跑同 commit、同输入的单课 baseline/P0 配对；不要直接跑 8/30 份批量。
10. 人工检查最终视频后，才判断 Gate 2/3；正式方法实验前再完成双盲标注、agreement/adjudication 和 split 冻结。

## 6. 关键命令

```powershell
# 使用项目解释器，不要使用 shell 默认 python
.\.venv\Scripts\python.exe -m pytest tests/test_ab_experiment_config.py tests/test_research_generation_v2.py -q
.\.venv\Scripts\python.exe -m pytest -q

# 开发检查
.\scripts\check_research_g0_starter.ps1 -Mode development -AllowDirty -RequireRendering

# RUNNABLE 配置建好、提交并推送后才执行
.\.venv\Scripts\python.exe -m textbook2video.research.experiment_config `
  configs/experiments/<frozen-run>.json --repo-root . --expected-mode pilot
.\scripts\check_research_g0_starter.ps1 `
  -Mode pilot -ConfigPath configs/experiments/<frozen-run>.json
```

正式模式不能带 `-AllowDirty`，也不能把 development 的 PASS 改写成 Gate 1B 正式通过。

## 7. 绝对不要做

- 不覆盖 A 归档，不在 A/AB/服务器三处同时手改代码。
- 不直接改 `master`，不在服务器形成未回传代码。
- 不把 gold 放入生成、检索、排序、binding、timing 或 planning。
- 不把 runtime trace 当 final-video evidence。
- 不在 locked test 调参或重复运行。
- 不隐藏失败、删除失败样本、复用旧输出、覆盖 run 或只挑最好随机结果。
- 不把 template、mock tests、旧视频或旧服务器结果写成当前正式实验。
- 不提交 `.env`、密钥、腾讯文档信息、私人路径、版权不明资产或大型视频/音频。

## 8. 文件导航

- 总规程与完整交接清单：`docs/研究/AB统一研究执行规程.md`
- 两份研究主文档：`docs/研究/教学原则驱动的教材教学视频生成_研究计划.md`、`docs/研究/教学原则驱动的教材教学视频生成_研究思路报告.md`
- G0 契约：`docs/研究/G0_研究数据契约冻结说明.md`
- Gold 边界：`datasets/research_generation_v2/reference/a_visual_support_gold_v0.1/README.md`
- 配置说明：`configs/experiments/README.md`
- 配置模板：`configs/experiments/ab_single_lesson_pilot.template.json`
- 三个严格 schema：`contracts/ab_experiment_config_v1.schema.json`、`contracts/ab_dataset_manifest_v1.schema.json`、`contracts/ab_frozen_file_manifest_v1.schema.json`
- 语义验证器：`src/textbook2video/research/experiment_config.py`
- 预检：`scripts/check_research_g0_starter.ps1`
- 配置回归测试：`tests/test_ab_experiment_config.py`

## 9. 接手完成标准

接手人能够复述当前 Gate 状态，确认工作树与 upstream 一致，使用仓库 `.venv` 通过 development preflight，并承诺按“真实输入冻结 → run manifest → RUNNABLE 配置 → formal preflight → 本地真实单课 → 服务器单课”的顺序推进，才算完成交接；仅能运行单元测试不等于完成接手。
