# 仓库收口记录

## 当前基线

- GitHub 稳定基线：`master`，提交 `d12a2d3`。
- 生产整理分支：`codex/production-stabilization`。
- PresentAgent 实验分支：`codex/experiment-presentagent-v1`。
- 审计快照时间：2026-08-07。

`master` 只接收经过测试、可复现的生产代码与文档。实验脚本、数据集评估材料和 PresentAgent 适配不直接混入 `master`。

## 已冻结的旧工作区

本地与云端旧工作区均存在未提交内容。为避免整理中丢失修改，已创建以下只读审计快照：

```text
本地：D:\Code\vibe coding\Textbook-to-Video-audits\20260807-stabilization\
云端：/ai/data/textbook-to-video/audits/20260807-stabilization/
```

快照包含 Git 状态、未暂存/暂存补丁、未跟踪文件清单、云端未跟踪源码归档和校验和。清理前必须先比对这些快照；不得对旧工作区执行 `git reset --hard`、覆盖式拉取或递归删除。

## 分类规则

| 类别 | 归属 | 处理方式 |
| --- | --- | --- |
| 可复现的出片代码、测试、运行手册 | `master` | 审查、测试后单独提交 |
| MegaTTS3/云端 TTS 适配 | 生产整理分支 | 从审计快照逐文件迁入、补测试后再合并 |
| PresentAgent、TextbookEval、评分与数据准备脚本 | `codex/experiment-presentagent-v1` | 独立提交与评审 |
| 视频、音频、HTML、模型、缓存、压缩输入 | `/ai/data/textbook-to-video` | 不提交 Git |
| `.rej`、临时补丁和来源不明文件 | 审计区 | 先人工判定，不能直接提交或删除 |

## 云端部署原则

云端旧路径 `/ai/data/repos/Textbook-to-Video` 目前是历史工作区，仅保留用于比对和迁移。新的干净部署目录应由本地 `master` 的不可变 Git bundle 创建，直到云端具备只读 GitHub 拉取凭据。

后续标准同步路径：

```text
本地干净 worktree -> GitHub master -> 云端干净部署 worktree
```

云端不能直接编辑 `master`。云端适配若需修改，先记录补丁并回收至本地生产整理分支；通过测试和审查后再推送。

## 待迁入的生产适配

云端旧工作区包含 MegaTTS3 后端、云端批处理 runner 和浏览器/TTS 适配，其中部分没有进入 `master`。这些文件已经在审计快照中保全，但在以下条件满足前不得合并：

1. 与当前 `master` 的 narrator、orchestrator、CLI 和测试逐项三方比对。
2. 为 MegaTTS3 后端增加无 GPU 的单元测试或 mock 覆盖。
3. 验证 TTS 文本规范化、timed storyboard、manifest 和 mux 链路。
4. 在 `/ai/data` 的固定浏览器运行时中完成 smoke MP4。

这避免把旧云端分支中的 UI 实验、PresentAgent 文件或过时依赖一起带回生产主线。
