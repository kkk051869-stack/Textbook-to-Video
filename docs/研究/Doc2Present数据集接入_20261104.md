# Doc2Present 数据集接入决定（2026-11-04）

用户指定采用 PresentAgent 论文公开的 Doc2Present，作为后续开发性方法比较和端到端实验的共同文档来源；不改写已有冻结教材、gold、baseline或locked test。它是混合文档基准，报告中不将全部来源称为教材章节。

官方入口：https://huggingface.co/datasets/AIGeeksGroup/Doc2Present
代码与论文对应：https://github.com/AIGeeksGroup/PresentAgent
固定数据版本：5656f79a4101aa81cb249bbf630dd4e73971a60e。

官方发布30份PDF与30份MP4，README声明数据集MIT。当前公开文件清单没有独立的完整测验题库、命题级视觉必要性标签或动态事件真值；不虚构这些标注。数据集级许可元数据与嵌入第三方素材的逐项来源权限分开记录，不改strict acquisition许可规则。

使用安排：

- PDF作为方法生成输入，提取文字、来源页和原图，方法条件共享同一来源和候选宇宙。
- 发布MP4仅作为参考/评价侧资产，不能进入方法生成、检索排序或动态规划。它们不自动成为逐命题事实真值或动态时序gold。
- FineGym、Just Ask已被上一轮RQ1使用，保留为已暴露开发样本。其余文件只是未被该轮使用，不能据此宣称从未暴露；核对历史访问后另行冻结文档级划分。
- 下一步在剩余文档中按预先固定规则选少量文档/连续片段，冻结双Judge正反序预算和验收规则，先完成一次受控RQ1验证；后续分别推进RQ2绑定/时序比较，不以Proposed获胜作为推进条件。

下载原件与哈希清单保存在仓库忽略目录 `.local/datasets/Doc2Present/5656f79-20261104/`，原件不入Git。此次仅数据接入与完整性核对，不调用模型、不运行整课，不将公开可下载等同真实实验完成。

完整性核对：61项文件全部下载成功，277,866,935字节，SHA256逐项回读一致；30份PDF打开通过，30个MP4的ffprobe通过，30对文件名规范化配对唯一。未做全视频解码、内容对齐或人工验收。轻量清单见 configs/research/doc2present_inventory_20261104.json。
