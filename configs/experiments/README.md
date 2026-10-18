# A/B 实验配置

`ab_single_lesson_pilot.template.json` 是机器可校验但不可直接运行的模板。复制为新的版本化配置后，必须：

1. 替换全部 `REPLACE_*`；
2. 将 `config_status` 改为 `RUNNABLE`；
3. 指定冻结 dataset manifest 和全新输出目录；正式 preflight 自动把当前已推送 commit 写入环境快照，避免配置文件产生自引用 commit；
4. 每个直接输入写成 `{path, sha256}`，明确 prompt、候选宇宙/子集、讲稿和音频 manifest；dataset manifest 必须符合 `contracts/ab_dataset_manifest_v1.schema.json`，其余四类 manifest 必须符合 `contracts/ab_frozen_file_manifest_v1.schema.json`，所有传递文件也必须逐项给出 `path` 与 `sha256`；
5. 通过 schema 及 `textbook2video.research.experiment_config` 的语义/hash/隔离校验；
6. 使用 `textbook2video.research.run_manifest prepare` 根据已验证配置和环境快照创建不可覆盖的 run manifest；它要求配置、输入、commit 已跟踪且工作树与 upstream 完全一致；
7. 执行器必须通过 `record_input_access` 记录实际读取，generation 阶段读取 gold、读取未声明文件或 hash 漂移都会立即失败并保留运行目录。

正式预检示例：

```powershell
.\scripts\check_research_g0_starter.ps1 -Mode pilot -ConfigPath configs/experiments/<frozen-run>.json

.\.venv\Scripts\python.exe -m textbook2video.research.run_manifest prepare `
  configs/experiments/<frozen-run>.json `
  .local/research_preflight/<matching-snapshot>.json --repo-root .
```

验证器会拒绝任意字段中的占位符、manifest 未声明字段、传递文件缺少 hash、hash 不匹配、gold 与 generation 输入同路径/同内容或通过等价路径间接引用、重复 condition ID、已存在的输出目录及 mode/split 不一致。A/B 条件必须共享 source、讲稿、音频、主题和时长预算；RQ1 共享候选宇宙，RQ2 共享冻结候选子集。

`locked-test` 不能只写一个布尔值；必须提供单次授权记录及其证据文件 hash。配置隔离只约束由该配置声明并经预检的输入，不能替代运行时审计；正式执行仍必须从该配置生成 run manifest，并在运行后核对实际访问日志。
