# 普通 produce 的 Proposed 接入范围修复与实片验证（2026-11-13）

当前分支 codex/visual-acquisition-handoff-20261030，基线 8b94757。代码工作树包含此前最小接线修改，本轮未提交或推送。

## 修复

原适配器以 visual_acquisition_action=generate 筛选 SVG，使 RQ1 none、reuse、retrieve 页面无法使用 Proposed。现按实际视觉候选接入：图片整体、带稳定对象 ID 的 SVG、流程/表格/对比等原生组件。资产文件/hash不符仍拒绝；原生组件通过现有 Renderer 截图成为模型的真实视觉输入。优先沿用 proposition_ids，否则只考虑同页有 source_refs 的命题，实际选择仍由 Proposed 作出。缺少视觉、来源支持或引用关联均记录原因。

普通 --rq2-audit 不再必须搭配 RQ1 自动增强/选择文件。没有既存命题图时复用现有 source_evidence 和 proposition_graph 构建入口；已有图直接复用。未改变 RQ1、Proposed、语义检查的核心算法或 Prompt。

发现并修复旧词面时序把绑定对象显示得过晚的问题：当绑定命题的讲解窗口早于原显示事件，单独提前其 show，保留其他目标，再交给原动态规划器决定 focus。首次录制及失败窗口保留于 media/，修复后用同一预测、同一实测音轨在 media-fixed/ 重录，零新增模型请求。

## 真实输入与结果

使用 Flows 论文第3页此前由普通 produce 模型生成的9页分镜中的第4页（原ID=4，S2S架构核心操作）。S2S是论文架构名称，并非手工光流S2页面。仅抽取该自动页面，元素、旁白、原RQ1决策均未改写；本轮从保存分镜恢复，不声称重新从PDF生成了整套计划。原RQ1为none，仍保留原始决策。

5条命题：nprop-012 BOUND/e3、nprop-013 BOUND/e3；nprop-014 拒绑（关系不足）；nprop-015 SEMANTIC_CHECK_FAILED；nprop-016 拒绑。两条被接纳的独立模型核查为SUFFICIENT，均非Gold。nprop-013对2x2到4通道细节的充分性仍值得质疑：流程组件只给出空间换通道概括，不能据此宣称完整解释张量变化。

最终规划对nprop-012产生focus，nprop-013被现有signal_density_budget限制不重复强调。命题“包含三个核心操作：SQUEEZE、Step of Flow和SPLIT” → Proposed选择e3 → 原生流程组件 → focus计划0.55秒、保持2秒 → runtime及MP4帧。详见 evidence-chain.json。此处关注整个三操作关系与总述旁白一致；没有实现逐个子步骤的独立寻址。

## 验证

最终视频：D:\Code\vibe coding\Textbook-to-Video-worktrees\visual-acquisition-handoff-20261030\.local\data\runs\proposed-native-produce-20261113-01\media-fixed\flows-operations.mp4

48.533333秒，H264/AAC/字幕流，全片解码退出0，CALIBRATED。1920×1080、1366×768布局检查通过，质量报告ok=true，仍保留初始可见元素少和页面重心偏移警告。实际查看0.2、1.3、3.3、10、47秒视频帧：1.3秒橙色边框可见，3.3秒已恢复，无明显遮挡或裁切。没有连续完整听看，不能声称人工音画验收通过。

模型调用：8次绑定、6次独立语义检查，合计14次（含现有有界修正），无新Visual Decision、图片生成。Token/费用未由当前调用接口持久化，未知；不估算。单页SAPI实测音轨48.44秒，重录复用同一音轨。

定向测试8项通过；development/rendering预检33项通过；course_binding及定向测试ruff通过，git diff --check通过。首个新增时序回归曾因全局semantic timing也会调整无关目标而失败，改为直接验证本轮依赖适配函数，未改生产算法迎合断言。

## 边界

真实出片验证覆盖RQ1 none页面的原生组件。reuse/retrieve/generate候选已解除获取动作限制，有离线范围回归，尚无三条各自的本轮真实模型成片证据。位图仅能聚焦整图；没有区域数据不能自动获得图内节点。现有适配器逐元素评估，尚非跨独立组件的全页联合选择。没有重新开展论文方法比较，不据此声明教学优势或泛化通过。

所有运行证据：D:\Code\vibe coding\Textbook-to-Video-worktrees\visual-acquisition-handoff-20261030\.local\data\runs\proposed-native-produce-20261113-01

最终交付目录为media-delivery。另修复重算保留旧course_binding_dynamic_plan事件的问题，仅移除本适配器旧事件，保留原事件；回归覆盖旧事件清理、分组show拆分与其他目标保全。media-fixed/与media-final/保留中间现场，交付版Trace只有当前计划的nprop-012 focus。交付版最终帧另存delivery-frames/，完整解码退出0。
