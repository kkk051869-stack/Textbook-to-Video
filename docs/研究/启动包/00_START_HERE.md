# Textbook-to-Video 论文研究 G0 启动包

这个启动包用于两人并行开展第一阶段研究。仓库、冻结契约、mock、已有 Pilot 数据、研究文档和测试都已放在同一份项目快照中。

## 先做这四步

在 `repository/Textbook-to-Video/` 下打开 PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest tests/test_research_generation_contract.py tests/test_research_pilot.py -q
```

如果最后显示 `6 passed`，说明研究契约、mock 和已有 Pilot 导出链可以使用。

需要生成视频时再安装系统依赖：

```powershell
playwright install chromium
winget install Gyan.FFmpeg
t2v doctor
```

`ffmpeg` 安装后需要重新打开终端。只开发 schema、visual decision、binding、metrics 时无需先安装 ffmpeg。

## 从哪里开始

- 成员 A：阅读 `02_成员A_启动任务.md`；
- 成员 B：阅读 `03_成员B_启动任务.md`；
- 两个人共同遵守 `01_共同环境与工作规则.md`；
- 合并前按 `04_交付与合并清单.md` 检查。

冻结契约入口：

- `contracts/research_generation_v2.schema.json`；
- `docs/研究/G0_研究数据契约冻结说明.md`；
- `datasets/research_generation_v2/mock_v0.1/package_manifest.json`。

## 当前阶段不做什么

- 不立即批量调用 LLM；
- 不实现通用 RAG 平台；
- 不实现 AI 补图、自动 repair 或 layout loop；
- 不开始正式 20–30 proposition 双人标注；
- 不修改或覆盖 Pilot v1、mock v0.1 和已有正式结果。

当前目标是：先用 mock 各自跑通代码，再用 5–10 个 proposition 做非正式 sanity check，最后进行 3–5 文档 dry run。

