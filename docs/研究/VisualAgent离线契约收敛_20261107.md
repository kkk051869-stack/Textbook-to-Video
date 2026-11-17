# Visual Agent 离线契约收敛（2026-11-07）

基线 `4c1993e`，分支 `codex/visual-acquisition-handoff-20261030`。仅工程诊断与修复；模型、VLM、图片生成、TTS、录制调用均为 **0**，新增模型 tokens/费用为 **0**。无冻结输入或研究契约变更。

## 共同根因与修复

反复失败不全是模型能力不足：普通局部增强把旧页面传给资产生成器，触发整页内容去向规划；同一页面又由局部合成器保全，职责重复。`content_map` 把标题算作可替换正文，而下游只接受正文分区；单一异常又遮住后面的组合参数错误。

| 阶段 | 职责及本轮处理 |
|---|---|
| Visual Decision → 资产请求 | 决策、来源和命题沿用现有实现。普通 generate 调用已有 `page_context=None` 资产路径；原页由局部合成器持有。未重新决策或修改冻结案例。 |
| VisualPlan | 模型保留教学语义、视觉形式、节点关系、来源选择。资产模式只提交视觉内容；固定协议版本由程序填入并记账。显式错误版本仍拒绝；旧整页解析接口仍要求版本。资产模式不再索要或接受 content_map/page_plan/composition。 |
| 页面计划 | 旧整页入口继续可用。标题/subheading 由程序保全，正文才参与保留/替换集合；历史标题条目显式记录为未应用。正文来源和覆盖要求不变。局部路径不进入“主图+最多两个短文本”约束。 |
| 编译与组合 | flat relationship 与 renderer 容器的结构检查口径一致。现有组合字段补入同一输出 Schema；缺 visual_ids、非法轴/类型/重复 ID 提前拒绝。组合校验移到资产编译前，非法参数作为可记录的 ValueError，不再编译后触发缺参数 TypeError。 |
| 诊断 | 复用现有结构、角色、来源、旁白、页面和语法校验，输出 stage/path/message；信封、独立角色问题与后续可检查问题一并保存到 model-diagnostics，并进入失败反馈。补丁必须依托真实父稿，不作为完整图误判。诊断不构成准入。 |
| 审核 → 局部合成 | 原语义审核、hash、来源、实际尺寸与双视口门禁不变。程序派生稳定插入 ID，保留原元素及事件；没有审核记录的资产仍拒绝生产合成。 |

文件：`pipeline/course_visuals.py`（资产路由）、`research/visual_model_interface.py`（共享契约及汇总诊断）、`research/visual_content_map.py`（标题/正文集合）、`research/visual_tools.py`（按职责裁剪 Prompt、提前组合校验、保存诊断）。对应三份测试文件增加回归。没有新增 Agent、平行 Schema 或语义修正规则；未探测服务端 JSON Schema 支持，仍使用已支持的 json_object 与本地严格校验。

## 历史响应重放

本机可定位的两个视觉运行根 `.local/data/runs/`、`.local/ordinary-course/` 共 6 份真实 Visual Agent 回复，全部检查。完整原路径、SHA256、诊断及执行结果：

`.local/data/runs/visual-agent-offline-audit-20261107/replay-final.json`

| 历史响应（SHA256 前缀） | 本轮到达的阶段及边界 |
|---|---|
| 版本错误 `fc0e0c017de7` | 原回复仍因 `plan_version="1"` 拒绝。未修改为合法版本；可检查的内部字段另做静态诊断。 |
| goal/steps `61379e4b1ad3` | 标题集合冲突消除后发现原 composition 缺 visual_ids；最终代码在信封阶段即拒绝。另作明确标记的“仅资产投影”，visuals 原样保留，编译及 1600×900/1366×768 预览成功；生产合成因未审核拒绝，显式工程模式实测合成又因裁切拒绝，原页不变。投影成功不等于原回复通过。 |
| FineGym `107360cac27b` | 逐条报出两条 produces 主客体角色冲突；原回复与资产投影都在语义结构校验停止。未修改关系。 |
| 历史哈希图第 0 次 `2832acb99f62` | produces 指向状态的角色冲突仍被拒绝。 |
| 历史哈希图第 1 次 `f84a07f7685d` | 信封通过；使用原不可变父 DraftGraph 实际应用 updates，仍因替换/重复现有节点拒绝。 |
| 历史哈希图第 2 次 `70fc77194f10` | 实际编译、双视口预览成功；历史审核为 REVISE，本轮未重做语义审核，未升级 ACCEPT。 |

最终代码再次编译资产投影，产物 hash 与已查看预览对应资产一致（`final-asset-compile/`）。旧运行目录和原回复 hash 不变。失败现场、未通过布局截图全部保留。

已实际查看跨帧页双视口静态截图：1600×900 底部步骤被裁，1366×768 更明显；图中存在英文单词生硬断行、原始公式文本未排版。独立图预览的几何检查无报错不能代替可读性/教学审核。没有修改图、删除步骤、缩小字体或放宽门禁让它通过。

## 离线贯通与验证

- 83 项契约、content_map、自动路由和模型接口定向测试通过；14 项既有工具、审核失败、组合/事件测试通过（52 deselected）；22 项局部合成定向测试通过（7 deselected）。另补组合字段类型门禁 1 项通过，并复跑既有组合测试通过；共 120 个不同用例，0 failed、0 skipped；未运行全量测试。
- 按仓库要求执行 `check_research_g0_starter.ps1 -Mode development -AllowDirty -RequireRendering`：通过，内置 33 项检查通过；未启用 RequireLLM，没有健康检查模型请求。
- `git diff --check` 通过。只检查四个变更生产模块的 Python 编译语法。
- 水循环为明确标注的工程夹具。真实编译 SVG、局部插入/替换、双视口浏览器、保存→重载→渲染均执行；原正文、图片、focus_box/callout、ID、来源与事件保全。独立浏览器 Trace 的 4 个原事件执行，包括 highlight 未退化成 show。图片 hash 漂移、非法替换事件、拥挤页面仍原子拒绝。
- 夹具双视口截图已实际查看：原图与标注在左、新 SVG 在右，正文保留，无可见裁切。这是工程执行证据，不是水循环教学语义通过。

可复现定向命令（仓库 `.venv/Scripts/python.exe`，`PYTHONPATH=src`）：

```text
-m pytest tests/test_visual_model_interface.py tests/test_visual_content_map.py tests/test_visual_plan_contract_consistency.py tests/test_auto_visual_enhancement.py -q
-m pytest tests/test_visual_tools.py -q -k "agent_uses_review_feedback or agent_review_outage or agent_detects_repeat or composition_requires or single_visual_cannot_trim or immutable_revision or page_plan"
-m pytest tests/test_local_visual_composition.py -q -k "test_A_ or test_B_ or test_C_ or test_D_ or test_E_ or test_F_ or retained_image_hash or unreviewed"
```

截图和运行证据均位于新目录 `visual-agent-offline-audit-20261107/`，其中 `fixture-tests/` 保存夹具页面、HTML、布局和运行事件；`case-01/engineering-composition/` 保存被拒页面。运行资产不提交 Git。

## 尚未解决与交接

确定性工程修复不能决定错误关系应该改成什么，也不能证明真实引用蕴含图中结论。跨帧图仍需要语义/可读性审核与合格空间方案；本轮不修样例。未重新调用真实 Visual Agent，因此不宣称新契约已证明真实生成成功率提高。

诊断聚合独立阶段错误；语义不合法的依赖阶段不会冒充已验证，部分现有单项校验仍在其首个错误处返回。未承诺穷尽任意非法 JSON 的所有潜在错误。有效旧整页入口、手工 dispatch 和审核门禁保留；普通资产增强不再让模型重规划旧页。

提交只包含上述四个生产模块、三份定向测试和本文。原工作树已有交接卡及其他未提交文件保留，不混入本次提交。
