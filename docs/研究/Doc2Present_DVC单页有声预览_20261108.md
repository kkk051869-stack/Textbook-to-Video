# Doc2Present DVC：修订、入页和短有声预览

基准1b1a4e1656e4616dd8512a02c4f021f947978f41，分支codex/visual-acquisition-handoff-20261030。本轮无生产代码修改，冻结PDF/旁白/旧运行均未覆盖。输入承接[上一轮DVC派生单页](Doc2Present单页生成恢复_20261108.md)，不是旧普通produce分镜/决策恢复，也不是新人工Gold。

## 修订和页面

保留原失败，通过既有resume_from/DraftGraph的draft_updates恢复。程序授权两条错误边的连通子图更新，可增添来源约束内的中间节点；并非全图重写。

repair-01实际模型回复补出了Add，但节点source_refs包含未获授权的source-032，且两个更新重复定义同一Add和结果边；程序先因来源越界拒绝，未编译/审核。旧失败原样保留。

repair-02使用相同sealed parent、source、goal和契约，在既有feedback.validation_error中追加上述明确错误及“共享Add定义一次、后续只引用、来源仅source-031”的执行者修订要求。原请求和实际转发请求分别保留。这是执行者补充反馈后的真实模型修订，不是默认入口已经能自动汇总这些约束；没有手改模型响应或扩大来源权限。模型一次只新增add-process，另一个更新nodes=[]引用共享节点，结果边不重复，原data节点和下一帧motion-estimation输入边保留。

真实编译、整页预检、严格截图模型审核ACCEPT/issues=[]及compose_local_visual落盘重载完成。原标题/原文正文、旁白、animations和旧timeline保全。有限布局前两次容量未过，第三个既有full_stack+compact-spacing通过，未缩字或拆页。新增SVG小视口最小实测16.69px；最终1600×900和1366×768均通过并实际查看。

## 有声预览实测

合格页面之后，本机Windows SAPI/Microsoft Zira Desktop配音1批、Chrome录制1次，无模型调用或媒体重试。派生视频页保留原组件/旁白/animations和旧timeline，单独追加新图show事件0秒，配音前留0.8秒；整图伴随整段旁白，是工程可见性预览，不是逐命题动态对齐。

原始WAV声音长20.481587秒，计划声音窗口[0.8,21.281587]秒。实际MP4容器21.641秒，视频H.264/21.633333秒，音频AAC/21.594014秒。完整解码0错误，时钟CALIBRATED，3事件全部executed，新图runtime触发0.034秒。音频mean -20.7dB、peak -2.9dB。实际查看0.85、10.84、21.28秒最终帧，新图可见；另保存0.5和2秒帧。以上不证明连续视频每帧可见或声音准确。

最终文件：`.local/visual-loop/20261108-doc2present-dvc-video-01/voiced.mp4`，SHA256=b264a5ca4cb369505f1cc14a864b3afd5ff3ee6dda949a80f024753e9c187884。证据包括audio-timing.json、ffprobe.json、volume.txt、silent.clock.json、runtime-trace.json、frames/、closure.json及output-manifest.json。本地运行资产不进Git。

## 调用、验证与边界

| 调用 | tokens | 秒 |
|---|---:|---:|
|此前原规划|6374|15.969|
|本轮repair-01|7154|13.750|
|本轮repair-02|7200|5.172|
|本轮截图审核|11541|22.312|

本轮3请求共25895tokens/41.234秒；本DVC案例累计3次规划（含修订）+1次审核，共32269tokens/57.203秒。repair-02缓存64、审核缓存0，另两次缓存未知；费用未知，不估算。健康/图片API0。模型请求没有传输重试；两次修订各为保留证据的新任务目录，不能称首次生成成功。

development/rendering预检33通过；独立只读核对修订的来源、范围、实际请求反馈差异和模型/页面状态。无生产源码变更，未重复全量测试。视频独立核对媒体和trace，不等于独立人工语义/发音判断。

结论：在明确执行者错误反馈下，Doc2Present新派生DVC单页已完成模型修订→严格模型审核→真实页面→有声视频的工程预览。人工教学语义、公式发音及连续音画均NOT_REVIEWED；公式仍使用PDF抽出的重音符号样式，不宣称标准数学排版质量通过。不是默认普通入口全自动恢复、整课、RQ2方法验证或P0效果结果。

下一步停止打磨本例，回到Doc2Present的普通入口端到端任务：明确冻结输入和模型/媒体预算，保留教材计划、讲稿、分镜与自动决策，检验新视觉进入页面和视频是否能在完整入口复现。尚未证明自动化的人工补充错误反馈须记录，不能将本单页成功当整条入口已通过。
