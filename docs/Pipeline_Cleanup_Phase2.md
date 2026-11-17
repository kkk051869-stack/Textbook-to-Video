# Pipeline cleanup — phase 2

分支：`refactor/pipeline-cleanup`。本阶段基准：第一阶段提交
`0390d7e31f8dde16c064927349057d4d2fb29fd6`。
Snapshot 保持在 `46b50b7bbec13df9c4e6ed5583168741025adc1a`。

## 职责与接口

- `research/p0_preparation.py`：提供 `prepare_p0_research` 和
  `schedule_p0_research`，分别负责 TTS 前的研究输入准备和 TTS 后的实测调度。
  `P0Preparation` 仅保存跨 TTS 边界所需的路径，不依赖生产 `Artifacts`。
  准备过程继续调用已有 `p0_integration`，保留候选复制、校验及 sidecar 写入顺序。
- `research/visual_decision.py`：新增 `upgrade_visual_decision_file`，承接旧决策
  升级、来源证据校验和原位落盘；原有决策函数不变。
- `research/p0_method_runner.py`：新增 `prepare_p0_phase2_plan`，承接执行候选池
  构建、方法比较、事件计划编译及顶层计划别名写入。继续复用现有算法。
- `pipeline/orchestrator.py`：调用上述准备边界，继续选择输入与恢复入口、延期
  P0 TTS、切换候选产物路径、执行生产 TTS，然后继续 HTML、录制、合成和证据收尾。

研究准备模块不会合成音频或视频，也不导入 orchestrator。静态导入关系检查未发现
从准备模块返回 orchestrator 的路径。新增依赖为 orchestrator → p0_preparation，
以及准备模块 → 现有 integration、decision、acquisition 和 method runner。

v2 双写跨越内容生成、配音及成片证据，本阶段保留原位，避免扩大兼容范围。

## 保持的行为

- 普通 produce 不执行 P0 准备；P0 默认 phase2、legacy 和外部计划选择规则不变。
- 来源证据、图谱、决策、获取、候选准备、TTS、候选池、方法比较、计划编译、
  调度的先后顺序不变。外部计划不触发 phase2 编译。
- phase2 的 `require_coverage=False`、`require_pool_coverage=False` 和
  `allow_decision_bridge=True` 不变，不改变独立比较入口的默认值。
- CLI、Prompt、模型参数、文件名、JSON、候选修改、sidecar 重写、异常消息及
  已发生的文件副作用保持一致。缺少实测 cues 仍报错，不增加估算回退。
- 音频复用和冻结音频参数继续由 produce 传给原 run_tts；恢复仍调用原恢复函数。

## 离线验证

迁移前扩充 P0 固定输入测试，最初覆盖 phase2、legacy、外部计划、恢复、cues
缺失/损坏和审核文件缺失；连同第一阶段兼容测试共 29 项通过。
后续补充冻结图谱/决策输入、图谱缺失、决策缺失和非法计划，并检查候选池、
方法比较与编译必须发生在 TTS 后。

使用 Git 对象加载第一阶段原始 orchestrator，在相同临时目录分别执行原实现与
重构实现。11 组成功/失败场景全部通过，逐字节比较产物、文件清单和控制台输出，
同时断言调用顺序、异常边界、基础 Storyboard 保留及音频参数透传一致。
每次运行之间仅清理该验证程序自己创建的临时产物。

相关测试共 83 项通过：

```text
tests/test_orchestrator.py
tests/test_generation_compatibility.py
tests/test_narrate.py
tests/test_p0_integration.py
tests/test_p0_research_chain.py
tests/test_p0_methods.py
```

AST 对照确认 visual_decision 原有 7 个函数、p0_method_runner 原有 5 个函数完全
不变。新准备模块及已有模块新增函数通过 Ruff；Git whitespace 检查通过。

模型生成、TTS、获取和视频重步骤使用替身；实际候选复制、来源证据、旧决策升级、
计划比较/编译和事件调度在固定输入下执行。未调用真实模型、TTS、图像生成或完整
出片服务。未验证真实服务的随机失败与重试、所有素材获取组合、完整 VLM 审核成功
链路或最终视听质量；冻结音频主要验证参数透传，不宣称完成真实音频恢复验收。

## 原有行为观察，未修复

旧视觉决策升级会原位重写调用者提供的决策文件，包括被当作冻结输入的文件。
本阶段保留此副作用；若以后需要不可变输入，应作为独立行为变更评审。

本阶段不合并分支、不删除历史能力、不继续第三阶段。
