# 回到Doc2Present：DVC单页受控生成

## 范围纠正

用户已指定PresentAgent官方Doc2Present。此前两轮使用旧区块链来源，不计入新数据集进展；旧报告和失败证据保留，但停止将旧003/004作为下一步任务。本轮恢复正确数据范围，不重跑RQ1/RQ2比较或整课。

基准c5a4b551517a2251b47e745f148654b89ce23610，分支codex/visual-acquisition-handoff-20261030，无生产代码修改。Doc2Present固定版本5656f79a4101aa81cb249bbf630dd4e73971a60e，DVC An End-to-end Deep Video Compression Framework.pdf SHA256=dbbb939fe2a167419b60aa8dc4326c8439b531684ecd6b7e91d150e807d4ba3e，与已跟踪inventory一致。

完整旧分镜/决策包缺失，因此本轮明确新建开发副本，不伪称恢复原普通produce预测。输入为PDF第3页§3.1，派生页含标题和Step6原文正文，旁白使用同一原文。NFKC、断行连词及空白归一记录在task-contract，保留整页原始抽文与PDF渲染证据，主执行实际查看原页。教学目标来自已下载case-01旧生成请求，经hash记录。参考MP4及原论文图未进入生成，无新图许可升级或Gold输入。

## 一次真实执行

原页容量通过1600×900和1366×768。使用现有run_visual_agent→整页预检→strict审核→compose_local_visual路线，预算规划1、审核最多1、max_iterations=1；健康/重试/图片API为0。实际只调用规划1次：输入5734、输出640、总6374 tokens，15.969秒；缓存和费用未知。没有为了用完预算补发审核。

模型返回合法单资产结构，数据节点角色已正确标data，下一帧运动估计为process。但两个input边pred-frame→recon-frame与rec-resid→recon-frame均是data→data，现有规则要求输入目标为process，语义门禁汇总2条relation_role_pair并停止。具体路径/源节点/目标及原回复均保存。

根因是模型省略了源文明确的“相加”操作节点，将输入数据直接接到结果数据。不同于旧记录把帧标entity，也不是API500、容量失败或截图审核拒绝。不得将结果帧重标为process来凑过校验。

运行状态STOPPED_GENERATION_OR_REVIEW，agent为STOPPED_ITERATION_BUDGET。没有编译SVG、生成图截图审核、页面合成、TTS或录制；original-page截图仅是原文本页容量证据。人工NOT_REVIEWED。

证据根目录`.local/visual-loop/20261108-doc2present-dvc-page-01/`：task-contract.json、runner_snapshot.py、source-page-3.txt/png、source.txt、input-storyboard.json、calls.json、state.json；原回复agent/model-response-0.txt；2条错误agent/revision-00/failure.json及draft-graph.json。原件PDF hash前后不变。运行资产不上传Git。

development/rendering预检33 passed；独立只读复核确认来源、派生范围、预算及门禁。无源码变更，不重复全量测试。本轮到此停止，不在该目录追加模型修订。

## 下一步最小行动

使用现有结构修订路径，在新任务/目录补充“相加”process节点，保持预测帧/重建残差/结果帧data角色、原引用、相加关系及下一帧反馈；不改角色表或增加协议。修订后才走编译、整页容量、严格审核和合成。成功后接真实音轨及出现窗口；失败保留实际阻塞，不转回区块链或通过改输入主题规避。
