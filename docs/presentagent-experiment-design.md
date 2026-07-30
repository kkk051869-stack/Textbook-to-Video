# Textbook-to-Video 与 PresentAgent 对照实验执行方案

> 文档版本：v2.0，双人并行版
> 数据集：TextbookEval-v1
> 内部系统基线：`bf086e8f4424d7bfbb7c6f3ee33a225b66b23c72`
> 外部基线：PresentAgent 2025
> 当前范围：数据集、系统生成、自动评价、双人独立评分和视觉语言模型辅助评价

## 1. 目标与边界

本实验研究两个问题：

1. 教学计划（Lesson Plan）是否改善教材知识覆盖、教材忠实度和教学结构。
2. 旁白驱动的页内动画是否改善视觉元素与讲解内容的同步。

实验由三部分构成：

```text
TextbookEval-v1 数据集
  -> Textbook-to-Video 内部 2 × 2 实验
  -> 官方 PresentAgent 端到端外部对照
```

当前版本不安排学习者参与研究，也不作“提高真实学习效果”的结论。当前可以验证的是：

- 核心知识点是否被准确覆盖；
- 视频是否忠实教材；
- 教材图片是否被正确使用；
- 页面元素是否在合适时间出现；
- 教学结构是否完整；
- 系统是否稳定、可复现；
- 与 PresentAgent 相比，整体教材教学视频质量是否更好。

## 2. 对照对象

### 2.1 Textbook-to-Video

当前完整流程：

```text
教材
  -> 解析
  -> 教学计划（Lesson Plan）
  -> 讲稿（Script）
  -> 结构化分镜脚本（Storyboard）
  -> 文字转语音（TTS）并取得真实音频时长
  -> 写入元素出现时间
  -> 网页动画
  -> 浏览器录制
  -> 音画合成
  -> 质量报告
```

核心实验变量：

- 是否使用教学计划；
- 是否根据旁白控制页内元素的出现时间。

### 2.2 PresentAgent 2025

原始 PresentAgent 将长文档转换为带旁白的静态幻灯片视频。本文将它作为“文档转演示视频”任务的外部对照系统：

- [PresentAgent 论文](https://aclanthology.org/2025.emnlp-demos.58/)
- [PresentAgent 官方代码](https://github.com/AIGeeksGroup/PresentAgent)

PresentAgent-2 已扩展为“根据用户问题生成演示内容”，并支持 GIF、视频和交互，与当前固定教材输入的任务不完全相同，因此不作为主要对照系统：

- [PresentAgent-2](https://github.com/AIGeeksGroup/PresentAgent-2)

论文中必须明确写“原始 PresentAgent 2025”，不能笼统写整个 PresentAgent 系列。

## 3. 内部 `2 × 2` 实验

`2 × 2` 的意思不是运行两次，而是有两个实验开关：

1. 是否使用教学计划；
2. 是否让元素按旁白时间逐步出现。

每个开关各有“开、关”两种状态，组合后得到下面四个条件。

### 3.1 四个条件

| 条件 | 教学计划 | 页内呈现方式 | 中文含义 |
| --- | --- | --- | --- |
| `C00` | 关闭 | 静态展示 | 不先制定教学计划，页面元素一次全部显示 |
| `C01` | 关闭 | 定时逐步展示 | 不先制定教学计划，但元素按旁白时间出现 |
| `C10` | 开启 | 静态展示 | 先制定教学计划，页面元素一次全部显示 |
| `C11` | 开启 | 定时逐步展示 | 先制定教学计划，元素按旁白时间出现，即完整系统 |

### 3.2 条件配对

每个课节的每次重复运行只生成两个内容分支：

```text
P0：不使用教学计划
  -> 一份讲稿、分镜和音频
  -> C00 静态展示
  -> C01 定时逐步展示

P1：使用教学计划
  -> 一份讲稿、分镜和音频
  -> C10 静态展示
  -> C11 定时逐步展示
```

因此：

- `C00/C01` 必须共用讲稿、分镜内容、图片、旁白和音频；
- `C10/C11` 必须共用讲稿、分镜内容、图片、旁白和音频；
- 静态版和定时版只能改变元素出现方式；
- 不能分别调用完整流程重新生成四次，否则无法判断差异是否真由出现时机造成。

### 3.3 静态展示的定义

静态展示版本必须：

- 保留全部页面和元素；
- 保留旁白、字幕和页面时长；
- 保留教材图片；
- 页面进入时立即显示全部页内元素；
- 不执行逐元素 `trigger_at_sec`；
- 可以保留普通翻页过渡。

静态展示版本不能：

- 删除元素；
- 改写文字；
- 更换图片；
- 改变旁白；
- 缩短页面；
- 重新生成 storyboard。

### 3.4 共同控制项

四个条件统一：

- `ecnu-plus`；
- 模型参数；
- 主题；
- 文字转语音所用声音和语速；
- 目标页数；
- 目标时长；
- 字幕；
- 模板渲染器；
- 教材图片策略；
- 布局质量检查；
- 自动修复次数；
- 浏览器；
- `ffmpeg` 音视频工具；
- 输出分辨率和帧率。

主实验中额外的智能体审查功能全部关闭。若后续需要评价它，应另设补充实验，不能只在完整系统中开启，否则会多出一个无法控制的变量。

### 3.5 研究假设

- **H1**：教学计划提高核心知识点覆盖和教学结构评分。
- **H2**：定时逐步展示降低视觉元素出现时间误差和过早显示比例。
- **H3**：定时逐步展示对流程、对比和图示类内容的同步改善更明显。
- **H4**：完整系统在不增加严重事实错误和布局失败的情况下取得最高综合质量。
- **H5**：完整系统相较 PresentAgent 具有更高的教材忠实度和图片对应准确性。

## 4. 实验规模

### 4.1 试运行

```text
2 个课节
× 4 个实验条件
× 每个条件独立生成 2 次
= 16 个内部视频

另加：
2 个 PresentAgent 视频
```

试运行用于发现：

- 输入范围错误；
- 图片提取问题；
- 静态版与定时版的配对错误；
- 时长和页数失控；
- PresentAgent 中文兼容问题；
- 评分表不清楚；
- 成本或运行时间不可接受。

试运行结果不进入正式主统计。

### 4.2 正式实验

```text
8 个课节
× 4 个实验条件
× 每个条件独立生成 3 次
= 96 次内部完整运行

外部基线：
8 个课节 × PresentAgent = 8 次外部系统完整运行
```

这里的 96 来自 `8 × 4 × 3`：8 个课节、4 个实验条件、每个条件独立生成 3 次。全部 96 次内部运行都计算自动指标，用来同时考察平均质量和运行稳定性。

双人独立评分使用预先指定的标准结果：

```text
8 个课节 × 4 个内部条件 = 32 个视频
8 个 PresentAgent 输出 = 8 个视频
合计 40 个视频
```

标准结果默认使用第一次重复运行 `r01`。如果 `r01` 因技术问题失败，则使用按运行顺序得到的第一个成功结果，并保留全部失败尝试记录。这个规则必须在生成前确定，不能看完视频后挑质量最好的一个。

## 5. 双人并行分工

### 5.1 总体分工及逐项解释

| A 工作线：教材与本系统 | B 工作线：外部系统与评价 | 实际要做什么 |
| --- | --- | --- |
| 提取 DOCX 教材数据 | 提取 PDF 教材数据 | 分别扫描两种教材格式，建立可选课节清单，记录标题、正文、图片、篇幅和内容类型。 |
| 开发标准课节输入包工具 | 制定标注格式和评分标准 | A 把教材内容导出为统一输入包；B 规定人工标注文件有哪些字段、每个分数如何判定。两人互相检查结果。 |
| 开发 Textbook-to-Video 自动运行脚本 | 安装并运行 PresentAgent | A 让本系统能按实验表批量运行；B 负责让外部对照系统在固定环境下稳定产出。 |
| 执行 96 次内部完整运行 | 执行 8 次外部完整运行 | A 批量生成内部四个条件的所有重复结果；B 为 8 个正式课节各生成 1 个 PresentAgent 结果。 |
| 计算出现时机、布局和可靠性指标 | 计算内容、视觉语言模型和统计指标 | A 侧重程序可直接测量的工程指标；B 侧重内容质量、辅助模型评价和最终统计。 |
| 主标 4 个正式课节，复标另外 4 个 | 主标另外 4 个正式课节，复标前 4 个 | 每人都要看完 8 个正式课节。主标者先写完整标注，复标者独立检查并记录不同意见。 |
| 撰写系统方法和复现说明 | 撰写数据集、评价方法和结果 | A 说明系统如何运行和如何复现；B 说明数据怎样建立、分数怎样计算、结果怎样分析。最后共同审稿。 |

这里的“主标 4 个、复标 4 个”不是每人只处理 4 个课节。A 先完整标注 L01–L04，再独立复核 B 对 L05–L08 的标注；B 的工作方向相反。因此 8 个正式课节都会经过两个人检查，同时首次完整标注的工作量保持对半分。

两条工作线可以从第一周同时开始，目标工作量均约为 50%。虽然 A 的内部运行数量较多，但主要由脚本批量执行；B 的运行数量较少，却要承担环境适配、内容评价和统计分析，因此整体工作量应接近。

### 5.2 独立工作区

```text
A 工作线代码：
/ai/data/repos/Textbook-to-Video

A 工作线输出：
/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/runs/internal

B 工作线代码：
/ai/data/repos/PresentAgent

B 工作线输出：
/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/runs/presentagent

双方共用的冻结输入：
/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/sources/frozen
```

独立标注和评分目录：

```text
private_annotations/A
private_annotations/B
private_annotations/gold

ratings/A
ratings/B
ratings/resolved
```

约束：

- 两人不同时修改同一个云端 worktree；
- A 不修改 PresentAgent 输出目录；
- B 不修改内部系统输出目录；
- `sources/frozen` 冻结后只读；
- 两人不直接编辑对方标注；
- 通过清单文件和 Git 提交版本交接；
- 共享图形处理器或模型接口发生限流时，只调整运行时间，不改变实验配置。

### 5.3 并行节点

```text
阶段 1
A：生成 DOCX 课节候选清单，开发提取工具
B：生成 PDF 课节候选清单，制定数据格式规则，安装 PresentAgent

阶段 2
A：制作试运行课节 1 的标准输入包，开发内部自动运行脚本
B：制作试运行课节 2 的标准输入包，完成 PresentAgent 最小流程测试

阶段 3
A：主标 L01–L04，执行内部系统试运行
B：主标 L05–L08，执行 PresentAgent 试运行

阶段 4
A：L05–L08 复标、自动技术指标
B：L01–L04 复标、内容评价工具

阶段 5
A：96 次内部完整运行
B：8 次 PresentAgent 完整运行

阶段 6
A/B：交叉独立评分、统计和论文
```

### 5.4 共同冻结点

两人只在以下节点必须同步：

| 检查点 | 双方共同确认并锁定的内容 |
| --- | --- |
| F1 | 试运行和正式实验的课节名单 |
| F2 | 标准课节输入包 |
| F3 | 人工标准标注和保留评价题 |
| F4 | 内部系统与 PresentAgent 的试运行结果 |
| F5 | 正式配置、代码版本号和运行清单 |
| F6 | 匿名评分视频和评分标准 |
| F7 | 统计分析规则 |
| F8 | 最终结果表 |

每个冻结点记录：

- 日期；
- 文件哈希；
- A/B 确认；
- 未解决问题；
- 是否允许进入下一阶段。

## 6. TextbookEval-v1 的组成

TextbookEval-v1 只包括固定输入和人工标准标注，不包括系统输出。

```text
第 1 层：标准教材输入
  课节基本信息
  规范化教材正文
  教材图片
  来源文件指纹

第 2 层：人工标准评价数据
  核心知识点
  教材证据
  常见误解
  图片使用要求
  保留评价题

第 3 层：实验生成产物
  视频、音频和 HTML
  自动指标
  双人评分
  视觉语言模型评价结果
```

第 1 层和第 2 层组成数据集。

第 3 层是实验产物，不能根据生成结果反过来修改前两层，否则评价标准会被结果影响。

## 7. 当前教材与候选池

### 7.1 教材来源

当前项目已有：

| 来源 | 路径 | 结构 |
| --- | --- | --- |
| DOCX | `textbook.docx` | 按 style-2 识别章节、style-4 识别小节、style-5 识别子标题 |
| PDF | `references/义务教育信息科技教学指南 人工智能与智慧社会 人工智能专册 (1).pdf` | 已划分 27 个课节页码范围 |

原教材、完整正文和图片不进入公开 Git。

### 7.2 DOCX 编号

`produce --chapter --section` 使用从 0 开始的编号。主要正文章节：

| chapter | 章节 |
| ---: | --- |
| 3 | 绪论 |
| 4 | 数字素养 |
| 5 | 数字化转型 |
| 6 | 数字经济 |
| 7 | 大数据 |
| 8 | 人工智能 |
| 9 | 区块链 |
| 10 | 教育数字化转型 |
| 11 | 城市数字化转型 |
| 12 | “东数西算”工程 |

正式课节编号必须由候选清单脚本生成，不能依靠手工记忆编号。

### 7.3 当前优先候选

| 候选课节编号 | 内容 | 字符数 | 初步类型 | 处理 |
| --- | --- | ---: | --- | --- |
| `docx_ch08_s01` | 人工智能范式 | 698 | 概念 | 试运行候选 |
| `docx_ch05_s03` | 数字化转型实现路径 | 1622 | 流程 | 正式实验候选 |
| `docx_ch09_s02` | 信任体系 | 1860 | 概念/结构 | 正式实验候选 |
| `docx_ch09_s03` | 区块链是信任数据库 | 1796 | 图示/系统 | 试运行候选 |
| `docx_ch12_s01` | “东数西算”比拟性解读 | 1083 | 对比 | 正式实验候选 |
| `docx_ch12_s02` | “东数西算”逻辑性解读 | 944 | 流程/结构 | 正式实验候选 |
| `docx_ch05_s00` | 数字化转型概念演变 | 2427 | 概念 | 正式实验候选 |
| `docx_ch04_s00` | 从计算机技能到数字素养 | 3349 | 概念演变 | 需要拆分 |
| `docx_ch07_s01` | 认识数据 | 5856 | 概念/图示 | 必须拆分 |
| `docx_ch10_s00` | 教育信息化与教育数字化 | 8907 | 对比 | 必须拆分 |

还需从 PDF 中选择 4 个图片较丰富候选，最终纳入 2–3 个。

### 7.4 纳入标准

课节必须：

- 独立可理解；
- 解析结果完整；
- 约 700–2500 个中文字符；
- 包含 6–8 个可验证知识点；
- 适合 6–8 页；
- 适合约 90–150 秒讲解；
- 可以设计 8 道独立评价题；
- 有明确教材证据；
- 不依赖大量教材外知识。

### 7.5 排除标准

排除：

- 前言、结束语、习题、参考文献；
- 纯目录或纯引用；
- 文字识别或解析存在严重错误；
- 大量依赖上一节内容；
- 主要内容无法在目标时长表达；
- 图片、公式或表格无法可靠提取；
- 不能形成可靠的人工标准标注和评价题。

排除必须发生在正式生成之前并记录原因。不能因为某个系统结果差而替换课节。

### 7.6 类型配额

8 个正式实验课节：

| 类型 | 数量 |
| --- | ---: |
| 概念/定义 | 2 |
| 流程/算法 | 2 |
| 对比/辨析 | 2 |
| 图示/系统结构 | 2 |

来源建议：

```text
DOCX：5–6
PDF：2–3
```

## 8. 课节候选清单

课节候选清单是数据集建设的第一张总表。它先把所有可提取课节列出来，再按统一标准选择试运行、正式实验和备用课节。

### 8.1 需要实现的脚本

```text
scripts/build_lesson_catalog.py
```

目标命令：

```bash
python scripts/build_lesson_catalog.py \
  --docx textbook.docx \
  --pdf "references/义务教育信息科技教学指南 人工智能与智慧社会 人工智能专册 (1).pdf" \
  --output lesson_catalog.csv
```

### 8.2 清单字段

下列英文是 `lesson_catalog.csv` 中程序实际读取的列名。例如，`text_chars` 是正文字数，`image_count` 是图片数，`parse_warnings` 是解析警告，`exclusion_reason` 是排除原因。

```text
candidate_id
source_document_id
source_type
chapter_index
section_index
lesson_number
title
source_locator
text_chars
paragraph_count
image_count
caption_count
source_file_sha256
extracted_text_sha256
parse_warnings
technical_status
semantic_status
knowledge_type_candidate
difficulty_candidate
review_status
exclusion_reason
```

### 8.3 双人并行盘点

| A | B |
| --- | --- |
| 生成 DOCX 课节清单 | 生成 PDF 课节清单 |
| 检查标题样式划分是否正确 | 检查课节页码范围是否正确 |
| 提取 DOCX 图片 | 检查 PDF 图片 |
| 输出技术警告 | 输出文本或文字识别警告 |

完成后交换审查：

- A 审查 PDF 候选的语义完整性；
- B 审查 DOCX 候选的语义完整性；
- 共同选择 2 个试运行课节、8 个正式实验课节和 2–4 个备用课节。

## 9. 标准课节输入包

### 9.1 目的

Textbook-to-Video 和 PresentAgent 必须看到相同的正文范围和图片集合。

每个课节先生成唯一的标准课节输入包，再转换成两个系统各自需要的格式。这样做是为了保证 Textbook-to-Video 和 PresentAgent 获得相同的教材正文与图片。

### 9.2 目录

```text
sources/<lesson_id>/
├── source.json
├── source.md
├── source.private.json
├── source.pdf
├── images/
├── checksums.sha256
├── adapter_consistency.json
└── source_review.md
```

### 9.3 `source.json`

```json
{
  "dataset_version": "textbookeval-v1",
  "lesson_id": "docx_ch08_s01",
  "title": "人工智能范式",
  "language": "zh-CN",
  "paragraphs": [
    {
      "id": "p001",
      "text": "...",
      "source_locator": "docx:chapter=8;section=1;paragraph=1"
    }
  ],
  "images": [
    {
      "id": "img01",
      "filename": "img01.png",
      "caption": "...",
      "after_paragraph_id": "p002"
    }
  ],
  "normalized_text_sha256": "..."
}
```

### 9.4 规范化

计算文本哈希前：

- Unicode NFC；
- 换行统一；
- 连续空白压缩；
- 去除独立页码；
- 保留标点；
- 不改写教材内容；
- 不做繁简转换。

### 9.5 `source.pdf`

`source.pdf` 用于 PresentAgent 文档上传：

- 单栏；
- 统一字体；
- 无视觉装饰；
- 不加入总结；
- 不加入知识点列表；
- 不加入评价题；
- 图片按原文位置插入；
- 所有课节使用同一导出模板。

导出后重新提取 PDF 文本，与标准输入包中的规范化正文比较。

### 9.6 输入一致性

`adapter_consistency.json`：

```json
{
  "lesson_id": "docx_ch08_s01",
  "canonical_text_sha256": "...",
  "presentagent_text_sha256": "...",
  "text_match": true,
  "canonical_image_ids": ["img01"],
  "adapted_image_ids": ["img01"],
  "image_match": true,
  "warnings": []
}
```

正文或图片集合不一致时，不允许进入生成。

### 9.7 双人分配

| 课节 | 提取负责人 | 复核人 |
| --- | --- | --- |
| 试运行课节 1 | A | B |
| 试运行课节 2 | B | A |
| L01–L04 | A | B |
| L05–L08 | B | A |

提取负责人制作输入包；复核人独立提交审查报告，不直接修改负责人的文件。若发现问题，由负责人根据审查意见修正并重新生成文件指纹。

## 10. 人工标准标注

人工标准标注是后续评分所依据的“参考答案”。它必须在观看任何系统输出之前完成，以免研究者按照某个系统已经生成的内容倒推评价标准。

### 10.1 每课必需内容

每个课节：

- 6–8 个核心知识点；
- 每个知识点的教材证据；
- 重要性；
- 知识类型；
- 必须使用或可选使用的图片；
- 图片区域要求；
- 3–5 个常见误解；
- 适用的教学事件；
- 8 道只用于评价、不会提供给生成系统的保留题。

### 10.2 知识点

知识点必须是单一、可验证陈述。

错误：

```text
了解人工智能。
```

正确：

```text
知识驱动范式通过显式知识表示和推理规则解决问题。
```

字段：

```json
{
  "id": "kp01",
  "statement": "...",
  "importance": 2,
  "type": "concept",
  "required": true,
  "evidence_ids": ["ev01"],
  "image_ids": ["img01"]
}
```

### 10.3 教材证据

每条教材证据都要指向标准输入包中的段落或图片。`direct` 表示教材直接支持，`reasonable_inference` 表示可以合理推出，`insufficient` 表示证据不足，`contradictory` 表示与教材相矛盾。

```json
{
  "id": "ev01",
  "paragraph_ids": ["p002", "p003"],
  "support": "direct",
  "private_quote": "...",
  "note": "教材直接给出定义"
}
```

`support`：

```text
direct
reasonable_inference
insufficient
contradictory
```

### 10.4 图片使用要求

每张图片标为以下一种：

```text
required
optional
irrelevant
```

需要记录：

- 对应知识点；
- 图注；
- 必须解释的区域；
- 是否可替代；
- 可能的错误解释。

### 10.5 常见误解

这里记录本课最容易被讲错或理解错的说法，同时给出正确说法和教材证据。它既用于检查视频是否制造错误，也用于设计辨析题。

```json
{
  "id": "mc01",
  "incorrect_statement": "...",
  "correct_statement": "...",
  "knowledge_point_ids": ["kp02"],
  "evidence_ids": ["ev03"],
  "should_address": true
}
```

### 10.6 保留评价题

每课预先编写 8 道选择题，只在视频生成结束后用于评价。题目和答案不能出现在提供给任何生成系统的输入中。

每课 8 题：

| 类型 | 数量 |
| --- | ---: |
| 事实理解 | 2 |
| 概念辨析 | 2 |
| 应用 | 2 |
| 误解辨析 | 1 |
| 流程/图示 | 1 |

每题包含：

```json
{
  "id": "q01",
  "type": "application",
  "stem": "...",
  "options": {
    "A": "...",
    "B": "...",
    "C": "...",
    "D": "..."
  },
  "correct": "B",
  "knowledge_point_ids": ["kp03"],
  "evidence_ids": ["ev04"],
  "rationale": "...",
  "distractor_rationales": {
    "A": "...",
    "C": "...",
    "D": "..."
  }
}
```

评价题不得输入任何生成系统。

视频内生成的知识检测题不得与这 8 道保留评价题重复。

### 10.7 双人交叉标注

| 课节 | 首次完整标注者 | 独立复核者 |
| --- | --- | --- |
| L01–L04 | A | B |
| L05–L08 | B | A |

两人独立保存：

```text
annotation_A.json
annotation_B.json
```

仲裁后生成：

```text
annotation_gold.json
resolution_log.json
```

独立复核者不直接修改首次标注文件，只输出：

```text
annotation_review.json
quiz_review.json
```

### 10.8 标注自动检查器

需要实现：

```text
scripts/validate_annotation.py
```

检查：

- ID 唯一；
- 教材证据编号存在；
- paragraph/image 引用有效；
- 必须覆盖的核心知识点为 6–8 个；
- 每个必须覆盖的核心知识点都有证据；
- 每题答案有效；
- 每题绑定知识点；
- 评价题未进入标准课节输入包；
- JSON 文件符合预先定义的数据格式规则。

## 11. 数据集冻结

### 11.1 冻结内容

```text
2 个试运行标准课节输入包
8 个正式实验标准课节输入包
8 份正式实验人工标准标注
8 个课节 × 每课 8 道保留评价题
lesson_catalog.csv
dataset_selection.csv
data_dictionary.md
dataset_freeze_manifest.json
```

### 11.2 数据集完成条件

- 标准课节输入包的文件指纹完整；
- 文本和图片适配一致；
- 每人完成 4 个课节的首次完整标注和另外 4 个课节的独立复核；
- 每课有 6–8 个经过双方确认的核心知识点；
- 每课至少 3 个常见误解；
- 每课 8 道保留评价题；
- 双人一致性已计算；
- 每项分歧均有处理记录；
- 自动检查器全部通过；
- 可公开文件和包含教材原文的私有文件已分离；
- A、B 共同确认数据集冻结清单。

### 11.3 冻结后的修改规则

修改已经冻结的教材输入或人工标准标注时必须：

1. 提交修改申请；
2. 写明原因；
3. 对方复核；
4. 更新哈希；
5. 增加数据集修订版本号；
6. 判断是否需要重跑系统结果。

不能静默覆盖。

## 12. 内部实验运行器

### 12.1 需要实现

```text
scripts/build_run_matrix.py
scripts/run_experiment.py
scripts/verify_experiment.py
```

### 12.2 两阶段运行

运行器分成两步，是为了保证静态版和定时版只改变显示方式：

```text
第一步：准备共同内容（prepare-content）
  -> 开启或关闭教学计划
  -> 生成讲稿
  -> 生成分镜
  -> 生成音频
  -> 生成字幕
  -> 保存共同内容清单

第二步：渲染配对视频（render-pair）
  -> 生成静态展示版
  -> 生成定时逐步展示版
  -> 执行配对一致性检查
```

### 12.3 建议接口

```bash
python scripts/run_experiment.py prepare-content \
  --source sources/frozen/docx_ch08_s01/source.json \
  --lesson-plan off \
  --replicate 1 \
  --config experiments/textbookeval-v1/configs/experiment-v1.yaml \
  --output runs/internal/docx_ch08_s01/P0/r01
```

```bash
python scripts/run_experiment.py render-pair \
  --content-manifest runs/internal/docx_ch08_s01/P0/r01/content_manifest.json
```

### 12.4 配对一致性检查

自动验证：

- 旁白文字相同；
- 音频文件指纹相同；
- 字幕相同；
- 页面数量相同；
- 元素编号集合相同；
- 图片集合相同；
- 每页时长相同；
- 浏览器页面结构中的文字相同；
- 唯一差异是动画和元素出现时间。

检查失败的一对视频不进入评价，必须查清原因后按重试规则重新生成。

### 12.5 实验配置

```yaml
experiment_version: presentagent-comparison-v1
dataset_version: textbookeval-v1
model: ecnu-plus
theme: dark-blue-academic
voice: fixed_voice_id
rate: "+5%"
fps: 30
resolution: 1920x1080
target_slides:
  min: 6
  max: 8
target_duration_sec:
  min: 90
  max: 150
template_renderer: true
layout_repair_attempts: 2
agent_review: false
subtitles: true
textbook_images: true
max_attempts: 3
```

正式运行后不修改该配置。需要修改时建立新的实验版本。

## 13. PresentAgent 外部基线

### 13.1 安装位置

```text
/ai/data/repos/PresentAgent
```

建议固定：

```bash
source /ai/data/use_ai_env.sh
cd /ai/data/repos
git clone https://github.com/AIGeeksGroup/PresentAgent.git
cd PresentAgent
git checkout b9990e990c86c3709e18e9979bc36ac959d3b4d4
```

正式运行前重新确认代码版本号是否仍与论文对应。

### 13.2 环境

按官方要求使用独立 Python 3.11 环境：

```bash
conda create -n presentagent python=3.11
conda activate presentagent
pip install -r requirements.txt
```

记录：

- LLM；
- 视觉语言模型；
- 文本向量模型；
- MegaTTS3 模型文件版本；
- ffmpeg；
- LibreOffice；
- Python 依赖；
- GPU；
- API；
- 演示文稿模板；
- Git 代码版本号。

### 13.3 固定 PPT 模板

```text
/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/templates/presentagent-neutral.pptx
```

要求：

- 16:9；
- 中文字体正常；
- 高对比度；
- 无品牌；
- 无答案提示；
- 所有课节共用；
- 不为单个课节修改。

### 13.4 官方版与改造版

如果保持官方流程和 MegaTTS3，可标记：

```text
官方 PresentAgent
```

如果替换文字转语音模块、修改输入格式转换程序或改动生成逻辑，应标记：

```text
改造版 PresentAgent
```

所有修改都要保存代码差异文件和文字说明，以免把改造后的能力误当成官方系统能力。

### 13.5 不允许人工润色

在生成 PPT 和 PPT-to-video 之间不得人工修改：

- 文字；
- 图片；
- 版式；
- 讲稿；
- 动画；
- 页数。

发生人工修改的结果只能标记为“人工辅助版”，不进入主要对照结果。

### 13.6 每课保存

```text
runs/presentagent/<lesson_id>/
├── input/
├── generated.pptx
├── narration/
├── audio/
├── final.mp4
├── operation_log.json
├── environment.json
└── run_manifest.json
```

## 14. 试运行流程

### 14.1 建议课节

| 试运行编号 | 内容 | 目的 |
| --- | --- | --- |
| P01 | 人工智能范式 | 基础概念和短文本 |
| P02 | 区块链是信任数据库 | 检查图片、结构和元素出现时机 |

### 14.2 运行前

```bash
source /ai/data/use_ai_env.sh
cd /ai/data/repos/Textbook-to-Video
t2v doctor --ping
python -m pytest tests/ -q
```

确认：

- LLM；
- TTS；
- ffmpeg；
- 浏览器；
- 图片；
- 输出目录。

### 14.3 试运行检查

- 能播放；
- 有声音；
- 字幕完整；
- 页面时长正确；
- 图片正确；
- 静态版一次显示全部页内元素；
- 定时版按旁白逐步显示；
- 无空白页；
- 无严重遮挡；
- 配对一致性检查通过；
- PresentAgent 中文字体正常；
- PPT 和视频都保存；
- 成本和耗时可接受。

### 14.4 试运行通过条件

通过条件：

- 16 次内部目标运行均有成功或失败状态记录；
- 2 次 PresentAgent 运行均有状态记录；
- 四条件至少各有一个成功样本；
- 成功的视频配对全部通过一致性检查；
- 无系统性音频、图片或布局错误；
- 自动评分能完整输出；
- 正式成本可接受。

只允许修复流程问题，不能只优化某一个条件。

## 15. 正式运行

### 15.1 正式运行清单

内部 `formal_run_matrix.csv` 共 96 行：

每一行代表一次预定运行。下面这些英文是 CSV 的实际列名，分别记录运行编号、课节、实验条件、重复次数、随机顺序、执行状态、重试次数以及它是否被选为标准评分结果。

```text
run_id
lesson_id
condition
lesson_plan
timing
replicate
content_pair_id
randomized_order
planned_seed
status
attempt_count
canonical
notes
```

外部 `presentagent_run_matrix.csv` 共 8 行。

### 15.2 随机顺序

不能先运行全部 C00，再运行 C11。

使用固定的随机种子打乱并交错运行：

```text
lesson A P0 r1
lesson C P1 r2
lesson H P0 r3
lesson B P1 r1
...
```

### 15.3 重试规则

允许重试：

- 网络超时；
- API 5xx；
- TTS 临时失败；
- 浏览器崩溃；
- ffmpeg 非内容性失败。

不允许重试：

- 结果不好看；
- 分数低；
- 不喜欢页面；
- 想获得更好结论。

每次共同内容生成最多尝试 3 次。第一次完整成功的结果有效，失败尝试不删除。

### 15.4 每日状态

A、B 每天分别保存：

```text
logs/status_A_YYYY-MM-DD.json
logs/status_B_YYYY-MM-DD.json
```

字段：

```text
date
track
completed_run_ids
failed_run_ids
blocking_issue
next_actions
artifact_manifest_path
content_opened
```

只有以下问题需要暂停双方：

- source hash 不一致；
- 图片集合不一致；
- 配置变化；
- 评价题泄漏；
- 正式运行中途需要修改代码；
- 输出目录或运行编号冲突。

## 16. 评价指标

### 16.1 运行可靠性

- 生成成功率：计划运行中有多少最终成功；
- 首次成功率：无需重试就成功的比例；
- 重试次数；
- 运行耗时；
- 估算成本；
- 输出视频时长；
- 输出页面数量。

### 16.2 结构完整性

- 分镜文件格式是否正确；
- 元素编号完整率；
- 动画目标有效率；
- 音频/页面数量一致率；
- 字幕覆盖率；
- 页面布局检查通过率；
- 空白页比例；
- 图片解析失败率；
- 元素出现时间警告数。

### 16.3 核心知识点覆盖率

把每个经过双方确认的核心知识点标为：

```text
完整且正确覆盖 = 1.0
部分覆盖 = 0.5
未覆盖 = 0.0
讲解错误 = 0.0
```

加权覆盖率：

```text
Weighted KPC =
Σ importance(kp) × coverage_score(kp)
/ Σ importance(kp)
```

讲解错误还要另行计入事实错误指标，不能只表现为覆盖率降低。

### 16.4 教材忠实度

先把视频拆成可以判断真假的事实性陈述，再把每条陈述分为：

```text
教材直接支持
可由教材合理推出
教材之外但内容正确
教材不支持
内容错误
与教材矛盾
```

报告：

- 有教材支持的陈述比例；
- 无教材支持的陈述数量；
- 严重错误数量；
- 每分钟无依据生成内容的比例。

教材外但正确的扩展知识不能与错误混为一类。

### 16.5 教材图片对应准确性

- 必需教材图片使用率；
- 图片与讲解内容正确对应的比例；
- 指定图片区域解释准确率；
- 图注与讲解一致性；
- 使用错误图片的数量。

### 16.6 元素出现时机

```text
onset_error =
visual_onset - narration_onset
```

报告：

- 平均出现时间误差：用于判断整体偏早还是偏晚；
- 平均绝对时间误差：不考虑方向，只看偏差有多大；
- 过早显示比例：比相关旁白早 `2` 秒以上；
- 过晚显示比例：比相关旁白晚 `2` 秒以上；
- 过早显示持续时间占比；
- 找不到对应旁白或画面元素的比例。

这些指标只能说明画面和旁白是否同步，不能单独证明学习效果。

### 16.7 教学与视觉评分

双人独立评分：

| 指标 | 形式 |
| --- | --- |
| 教材忠实度 | 1–5 |
| 教学结构 | 1–5 |
| 常见误解处理 | 1–5 |
| 教材图片对应准确性 | 1–5；不适用时记为 N/A |
| 视觉清晰度 | 1–5 |
| 旁白连贯性 | 1–5 |
| 音画协调性 | 1–5 |
| 动画帮助程度 | 1–5；不适用时记为 N/A |
| 总体质量 | 1–5 |

问题标签：

```text
factual_error
unsupported_claim
missing_key_point
image_mismatch
visual_overload
distracting_animation
narration_mismatch
layout_defect
```

## 17. 双人独立评分

### 17.1 匿名化

```text
原文件名
docx_ch08_s01_C11_r01.mp4

匿名文件名
V017.mp4
```

私有映射：

```text
ratings/blind_mapping.private.csv
```

### 17.2 评分规则

1. A、B 分别评分，不查看对方结果；
2. 同一课节的不同系统版本打乱顺序；
3. 使用相同教材输入、人工标准标注和评分标准；
4. 视觉语言模型分数在双人评分完成前不展示；
5. 评分后计算一致性；
6. 事实错误、知识点覆盖和图片对应判断可以由双方讨论后裁定；
7. 主观评分保留两份原始值。

由于评分者也是项目研究者，论文中应称为：

```text
两名研究者独立评分
```

不能描述为完全独立的外部专家实验。

### 17.3 工作量平衡

第一轮：

```text
A：V001–V020
B：V021–V040
```

第二轮交换：

```text
A：V021–V040
B：V001–V020
```

每次最多 8–10 个视频，避免疲劳。

### 17.4 一致性

- 类别判断使用 Cohen's kappa，衡量两人对“有/无错误”等分类是否一致；
- 1–5 等级评分使用组内相关系数（ICC），衡量两人的分数是否接近；
- 报告原始分歧数量；
- 仲裁后结果与独立结果分开保存。

## 18. 视觉语言模型辅助评价

视觉语言模型可以读取视频画面、字幕或抽帧图像。本实验让它完成以下辅助任务：

- 回答每课 8 道保留评价题；
- 辅助内容和视觉评分；
- 与双人评分做一致性分析；
- 复现 PresentEval 风格评价。

要求：

- 负责评价的模型与负责生成视频的模型分离；
- 条件和系统名称匿名；
- 固定评价提示词；
- 固定模型版本；
- 输入方式对所有系统一致；
- 每个样本重复判断 3 次或使用多个评价模型；
- 保存模型的原始回答；
- 不把保留评价题输入生成系统。

视觉语言模型的答题分数只能表述为：

```text
模型模拟的信息可恢复性
```

它表示“从视频中是否容易找回正确信息”，不能表述为真实学习成绩，也不能代替学习者实验。

## 19. 统计分析

### 19.1 内容层指标

静态版和定时版共用内容，因此核心知识点覆盖率、陈述忠实度和无依据生成比例只按内容分支计算一次：

```text
metric ~ LessonPlan
         + KnowledgeType
         + LessonPlan:KnowledgeType
         + (1 | Lesson)
```

不能把同一内容复制成 Static/Timed 两个独立样本。

### 19.2 四条件指标

元素出现时机、视觉和总体评分：

```text
metric ~ LessonPlan * TimedAnimation
         + KnowledgeType
         + TimedAnimation:KnowledgeType
         + (1 | Lesson)
         + (1 | ContentPair)
```

重点报告：

- 教学计划的整体影响；
- 定时逐步展示的整体影响；
- `LessonPlan × TimedAnimation`；
- `TimedAnimation × KnowledgeType`。

这里的“整体影响”指在平均考虑另一个开关状态后，单独打开某个开关带来的变化；带 `×` 的项用于判断两个因素是否会相互增强或削弱。

### 19.3 PresentAgent 比较

按课节一一配对：

```text
metric ~ System + KnowledgeType + (1 | Lesson)
```

样本较少时同时报告：

- 每个课节分别报告结果；
- 同一课节两个系统之间的差值；
- 用重采样方法估计的 95% 置信区间；
- 平均值和中位数。

### 19.4 报告要求

除 p 值外报告：

- 百分点差；
- 效应量，即差异有多大；
- 95% 置信区间，即结果可能的波动范围；
- 两名评分者的一致性指标；
- 失败率；
- 成本差异；
- 运行耗时差异。

次要比较使用 Holm 多重比较校正，降低同时检验多个指标时偶然得到“显著结果”的概率。临时增加的探索性分析要单独标记，不能假装成预先设定的主要结论。

## 20. 数据与目录

### 20.1 Git

```text
experiments/textbookeval-v1/
├── README.md
├── schemas/
│   ├── lesson-annotation.schema.json
│   ├── run-manifest.schema.json
│   └── rating.schema.json
├── metadata/
│   └── lessons.csv
├── annotations/
├── instruments/
│   ├── annotator-guide.md
│   ├── rating-rubric.md
│   └── question-writing-guide.md
├── configs/
│   └── experiment-v1.yaml
└── analysis/
    ├── analysis-plan.md
    └── table-specs.md
```

Git 保存：

- 数据格式规则；
- 不含教材原文等敏感内容的元数据；
- 标注规范；
- 配置；
- 脚本；
- 聚合统计；
- 可公开标注。

### 20.2 私有云端

```text
/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/
├── sources/
├── private_annotations/
├── runs/
│   ├── internal/
│   └── presentagent/
├── videos/
├── ratings/
├── logs/
└── exports/
```

云端保存：

- 教材；
- 完整正文；
- 图片；
- source PDF；
- 音频；
- HTML；
- 视频；
- 教材证据原文；
- 原始评分。

密钥不得进入任何实验目录或日志。

## 21. 需要实现的文件

### 21.1 数据集

```text
scripts/build_lesson_catalog.py
scripts/export_lesson_source.py
scripts/validate_annotation.py
experiments/textbookeval-v1/schemas/lesson-annotation.schema.json
experiments/textbookeval-v1/metadata/lessons.csv
```

### 21.2 实验运行

```text
scripts/build_run_matrix.py
scripts/run_experiment.py
scripts/verify_experiment.py
experiments/textbookeval-v1/configs/experiment-v1.yaml
```

### 21.3 评价

```text
scripts/score_experiment.py
scripts/blind_experiment.py
experiments/textbookeval-v1/instruments/rating-rubric.md
experiments/textbookeval-v1/instruments/question-writing-guide.md
```

### 21.4 分析

```text
scripts/analyze_experiment.py
experiments/textbookeval-v1/analysis/analysis-plan.md
experiments/textbookeval-v1/analysis/table-specs.md
```

## 22. 执行顺序

### 阶段检查点 A：候选课节与标准输入包

通过条件：

- DOCX/PDF 课节候选清单完成；
- 2 个试运行课节；
- 8 个正式实验课节；
- 2–4 个备用；
- 两个系统使用的文字和图片一致；
- 文件指纹完整。

### 阶段检查点 B：人工标准标注

通过条件：

- 双人独立标注；
- 每课 6–8 个核心知识点；
- 教材证据完整；
- 图片要求完整；
- 常见误解完整；
- 每课 8 道保留评价题；
- 自动检查器通过；
- 人工标准标注已冻结。

### 阶段检查点 C：试运行

通过条件：

- 16 次内部运行有完整状态；
- 2 次 PresentAgent 运行有完整状态；
- 配对一致性检查通过；
- 无系统性音频、图片和布局问题；
- 自动评分可运行；
- 成本可接受。

### 阶段检查点 D：正式实验配置冻结

冻结：

- 数据集；
- 本系统代码版本号；
- PresentAgent 代码版本号；
- 提示词文件指纹；
- 实验配置；
- 演示文稿模板；
- 运行清单；
- 重试规则；
- 评分标准；
- 统计方案。

### 阶段检查点 E：生成产物

通过条件：

- 96 次内部运行状态完整；
- 8 次 PresentAgent 运行状态完整；
- 失败未删除；
- 清单文件完整；
- 标准评分结果已按预定规则确定；
- 视频可播放。

### 阶段检查点 F：评分与统计分析

通过条件：

- 40 个视频完成双人独立评分；
- 视觉语言模型辅助评价完成；
- 双人评分一致性计算完成；
- 自动指标完成；
- 分析脚本锁定；
- 结果表可重复生成。

## 23. 并行时间表

| 周次 | A 工作线 | B 工作线 | 共同输出 |
| --- | --- | --- | --- |
| 第 1 周 | DOCX 课节清单、标准输入工具 | PDF 课节清单、数据格式规则、安装 PresentAgent | 候选池 |
| 第 2 周 | 试运行课节 1、内部运行脚本 | 试运行课节 2、PresentAgent 最小流程测试 | 试运行数据与标注 |
| 第 3 周 | L01–L04 主标、内部系统试运行 | L05–L08 主标、PresentAgent 试运行 | 通过试运行检查 |
| 第 4 周 | L05–L08 复标、技术指标 | L01–L04 复标、内容指标 | 数据集冻结 |
| 第 5 周 | 96 次内部运行 | 8 次 PresentAgent 运行、评分准备 | 生成产物齐备 |
| 第 6 周 | 自动指标、20 个视频初评 | 视觉语言模型评价、另外 20 个视频初评 | 第一轮评分 |
| 第 7 周 | 交换评分、系统分析 | 交换评分、统计分析 | 评分结果锁定 |
| 第 8 周 | 方法、复现、失败案例 | 数据集、评价、结果 | 实验章节 |

若共享 GPU/API，生成任务可以错峰；数据、代码、标注和评分仍按双轨并行。

## 24. 现在开始做什么

第一轮只做：

1. 创建 `experiments/textbookeval-v1/`。
2. A 实现 DOCX 课节候选清单。
3. B 生成 PDF 课节候选清单并定义标注文件格式。
4. 合并候选池。
5. 选择两个试运行课节。
6. A 导出试运行课节 1 的标准输入包。
7. B 导出试运行课节 2 的标准输入包。
8. 交换复核。
9. 两人独立标注试运行课节。
10. A 开发内部自动运行脚本。
11. B 安装 PresentAgent 并完成一次最小流程测试。
12. 通过试运行检查后，再选择和建设 8 个正式实验课节。

第一轮结束时应存在：

```text
experiments/textbookeval-v1/
├── README.md
├── schemas/
│   ├── lesson-annotation.schema.json
│   └── run-manifest.schema.json
└── metadata/
    └── lesson_catalog.public.csv

/ai/data/textbook-to-video/experiments/presentagent-comparison-v1/
├── extracted/lesson_catalog.csv
├── sources/draft/A/<pilot-1>/
├── sources/draft/B/<pilot-2>/
├── private_annotations/A/
└── private_annotations/B/
```

在这些文件完成并通过交叉检查前，不开始正式 96 个 run。

## 25. 结论表述边界

实验完成后可以主张：

- 教学计划改善了哪些内容和教学结构指标；
- 定时逐步展示改善了哪些同步指标；
- 哪类知识受益更明显；
- Full System 与 PresentAgent 在教材场景下有何差异；
- 系统的失败率、成本和稳定性；
- TextbookEval-v1 如何支持教材视频评价。

不能主张：

- 已经证明真实学习效果；
- 动画一定提高所有内容的理解；
- 结果适用于所有教材、学科和语言；
- 视觉语言模型答题等同于学习者理解；
- 两名项目研究者的评分等同于完全外部专家评审。

最稳妥的论文结论是：

> 本研究构建了面向教材教学视频的 TextbookEval-v1，并通过可控的“教学计划 × 定时逐步展示”双因素实验和原始 PresentAgent 外部对照，评价教学内容规划、教材忠实度、教材图片对应准确性、页面内时序呈现和工程可靠性。结果用于说明这些机制对生成质量和信息可恢复性指标的影响，不延伸为未经验证的真实学习效果结论。
