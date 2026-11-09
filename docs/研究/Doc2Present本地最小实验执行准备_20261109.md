# Doc2Present 本地最小实验：准备与执行（2026-11-09）

说明：本文件记录运行前准备状态；真实运行结果与下一位 AI 指引见《Doc2Present本地小规模运行结果与下一位AI交接_20261109.md》。下文“尚未启动”均指准备报告形成时的状态。仅限三份已曝光dev材料，不是正式测试或方法效果结论。

## 输入与使用范围

DVC、Factorized、Normalizing Flows，各2条RQ1视觉决策项目、2条RQ2绑定项目，共12项目。PDF、原文span、图与17个候选对象、hash和代码快照已经准备。复用已有来源选段和定位，避免重新生成整套教材；不按预测是否成功挑样。RQ1和RQ2使用各自冻结选段，是两个受控子实验，不声称同一段原文全自动串联。

根据负责人明确决定，这些论文及其图用于本地研究视频，保留来源、图号与hash，不再等待额外许可。原rights_status保留，不伪造开放许可、人工Gold或语义ACCEPT。新RQ1配置的local_research_use精确列出文档hash与本地用途；只有明确development scope、locked_test=false且全部hash匹配才允许该执行范围。既有其他配置及生产来源门禁默认继续严格。

有效包：`.local/doc2present-local-dev-20261109/ready-v2/rq1/`和`ready-v2/rq2/`。旧rq1/rq1-ready/rq2包只保留历史，补齐代码后不再用于执行。原输入PDF位于同根sources/，未覆盖旧运行。

配置：`configs/research/doc2present_local_dev_rq1_20261109.json`和`doc2present_local_dev_rq2_20261109.json`。

## 方法与评价

RQ1：既有never/always/keyword、Direct、Proposed、no-source及来源充分性/检索适用性/不确定性消融。RQ2：既有lexical、embedding、Direct、legacy source-conditioned、context source-conditioned及context no-source。不新增决策/绑定Schema，不改阈值。

使用ecnu-plus/ecnu-max两个模型别名的匿名、正反序代理评价，隐藏方法身份与rationale，保留不确定和顺序分歧；别名不能证明模型家族独立。无人工标注、人工Gold、Kappa前置要求，不报告人工准确率或学习效果。报告全分母、每类分布、拒绑、无效输出、裁判一致性及失败。单个方法无效只排除该方法，其余有效提议照常裁判；无效结果不折叠成普通拒绑。

不设金额或Token总预算。保留调用、usage、耗时、失败与可获得费用；未知费用不估算。60/43是既有runner按本批固定任务表的次数保护，无补发预留和自动重试，不是金额预算。任何更改任务表需新包，不能静默重发直到成功。

## 已补齐的执行链

1. 本地用途传入RQ1资产执行；许可未知不再自动阻断本批本地研究，来源/hash/语义校验保持。
2. 新媒体适配器读取完成比较的bindings/*.json及输出manifest，明确选择source_conditioned_context实际预测。缺失预测或未知目标拒绝；错误目标、无效输出和拒绑保留，不手填正确对象。该阶段禁止模型HTTP传输，不走会重算其他绑定的produce默认P0分支。
3. 调用既有SAPI句级TTS生成/复用一次音轨，并核对逐句文本、文档ID、音频hash及实测cue。再调用既有Dynamic Planner、P0事件调度、Timing、HTML生成、Recorder和MP4合成模块。不重做视频流水线。
4. 条件为legacy、semantic、simple_rule、proposition_aware、without_signaling。同文档的所有条件共用相同正文、对象像素、实际预测和WAV；without_signaling只去focus，保留show与cleanup。各条件区别写入现有事件计划。
5. 每文档只对相同静态内容做一次双视口布局选择，再逐条件真实编译。编译目标不得丢失；原文不截断、不缩字救布局。布局/编译失败保留并继续独立文档。
6. 录制时记录runtime/严格clock，调用原合成与字幕模块；生成完整解码结果、ffprobe和事件前/出现时/后的抽帧索引。抽帧一律NOT_REVIEWED，不用runtime冒充最终可见性。
7. evidence-index.json关联RQ1报告、绑定裁判、原预测、实测命题、计划、编译、runtime、clock、音频、MP4、解码和抽帧。未生成字段明确为空，不伪造结果。

呈现边界：本轮媒体显示实际预测选中的原图对象裁剪，与完整旁白正文混排；来源全图用于绑定上下文，不把这些裁剪宣称为完整关系图或整课。未选对象留在元数据，不用显示正确替代物挽救错误预测。页面截图中的原图边缘截断来自原候选裁剪，数学符号抽取/发音尚需真实结果核查。

## 本地执行命令

在当前任务工作树运行，默认Verify不调用模型。已有音轨Audio只校验复用，不重复配音。

```powershell
./scripts/run_doc2present_local_dev.ps1
# 后续启动整批最小实验；含真实模型调用，本轮未执行
./scripts/run_doc2present_local_dev.ps1 -Stage Run
```

Run先执行强制development/rendering预检，再比较方法与Judge、复用音轨、准备/渲染条件、逐文档逐条件录制一次并汇总。独立布局或录制失败记录后处理其他可执行条件；模型接口失败或共享音频失败停止相应阶段。不会重试修样例。

也可分阶段运行：Compare → Audio → MediaPrepare → Render → Record → Report。例如单条件：

```powershell
./scripts/run_doc2present_local_dev.ps1 -Stage Record -Document dvc -Condition proposition_aware
```

默认方法和条件不会由裁判结果事后改变。重复execute/prepare/record拒绝覆盖；只读Verify/Report和音轨hash复用检查允许重复。生产代码/输入与快照不一致则停止，需要另建包。

## 本轮实际验证

- 模型、VLM、图片API、健康请求：0；正式实验录制：0。
- 本机SAPI3批、共6句，每份只生成一次。DVC约15.29秒、Factorized约26.87秒、Flows约14.79秒，精确值及句界保存在media-v2/audio/*/sentence_cues.json。未宣称公式发音审核通过。
- 定向测试21 passed；新脚本/测试完整Ruff、修改旧脚本F821/F841和PowerShell语法检查通过。未运行全量测试。
- 工程夹具调用实际Dynamic Planner/P0调度/HTML编译：3文档×5条件=15 HTML，双视口布局通过；实际查看6张静态截图，正文和对象标签可读，未见页面裁切。这些预测明确是ENGINEERING_FIXTURE，不是模型输出，不能计为实验成功。
- 失败现场保留：首个夹具使用相对路径导致file URI失败；修正夹具路径后发现未启用渲染器既有preserve-components标记，已修正接线，最终通过。不针对教材增加规则或改变布局阈值。
- 预检曾因只设置T2V_FFMPEG而未设置预检读取的FFMPEG_PATH失败，已在统一入口衔接两种环境变量；失败日志保留，修正后development/rendering预检33 passed、exit 0，统一入口Verify exit 0。

工程证据：`.local/doc2present-local-dev-20261109/engineering-smoke-final/`（明确fixture）、共享音轨`media-v2/audio/`、准备与预检日志同根。实际实验媒体只写media-v2/，不得把工程夹具绑定复制进去。code基准5cf0cf2加本轮未提交diff/快照，本机无关修改保留。

目前没有等待外部教材、额外许可或旧音频的前置阻塞。真实模型结果、语义评价、时序MP4和实际帧观察属于下一次Run的产物，不能由本轮准备或静态截图代替。
